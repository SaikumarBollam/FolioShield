"""
FolioShield SDK / Library Integration Interface.
Enables programmatic, headless integration directly inside backend hotel services,
Property Management Systems (OPERA, Cloudbeds, Mews), and Building/Hotel Management Systems.
"""

import base64
import time
import uuid
from typing import Dict, Any, Optional, Union

import requests

from .models import NoticeData, FolioData, DisputePacketResponse, SubmissionRecord, OutcomeRecord
from .extractor import DocumentExtractor
from .reconciler import Reconciler
from .llm_engine import LlamaEngine
from .pdf_generator import EvidencePacketGenerator
from .audit_logger import AuditLogger
from .config import config, Settings


class FolioShield:
    """
    High-level Python SDK client for FolioShield.

    Usage:
        from core.client import FolioShield

        fs = FolioShield()

        # Ingest directly from PMS dictionary or objects:
        result = fs.process_dispute(
            notice_pdf_bytes=notice_bytes,
            folio=folio_dict_or_object,
            reviewer_name="Night Auditor John",
            generate_pdf=True
        )
        print(result.rebuttal_text)
        print(result.completeness_score)
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        api_key: Optional[str] = None,
        merchant_name: Optional[str] = None,
        settings: Optional[Settings] = None
    ):
        self.settings = settings or config
        self.merchant_name = merchant_name or self.settings.merchant_name
        self.llama_engine = LlamaEngine(
            provider=provider or self.settings.llama_provider,
            api_key=api_key or self.settings.get_api_key_for_provider(provider or self.settings.llama_provider)
        )
        self.audit_logger = AuditLogger(log_dir=self.settings.log_dir)
        from .application.dispute_service import DisputeService
        self.service = DisputeService(
            settings=self.settings,
            audit_logger=self.audit_logger,
            llama_engine=self.llama_engine,
        )

    def extract_notice_from_pdf(self, pdf_bytes: bytes) -> NoticeData:
        """Extracts structured notice data from raw PDF bytes."""
        raw_text = DocumentExtractor.extract_text_from_pdf(pdf_bytes)
        parsed = DocumentExtractor.parse_dispute_notice(raw_text)
        return NoticeData.from_dict(parsed)

    def extract_notice_with_ocr(self, pdf_bytes: bytes) -> NoticeData:
        """
        Extracts notice data, using the vision model as an OCR fallback for
        scanned / image-only notices. Raises ExtractionError if both fail.
        """
        raw_text = DocumentExtractor.extract_text_with_ocr_fallback(
            pdf_bytes, ocr_text_provider=self.llama_engine.extract_text_from_image
        )
        parsed = DocumentExtractor.parse_dispute_notice(raw_text)
        return NoticeData.from_dict(parsed)

    def extract_folio_from_pdf(self, pdf_bytes: bytes) -> FolioData:
        """Extracts structured folio data from raw PDF bytes."""
        raw_text = DocumentExtractor.extract_text_from_pdf(pdf_bytes)
        parsed = DocumentExtractor.parse_folio_pdf(raw_text)
        if not parsed.get("hotel_name"):
            parsed["hotel_name"] = self.merchant_name
        return FolioData.from_dict(parsed)

    def extract_folio_from_csv(self, csv_bytes: bytes) -> FolioData:
        """Extracts structured folio data from PMS CSV exports."""
        parsed = DocumentExtractor.parse_folio_csv(csv_bytes)
        if not parsed.get("hotel_name"):
            parsed["hotel_name"] = self.merchant_name
        return FolioData.from_dict(parsed)

    def reconcile(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        supporting_docs: Optional[Dict[str, bool]] = None
    ) -> Dict[str, Any]:
        """Cross-checks dispute against guest folio and evidence checklist."""
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        if not f_dict.get("hotel_name"):
            f_dict["hotel_name"] = self.merchant_name
        return Reconciler.reconcile(n_dict, f_dict, supporting_docs=supporting_docs)

    def draft_rebuttal(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        reconciliation: Dict[str, Any],
        custom_instructions: Optional[str] = None
    ) -> str:
        """Drafts formal dispute rebuttal using Meta Llama or deterministic fallback."""
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        return self.llama_engine.draft_rebuttal(
            n_dict, f_dict, reconciliation, custom_instructions=custom_instructions
        )

    def generate_pdf_packet(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        reconciliation: Dict[str, Any],
        rebuttal_text: str,
        approved_by: Optional[str] = "Hotel Management",
        approved_at: Optional[str] = None,
        policy_text: Optional[str] = None
    ) -> bytes:
        """Compiles the 3-page standardized dispute packet PDF bytes."""
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        if not f_dict.get("hotel_name"):
            f_dict["hotel_name"] = self.merchant_name
        return EvidencePacketGenerator.generate_packet(
            n_dict,
            f_dict,
            reconciliation,
            rebuttal_text,
            approved_by=approved_by,
            approved_at=approved_at,
            policy_text=policy_text
        )

    def generate_pdf_packet_hashed(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        reconciliation: Dict[str, Any],
        rebuttal_text: str,
        approved_by: Optional[str] = "Hotel Management",
        approved_at: Optional[str] = None,
        policy_text: Optional[str] = None,
        approval_fingerprint: Optional[str] = None,
        chain_head: Optional[Dict[str, Any]] = None,
        packet_format: str = "executive",
        exhibit_files: Optional[Dict[str, bytes]] = None
    ) -> bytes:
        """
        Two-pass packet build: pass 1 computes the packet SHA-256, pass 2
        embeds it (plus approval fingerprint + chain head) in the p.3 custody
        block so the downloaded file is self-verifying.

        packet_format="executive" produces exactly 3 pages (default, unchanged).
        packet_format="complete" appends an exhibit appendix after page 3.
        """
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        if not f_dict.get("hotel_name"):
            f_dict["hotel_name"] = self.merchant_name
        first_pass = EvidencePacketGenerator.generate_packet(
            n_dict, f_dict, reconciliation, rebuttal_text,
            approved_by=approved_by, approved_at=approved_at, policy_text=policy_text,
            approval_fingerprint=approval_fingerprint, chain_head=chain_head,
            packet_format=packet_format, exhibit_files=exhibit_files,
        )
        packet_hash = AuditLogger.calculate_sha256(first_pass)
        return EvidencePacketGenerator.generate_packet(
            n_dict, f_dict, reconciliation, rebuttal_text,
            approved_by=approved_by, approved_at=approved_at, policy_text=policy_text,
            approval_fingerprint=approval_fingerprint, chain_head=chain_head,
            packet_sha256=packet_hash,
            packet_format=packet_format, exhibit_files=exhibit_files,
        )

    def process_dispute(
        self,
        notice: Union[NoticeData, Dict[str, Any], bytes],
        folio: Union[FolioData, Dict[str, Any], bytes],
        supporting_docs: Optional[Dict[str, bool]] = None,
        custom_instructions: Optional[str] = None,
        reviewer_name: str = "Automated PMS Connector",
        generate_pdf: bool = True,
        policy_text: Optional[str] = None
    ) -> DisputePacketResponse:
        """
        Complete end-to-end processing pipeline suitable for headless PMS/BMS webhooks or jobs.
        """
        # Parse notice if raw bytes
        if isinstance(notice, bytes):
            n_data = self.extract_notice_from_pdf(notice)
        elif isinstance(notice, NoticeData):
            n_data = notice
        else:
            n_data = NoticeData.from_dict(notice)

        # Parse folio if raw bytes
        if isinstance(folio, bytes):
            # Try PDF then fallback to CSV
            try:
                f_data = self.extract_folio_from_pdf(folio)
            except Exception:
                f_data = self.extract_folio_from_csv(folio)
        elif isinstance(folio, FolioData):
            f_data = folio
        else:
            f_data = FolioData.from_dict(folio)

        if not f_data.hotel_name:
            f_data.hotel_name = self.merchant_name

        # Reconcile
        recon = self.reconcile(n_data, f_data, supporting_docs=supporting_docs)
        self.audit_logger.log_event("api_reconcile_completed", {
            "case_id": n_data.case_id,
            "completeness_score": recon.get("completeness_score")
        }, user=reviewer_name)

        # Draft rebuttal
        rebuttal = self.draft_rebuttal(n_data, f_data, recon, custom_instructions=custom_instructions)
        self.audit_logger.log_event("api_rebuttal_drafted", {
            "case_id": n_data.case_id,
            "engine": self.llama_engine.last_engine_used
        }, user=reviewer_name)

        # Machine processing (Phase 1 P0): drafting is NOT human approval.
        # No approval event is recorded here and the packet is a draft
        # ("Pending approval") until a named human calls approve_dispute()
        # and its fingerprint is supplied for the final packet.
        from .fingerprint import case_fingerprint as _case_fp
        fp = _case_fp(n_data.to_dict(), f_data.to_dict(),
                      recon.get("evidence_items") and {i["doc_type"]: i for i in recon["evidence_items"]} or {},
                      rebuttal, policy_text or "", custom_instructions or "", self.merchant_name or "")
        self.audit_logger.log_event("api_rebuttal_processed", {
            "case_id": n_data.case_id,
            "fingerprint": fp["fingerprint"],
            "fingerprint_version": fp["version"],
            "rebuttal_sha256": AuditLogger.calculate_sha256(rebuttal.encode("utf-8")),
            "human_approval_required": True,
            "readiness_submittable": (recon.get("evidence_readiness") or {}).get("submittable"),
            "message": "Headless machine processing completed by SDK/API pipeline; human approval still required",
        }, user=reviewer_name)

        # Generate PDF if requested (draft — no approval fingerprint embedded)
        pdf_b64 = None
        sha_digest = None
        if generate_pdf:
            pdf_bytes = self.generate_pdf_packet_hashed(
                n_data, f_data, recon, rebuttal,
                approved_by=None,
                policy_text=policy_text,
                approval_fingerprint=None,
                chain_head=self.audit_logger.chain_head,
            )
            sha_digest = AuditLogger.calculate_sha256(pdf_bytes)
            pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
            self.audit_logger.log_event("api_packet_generated", {
                "case_id": n_data.case_id,
                "sha256": sha_digest,
                "approval_status": "draft_pending_human_approval",
            }, user=reviewer_name)

        return DisputePacketResponse(
            case_id=n_data.case_id,
            disputed_amount=recon.get("disputed_amount", 0.0),
            completeness_score=recon.get("completeness_score", 0),
            completeness_assessment=recon.get("completeness_assessment", ""),
            rebuttal_text=rebuttal,
            pdf_base64=pdf_b64,
            sha256_digest=sha_digest,
            discrepancies=recon.get("discrepancies", []),
            audit_highlights=recon.get("audit_highlights", []),
            collection_gaps=recon.get("collection_gaps", []),
            evidence_items=recon.get("evidence_items", []),
            approval=None,
            human_approval_required=True,
            approval_fingerprint=fp["fingerprint"],
        )

    def approve_dispute(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        supporting_docs: Optional[Dict[str, bool]] = None,
        rebuttal_text: str = "",
        *,
        approved_by: str,
        policy_text: Optional[str] = None,
        custom_instructions: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Records an explicit human approval for a drafted rebuttal.

        This is the ONLY SDK path that creates an approval. The caller (a
        human-operated system) supplies the approver's name; the approval is
        bound to the canonical case fingerprint computed from the exact
        notice/folio/evidence/draft being approved. Returns
        {approved_by, approved_at, fingerprint, fingerprint_version,
        event_hash, rebuttal_sha256} for packet generation.
        """
        approver = (approved_by or "").strip()
        if not approver:
            raise ValueError("approved_by (the human approver's name) is required")
        if not (rebuttal_text or "").strip():
            raise ValueError("rebuttal_text is required — approve the actual draft text")
        n_data = notice if isinstance(notice, NoticeData) else NoticeData.from_dict(notice)
        f_data = folio if isinstance(folio, FolioData) else FolioData.from_dict(folio)
        if not f_data.hotel_name:
            f_data.hotel_name = self.merchant_name
        recon = self.reconcile(n_data, f_data, supporting_docs=supporting_docs)
        from .fingerprint import case_fingerprint as _case_fp
        fp = _case_fp(n_data.to_dict(), f_data.to_dict(),
                      recon.get("evidence_items") and {i["doc_type"]: i for i in recon["evidence_items"]} or {},
                      rebuttal_text, policy_text or "", custom_instructions or "", self.merchant_name or "")
        from datetime import datetime, timezone
        approved_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        event = self.audit_logger.log_event("rebuttal_approved", {
            "case_id": n_data.case_id,
            "fingerprint": fp["fingerprint"],
            "fingerprint_version": fp["version"],
            "rebuttal_sha256": AuditLogger.calculate_sha256(rebuttal_text.encode("utf-8")),
            "via": "sdk_explicit",
            "gate_override": False,
            "message": f"Rebuttal approved by {approver} via SDK (explicit human approval)",
        }, user=approver)
        return {
            "approved_by": approver,
            "approved_at": approved_at,
            "fingerprint": fp["fingerprint"],
            "fingerprint_version": fp["version"],
            "event_hash": event["event_hash"],
            "rebuttal_sha256": AuditLogger.calculate_sha256(rebuttal_text.encode("utf-8")),
        }

    def verify_approval(self, notice, folio, supporting_docs, rebuttal_text: str,
                        approval: Optional[Dict[str, Any]], policy_text: Optional[str] = None,
                        custom_instructions: Optional[str] = None) -> bool:
        """True when `approval` exists and its fingerprint matches the current case+draft."""
        if not approval or not approval.get("fingerprint"):
            return False
        n_data = notice if isinstance(notice, NoticeData) else NoticeData.from_dict(notice)
        f_data = folio if isinstance(folio, FolioData) else FolioData.from_dict(folio)
        if not f_data.hotel_name:
            f_data.hotel_name = self.merchant_name
        recon = self.reconcile(n_data, f_data, supporting_docs=supporting_docs)
        from .fingerprint import case_fingerprint as _case_fp
        fp = _case_fp(n_data.to_dict(), f_data.to_dict(),
                      recon.get("evidence_items") and {i["doc_type"]: i for i in recon["evidence_items"]} or {},
                      rebuttal_text, policy_text or "", custom_instructions or "", self.merchant_name or "")
        return fp["fingerprint"] == approval.get("fingerprint")

    # ------------------------------------------------------------------ Phase 6

    def build_submission_bundle(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        reconciliation: Dict[str, Any],
        packet_bytes: bytes,
        exhibit_files: Dict[str, bytes],
        portal_id: str = "generic",
    ):
        """Builds the submission ZIP (packet + exhibits + manifest + instructions)."""
        from .submission import build_submission_bundle as _build
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        manifest = self.audit_logger.build_case_manifest(n_dict.get("case_id"))
        zip_bytes, info = _build(n_dict, f_dict, reconciliation, packet_bytes, exhibit_files, manifest, portal_id=portal_id)
        self.audit_logger.log_event("api_submission_bundle_built", {
            "case_id": n_dict.get("case_id"), "portal": portal_id,
            "bundle_sha256": info["bundle_sha256"], "size_bytes": info["size_bytes"],
        }, user="SDK/API")
        return zip_bytes, info

    def register_submission(self, record: Union["SubmissionRecord", Dict[str, Any]]):
        """Registers a staff-confirmed portal submission (duplicate-guarded by validate_bundle)."""
        from .models import SubmissionRecord
        from .submission import SubmissionRegistry
        rec = record if isinstance(record, SubmissionRecord) else SubmissionRecord.from_dict(record)
        saved = SubmissionRegistry().register_submission(rec)
        self.audit_logger.log_event("api_submission_registered", {
            "case_id": rec.case_id, "portal": rec.portal_id,
            "confirmation_reference": rec.confirmation_reference,
            "bundle_sha256": rec.bundle_sha256,
            "expected_decision_by": saved.expected_decision_by,
        }, user=rec.submitted_by or "SDK/API")
        return saved

    def record_outcome(self, record: Union["OutcomeRecord", Dict[str, Any]]):
        """Records the issuer decision / escalation for a case."""
        from .models import OutcomeRecord
        from .submission import SubmissionRegistry
        rec = record if isinstance(record, OutcomeRecord) else OutcomeRecord.from_dict(record)
        saved = SubmissionRegistry().record_outcome(rec)
        self.audit_logger.log_event("api_issuer_outcome_recorded", {
            "case_id": rec.case_id, "decision": rec.decision,
            "amount_recovered": rec.amount_recovered, "next_stage": rec.next_stage,
        }, user="SDK/API")
        return saved

    # ------------------------------------------------------------- Phases 7–9

    def escalation_status(self, case_id: str) -> Dict[str, Any]:
        """Current escalation stage, deadlines, rounds, losses, arbitration."""
        from .escalation import EscalationRegistry
        return EscalationRegistry().status(case_id)

    def record_loss(self, case_id: str, loss_reason: str, issuer_text: str = "", actor: str = "SDK/API"):
        """Records why the issuer ruled against the merchant + gap analysis."""
        from .escalation import EscalationRegistry, gap_analysis
        registry = EscalationRegistry()
        record = registry.record_loss(case_id, loss_reason, issuer_text, actor=actor)
        data = registry.load(case_id)
        gaps = gap_analysis(data["rounds"][-1]) if data["rounds"] else []
        self.audit_logger.log_event("api_loss_recorded", {
            "case_id": case_id, "loss_reason": loss_reason, "gaps": len(gaps),
        }, user=actor)
        return {"loss": record, "gap_checklist": gaps}

    def arbitration_assessment(self, network: Optional[str], disputed_amount: float,
                               readiness_score: Optional[int]) -> Dict[str, Any]:
        """Fee/EV decision support for arbitration (heuristic, labelled)."""
        from .escalation import arbitration_assessment as _assess
        return _assess(network, disputed_amount, readiness_score)

    def draft_supplemental_rebuttal(self, notice, folio, reconciliation, prior_round,
                                    loss: Optional[Dict[str, Any]] = None,
                                    custom_instructions: Optional[str] = None) -> str:
        """Drafts the pre-arb supplemental rebuttal referencing the prior round."""
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        return self.llama_engine.draft_supplemental_rebuttal(
            n_dict, f_dict, reconciliation, prior_round, loss=loss,
            custom_instructions=custom_instructions)

    # -------------------------------------------------------------- Phase 10

    def compute_damages(self, notice, folio, outcomes=None, arbitration=None, chargeback_fee: float = 0.0):
        """Statement of loss for civil/criminal filings."""
        from .legal import compute_damages as _damages
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        return _damages(n_dict, f_dict, outcomes=outcomes, arbitration=arbitration, chargeback_fee=chargeback_fee)

    def generate_affidavit(self, notice, folio, manifest: Dict[str, Any], affiant: Optional[Dict[str, str]] = None) -> bytes:
        """Business Records Affidavit TEMPLATE (sign + notarize offline)."""
        from .legal import generate_business_records_affidavit
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        return generate_business_records_affidavit(n_dict, f_dict, manifest, affiant=affiant)

    def build_court_bundle(self, notice, folio, packet_bytes: bytes, exhibit_files: Dict[str, bytes],
                           legal_docs: Dict[str, bytes], manifest: Dict[str, Any], damages: Dict[str, Any],
                           fraud_report: Optional[Dict[str, Any]] = None):
        """Court exhibit ZIP (packet + legal templates + exhibits + damages)."""
        from .legal import build_court_bundle as _build
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        zip_bytes, info = _build(n_dict, f_dict, packet_bytes, exhibit_files, legal_docs, manifest, damages,
                                 fraud_report=fraud_report)
        self.audit_logger.log_event("api_court_bundle_built", {
            "case_id": n_dict.get("case_id"), "bundle_sha256": info["bundle_sha256"],
            "contents": info["contents"],
        }, user="SDK/API")
        return zip_bytes, info


