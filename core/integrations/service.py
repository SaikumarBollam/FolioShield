"""
Tenant-scoped integration service.

This is the shared application service used by the enterprise API, the
on-premises agent, and embedded views. It delegates all dispute business
logic to the existing FolioShield SDK and existing core modules.
"""

from __future__ import annotations

import base64
from typing import Any, Dict, Optional

from ..client import FolioShield
from ..extractor import DocumentExtractor
from ..models import EvidenceItem
from ..security import validate_upload
from .contracts import DocumentSubmission, IntegrationCaseRef, IntegrationEvent, TenantContext
from .registry import IntegrationRegistry
from .webhooks import WebhookManager


class IntegrationService:
    """Tenant-aware orchestration around the existing FolioShield engine."""

    def __init__(self, registry: IntegrationRegistry, engine: Optional[FolioShield] = None,
                 webhooks: Optional[WebhookManager] = None):
        self.registry = registry
        self.engine = engine or FolioShield()
        self.webhooks = webhooks or WebhookManager(registry)

    # ------------------------------------------------------------------ events

    def _emit(self, context: TenantContext, event_type: str, case_id: Optional[str], data: Optional[Dict[str, Any]] = None) -> IntegrationEvent:
        event = IntegrationEvent(
            event_type=event_type,
            tenant_id=context.tenant_id,
            case_id=case_id,
            actor_id=context.actor_id,
            data=data or {},
        )
        try:
            self.webhooks.publish(event)
        except Exception:
            # Webhook delivery must never break dispute processing.
            pass
        return event

    # ------------------------------------------------------------------ cases

    def create_case(self, context: TenantContext, case_ref: IntegrationCaseRef,
                    notice: Optional[Dict[str, Any]] = None, folio: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        context.require_scope("cases:write")
        payload = {"notice": notice or {}, "folio": folio or {}, "documents": [], "status": "received"}
        record = self.registry.upsert_case(context, case_ref, payload)
        self._emit(context, "dispute.received", case_ref.case_id, {"external_case_id": case_ref.external_case_id})
        return record

    def get_case(self, context: TenantContext, case_id: str) -> Optional[Dict[str, Any]]:
        context.require_scope("cases:read")
        return self.registry.get_case(context.tenant_id, case_id)

    def list_cases(self, context: TenantContext) -> list[Dict[str, Any]]:
        context.require_scope("cases:read")
        return self.registry.list_cases(context.tenant_id)

    # --------------------------------------------------------------- documents

    def upload_document(self, context: TenantContext, case_id: str, document_type: str,
                        filename: str, media_type: str, data: bytes,
                        evidence_doc_type: Optional[str] = None) -> Dict[str, Any]:
        context.require_scope("documents:write")
        validate_upload(data, filename, max_bytes=self.engine.settings.max_upload_bytes)
        record = self.registry.get_case(context.tenant_id, case_id)
        if not record:
            raise KeyError("Case not found for tenant")
        payload = record["payload"]
        submission = DocumentSubmission.for_bytes(
            document_type, filename, media_type, data, source=context.actor_type,
            evidence_doc_type=evidence_doc_type)

        if document_type == "dispute_notice":
            text = DocumentExtractor.extract_text_from_pdf(data)
            payload["notice"] = DocumentExtractor.parse_dispute_notice(text)
        elif document_type == "guest_folio":
            if filename.lower().endswith(".csv"):
                payload["folio"] = DocumentExtractor.parse_folio_csv(data)
            else:
                text = DocumentExtractor.extract_text_from_pdf(data)
                payload["folio"] = DocumentExtractor.parse_folio_pdf(text)
        elif document_type == "supporting_evidence":
            docs = payload.setdefault("supporting_docs", {})
            doc_type = evidence_doc_type or "supporting_document"
            docs[doc_type] = EvidenceItem(
                doc_type=doc_type, present=True, filename=filename,
                sha256=submission.sha256, verified_by=context.actor_id,
                size_bytes=submission.size_bytes, mime=media_type, stored_ref=submission.sha256,
            ).to_dict()
        else:
            raise ValueError(f"Unsupported document_type: {document_type}")

        payload.setdefault("documents", []).append(submission.to_dict())
        payload["status"] = "documents_collected"
        case_ref = IntegrationCaseRef.from_dict(record["case_ref"])
        saved = self.registry.upsert_case(context, case_ref, payload)
        self._emit(context, "document.processed", case_id, {"document_type": document_type, "sha256": submission.sha256})
        return {"case": saved, "document": submission.to_dict()}

    # -------------------------------------------------------------- processing

    def reconcile_case(self, context: TenantContext, case_id: str) -> Dict[str, Any]:
        context.require_scope("cases:process")
        record = self.registry.get_case(context.tenant_id, case_id)
        if not record:
            raise KeyError("Case not found for tenant")
        payload = record["payload"]
        recon = self.engine.reconcile(payload.get("notice") or {}, payload.get("folio") or {},
                                      supporting_docs=payload.get("supporting_docs"))
        payload["reconciliation"] = recon
        payload["status"] = "reconciled"
        saved = self.registry.upsert_case(context, IntegrationCaseRef.from_dict(record["case_ref"]), payload)
        self._emit(context, "reconciliation.completed", case_id, {"completeness_score": recon.get("completeness_score")})
        if recon.get("missing_evidence"):
            self._emit(context, "evidence.missing_identified", case_id, {"missing_evidence": recon.get("missing_evidence")})
        return {"case": saved, "reconciliation": recon}

    def draft_rebuttal(self, context: TenantContext, case_id: str, custom_instructions: Optional[str] = None) -> Dict[str, Any]:
        context.require_scope("cases:process")
        result = self.reconcile_case(context, case_id)
        record = result["case"]
        payload = record["payload"]
        draft = self.engine.draft_rebuttal(payload.get("notice") or {}, payload.get("folio") or {},
                                           payload["reconciliation"], custom_instructions=custom_instructions)
        payload["rebuttal_text"] = draft
        payload["status"] = "rebuttal_drafted"
        # Important: drafting is machine processing, not human approval.
        payload["approval"] = None
        saved = self.registry.upsert_case(context, IntegrationCaseRef.from_dict(record["case_ref"]), payload)
        self._emit(context, "rebuttal.drafted", case_id, {"engine": self.engine.llama_engine.last_engine_used})
        return {"case": saved, "rebuttal_text": draft, "engine": self.engine.llama_engine.last_engine_used}

    def process_case(self, context: TenantContext, case_id: str, custom_instructions: Optional[str] = None,
                     policy_text: Optional[str] = None) -> Dict[str, Any]:
        """Run existing reconciliation + drafting. Does not approve or submit."""
        drafted = self.draft_rebuttal(context, case_id, custom_instructions=custom_instructions)
        record = drafted["case"]
        payload = record["payload"]
        return {
            "case_id": case_id,
            "tenant_id": context.tenant_id,
            "status": payload.get("status"),
            "reconciliation": payload.get("reconciliation"),
            "rebuttal_text": payload.get("rebuttal_text"),
            "approval": None,
            "human_approval_required": True,
        }

    def generate_packet(self, context: TenantContext, case_id: str, approved_by: str,
                        approval_fingerprint: str, policy_text: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate a packet only when the caller supplies an explicit human
        approval reference. This method does not create approval.
        """
        context.require_scope("packets:generate")
        if not approved_by or not approval_fingerprint:
            raise PermissionError("Explicit human approval reference is required to generate a packet")
        record = self.registry.get_case(context.tenant_id, case_id)
        if not record:
            raise KeyError("Case not found for tenant")
        payload = record["payload"]
        if not payload.get("rebuttal_text"):
            self.draft_rebuttal(context, case_id)
            record = self.registry.get_case(context.tenant_id, case_id) or record
            payload = record["payload"]
        pdf_bytes = self.engine.generate_pdf_packet_hashed(
            payload.get("notice") or {}, payload.get("folio") or {}, payload.get("reconciliation") or {},
            payload.get("rebuttal_text") or "", approved_by=approved_by, policy_text=policy_text,
            approval_fingerprint=approval_fingerprint, chain_head=self.engine.audit_logger.chain_head)
        payload["packet_sha256"] = self.engine.audit_logger.calculate_sha256(pdf_bytes)
        payload["status"] = "packet_generated"
        payload["approval"] = {"approved_by": approved_by, "approval_fingerprint": approval_fingerprint}
        saved = self.registry.upsert_case(context, IntegrationCaseRef.from_dict(record["case_ref"]), payload)
        self._emit(context, "packet.generated", case_id, {"packet_sha256": payload["packet_sha256"]})
        return {"case": saved, "pdf_base64": base64.b64encode(pdf_bytes).decode("utf-8"),
                "packet_sha256": payload["packet_sha256"]}

    def audit_for_case(self, context: TenantContext, case_id: str) -> Dict[str, Any]:
        context.require_scope("audit:read")
        record = self.registry.get_case(context.tenant_id, case_id)
        if not record:
            raise KeyError("Case not found for tenant")
        return {
            "case_id": case_id,
            "tenant_id": context.tenant_id,
            "chain_head": self.engine.audit_logger.chain_head,
            "manifest": self.engine.audit_logger.build_case_manifest(case_id),
            "case_status": (record.get("payload") or {}).get("status"),
        }