class FolioShieldHTTPClient:
    """
    Authenticated HTTP client for the enterprise integration API.

    This class is additive: the local FolioShield SDK above remains unchanged.
    It sends Bearer credentials, tenant-scoped case requests, idempotency keys,
    and bounded retries for transient failures. It never logs secrets or payloads.
    """

    def __init__(self, base_url: str, api_key: str, timeout: int = 30, max_retries: int = 3,
                 session: Optional[requests.Session] = None):
        if not base_url:
            raise ValueError("base_url is required")
        if not api_key:
            raise ValueError("api_key is required")
        self.base_url = base_url.rstrip("/")
        self._api_key = api_key
        self.timeout = timeout
        self.max_retries = max(1, max_retries)
        self.session = session or requests.Session()

    def _headers(self, idempotency_key: Optional[str] = None) -> Dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "X-Request-Id": str(uuid.uuid4()),
        }
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return headers

    def _request(self, method: str, path: str, payload: Optional[Dict[str, Any]] = None,
                 idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                response = self.session.request(
                    method, url, json=payload, headers=self._headers(idempotency_key), timeout=self.timeout)
                if response.status_code in (429, 502, 503, 504) and attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                try:
                    data = response.json()
                except ValueError:
                    data = {"status": "error", "error": {"message": "Non-JSON response"}}
                if response.status_code >= 400:
                    message = ((data.get("error") or {}).get("message") if isinstance(data, dict) else None) or f"HTTP {response.status_code}"
                    raise RuntimeError(message)
                return data
            except (requests.RequestException, RuntimeError) as exc:
                last_error = exc
                if attempt < self.max_retries - 1:
                    time.sleep(min(2 ** attempt, 8))
                    continue
                raise
        raise RuntimeError(str(last_error) if last_error else "Request failed")

    def create_case(self, case_id: Optional[str] = None, external_system: Optional[str] = None,
                    external_case_id: Optional[str] = None, external_folio_id: Optional[str] = None,
                    external_transaction_id: Optional[str] = None, property_id: Optional[str] = None,
                    notice: Optional[Dict[str, Any]] = None, folio: Optional[Dict[str, Any]] = None,
                    idempotency_key: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", "/api/v1/integrations/cases", {
            "case_id": case_id, "external_system": external_system, "external_case_id": external_case_id,
            "external_folio_id": external_folio_id, "external_transaction_id": external_transaction_id,
            "property_id": property_id, "notice": notice, "folio": folio,
        }, idempotency_key=idempotency_key)

    def upload_document(self, case_id: str, document_type: str, filename: str, media_type: str,
                        data: bytes, evidence_doc_type: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/integrations/cases/{case_id}/documents", {
            "document_type": document_type, "filename": filename, "media_type": media_type,
            "content_base64": base64.b64encode(data).decode("utf-8"), "evidence_doc_type": evidence_doc_type,
        })

    def get_case(self, case_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/integrations/cases/{case_id}")

    def reconcile_case(self, case_id: str) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/integrations/cases/{case_id}/reconcile", {})

    def draft_case(self, case_id: str, custom_notes: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/integrations/cases/{case_id}/draft", {"custom_notes": custom_notes})

    def process_case(self, case_id: str, custom_notes: Optional[str] = None, policy_text: Optional[str] = None) -> Dict[str, Any]:
        return self._request("POST", f"/api/v1/integrations/cases/{case_id}/process", {
            "custom_notes": custom_notes, "policy_text": policy_text,
        })

    def get_audit(self, case_id: str) -> Dict[str, Any]:
        return self._request("GET", f"/api/v1/integrations/cases/{case_id}/audit")

    def monitoring(self) -> Dict[str, Any]:
        return self._request("GET", "/api/v1/integrations/monitoring")

    @staticmethod
    def verify_webhook_signature(secret: str, payload: bytes, timestamp: str, signature: str) -> bool:
        from .integrations.webhooks import verify_signature

        return verify_signature(secret, payload, timestamp, signature)
