"""
Application service for dispute management, document extraction, reconciliation,
rebuttal drafting, human approval custody, packet generation, and submission.

This service acts as the central application boundary for Streamlit UI,
REST API, and headless background/integration runners.
"""

from typing import Any, Dict, List, Optional, Union

from core.audit_logger import AuditLogger
from core.case_store import CaseStore
from core.config import Settings, config
from core.escalation import EscalationRegistry
from core.exhibit_store import ExhibitStore
from core.extractor import DocumentExtractor
from core.fingerprint import case_fingerprint
from core.legal import LegalRegistry
from core.llm_engine import LlamaEngine
from core.models import FolioData, NoticeData, OutcomeRecord, SubmissionRecord
from core.pdf_generator import EvidencePacketGenerator
from core.reconciler import Reconciler
from core.security import validate_upload
from core.submission import SubmissionRegistry


class DisputeService:
    """Central application service orchestrating FolioShield dispute operations."""

    def __init__(
        self,
        settings: Optional[Settings] = None,
        case_store: Optional[CaseStore] = None,
        exhibit_store: Optional[ExhibitStore] = None,
        audit_logger: Optional[AuditLogger] = None,
        llama_engine: Optional[LlamaEngine] = None,
        submission_registry: Optional[SubmissionRegistry] = None,
        escalation_registry: Optional[EscalationRegistry] = None,
        legal_registry: Optional[LegalRegistry] = None,
    ) -> None:
        self.settings = settings or config
        self.case_store = case_store or CaseStore()
        self.exhibit_store = exhibit_store or ExhibitStore(root=self.settings.exhibit_store_dir)
        self.audit_logger = audit_logger or AuditLogger(log_dir=self.settings.log_dir)
        self.llama_engine = llama_engine or LlamaEngine(
            provider=self.settings.llama_provider,
            api_key=self.settings.get_api_key_for_provider(self.settings.llama_provider),
        )
        self.submission_registry = submission_registry or SubmissionRegistry()
        self.escalation_registry = escalation_registry or EscalationRegistry()
        self.legal_registry = legal_registry or LegalRegistry()

    def close(self) -> None:
        """Closes underlying store connections."""
        if hasattr(self.case_store, "close"):
            self.case_store.close()

    # --- Case Lifecycle ---

    def save_case(
        self,
        case_id: str,
        notice: Optional[Dict[str, Any]] = None,
        folio: Optional[Dict[str, Any]] = None,
        state: Optional[Dict[str, Any]] = None,
        evidence_items: Optional[Dict[str, Dict[str, Any]]] = None,
        draft_text: Optional[str] = None,
        policy_text: Optional[str] = None,
        custom_notes: Optional[str] = None,
        approval: Optional[Dict[str, Any]] = None,
        fingerprint: Optional[str] = None,
        audit_session_id: Optional[str] = None,
        audit_head_hash: Optional[str] = None,
        audit_event_count: Optional[int] = None,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None,
        expected_updated_at: Optional[str] = None,
        actor: str = "system",
    ) -> Dict[str, Any]:
        """Saves case state with tenant isolation and audit logging."""
        effective_notice = notice or (state.get("notice") if state else {}) or {}
        effective_folio = folio or (state.get("folio") if state else {}) or {}
        effective_evidence = evidence_items or (state.get("evidence_items") if state else None)
        effective_draft = draft_text or (state.get("draft_text") if state else None)
        effective_policy = policy_text or (state.get("policy_text") if state else None)
        effective_notes = custom_notes or (state.get("custom_notes") if state else None)
        effective_approval = approval or (state.get("approval") if state else None)
        effective_fp = fingerprint or (state.get("fingerprint") if state else None)

        res = self.case_store.save_case(
            case_id=case_id,
            notice=effective_notice,
            folio=effective_folio,
            evidence_items=effective_evidence,
            draft_text=effective_draft,
            policy_text=effective_policy,
            custom_notes=effective_notes,
            approval=effective_approval,
            fingerprint=effective_fp,
            audit_session_id=audit_session_id,
            audit_head_hash=audit_head_hash,
            audit_event_count=audit_event_count,
            tenant_id=tenant_id,
            status=status,
            expected_updated_at=expected_updated_at,
        )
        self.audit_logger.log_event(
            "case_saved",
            {"case_id": case_id, "tenant_id": tenant_id},
            user=actor,
        )
        return res

    def load_case(
        self,
        case_id: str,
        tenant_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Loads case state with tenant verification."""
        return self.case_store.load_case(case_id, tenant_id=tenant_id)

    def list_cases(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists cases scoped by tenant."""
        return self.case_store.list_cases(tenant_id=tenant_id)

    def delete_case(
        self,
        case_id: str,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> bool:
        """Deletes a case with tenant authorization."""
        deleted = self.case_store.delete_case(case_id, tenant_id=tenant_id)
        if deleted:
            self.audit_logger.log_event(
                "case_deleted",
                {"case_id": case_id, "tenant_id": tenant_id},
                user=actor,
            )
        return deleted

    # --- Document Processing & Extraction ---

    def extract_notice(
        self,
        pdf_bytes: bytes,
        ocr_fallback: bool = False,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> NoticeData:
        """Extracts structured notice data from PDF bytes with optional OCR."""
        if ocr_fallback:
            raw_text = DocumentExtractor.extract_text_with_ocr_fallback(
                pdf_bytes,
                ocr_text_provider=self.llama_engine.extract_text_from_image,
            )
        else:
            raw_text = DocumentExtractor.extract_text_from_pdf(pdf_bytes)

        parsed = DocumentExtractor.parse_dispute_notice(raw_text)
        notice = NoticeData.from_dict(parsed)
        if tenant_id and not notice.tenant_id:
            notice.tenant_id = tenant_id

        self.audit_logger.log_event(
            "notice_extracted",
            {
                "case_id": notice.case_id,
                "amount": notice.disputed_amount,
                "reason_code": notice.reason_code,
                "ocr_fallback": ocr_fallback,
            },
            user=actor,
        )
        return notice

    def extract_folio(
        self,
        data: bytes,
        format_hint: str = "pdf",
        merchant_name: Optional[str] = None,
        actor: str = "system",
    ) -> FolioData:
        """Extracts structured folio data from PDF or CSV bytes."""
        hotel = merchant_name or self.settings.merchant_name
        if format_hint.lower() == "csv":
            parsed = DocumentExtractor.parse_folio_csv(data)
        else:
            try:
                raw_text = DocumentExtractor.extract_text_from_pdf(data)
                parsed = DocumentExtractor.parse_folio_pdf(raw_text)
            except Exception:
                parsed = DocumentExtractor.parse_folio_csv(data)

        if not parsed.get("hotel_name"):
            parsed["hotel_name"] = hotel

        folio = FolioData.from_dict(parsed)
        self.audit_logger.log_event(
            "folio_extracted",
            {
                "guest_name": folio.guest_name,
                "folio_number": folio.folio_number,
                "total_charges": folio.total_charges,
            },
            user=actor,
        )
        return folio

    # --- Evidence File Upload & Retention ---

    def upload_evidence(
        self,
        filename: str,
        data: bytes,
        doc_type: str,
        case_id: Optional[str] = None,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> Dict[str, Any]:
        """Validates and stores binary evidence with content-addressed retention."""
        validate_upload(data, filename)

        stored = self.exhibit_store.put(data, filename, tenant_id=tenant_id)
        self.audit_logger.log_event(
            "evidence_file_collected",
            {
                "case_id": case_id,
                "doc_type": doc_type,
                "filename": filename,
                "size_bytes": len(data),
                "sha256": stored["sha256"],
                "tenant_id": tenant_id,
            },
            user=actor,
        )
        return stored

    # --- Reconciliation ---

    def reconcile_dispute(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        supporting_docs: Optional[Dict[str, bool]] = None,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> Dict[str, Any]:
        """Cross-checks dispute against folio and checklist."""
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio

        recon = Reconciler.reconcile(n_dict, f_dict, supporting_docs=supporting_docs)
        self.audit_logger.log_event(
            "reconcile_completed",
            {
                "case_id": n_dict.get("case_id"),
                "tenant_id": tenant_id,
                "completeness_score": recon.get("completeness_score"),
                "status": recon.get("status"),
            },
            user=actor,
        )
        return recon

    # --- Rebuttal Drafting & Human Approval ---

    def draft_rebuttal(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        reconciliation: Dict[str, Any],
        custom_instructions: Optional[str] = None,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> str:
        """Drafts formal dispute rebuttal."""
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio

        rebuttal = self.llama_engine.draft_rebuttal(
            n_dict,
            f_dict,
            reconciliation,
            custom_instructions=custom_instructions,
        )
        self.audit_logger.log_event(
            "rebuttal_drafted",
            {
                "case_id": n_dict.get("case_id"),
                "tenant_id": tenant_id,
                "engine": self.llama_engine.last_engine_used,
            },
            user=actor,
        )
        return rebuttal

    def approve_rebuttal(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        rebuttal_text: str,
        approved_by: str,
        reviewer_role: str = "Hotel Management",
        policy_text: Optional[str] = None,
        custom_instructions: Optional[str] = None,
        supporting_docs: Optional[Dict[str, bool]] = None,
        tenant_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Enforces human approval: records approval event with cryptographic fingerprint.
        Machine processing cannot be substituted for human approval.
        """
        if not approved_by or not approved_by.strip():
            raise ValueError("Human approval requires a non-empty approved_by reviewer identity.")

        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        hotel = f_dict.get("hotel_name") or self.settings.merchant_name

        fp = case_fingerprint(
            n_dict,
            f_dict,
            supporting_docs or {},
            rebuttal_text,
            policy_text or "",
            custom_instructions or "",
            hotel or "",
        )

        approval_record = {
            "approved_by": approved_by.strip(),
            "reviewer_role": reviewer_role,
            "fingerprint": fp["fingerprint"],
            "fingerprint_version": fp["version"],
            "rebuttal_sha256": AuditLogger.calculate_sha256(rebuttal_text.encode("utf-8")),
            "tenant_id": tenant_id,
        }

        self.audit_logger.log_event(
            "rebuttal_approved",
            {
                "case_id": n_dict.get("case_id"),
                "approval": approval_record,
            },
            user=approved_by.strip(),
        )
        return approval_record

    # --- Evidence Packet Generation ---

    def generate_packet(
        self,
        notice: Union[NoticeData, Dict[str, Any]],
        folio: Union[FolioData, Dict[str, Any]],
        reconciliation: Dict[str, Any],
        rebuttal_text: str,
        approved_by: Optional[str] = None,
        approved_at: Optional[str] = None,
        policy_text: Optional[str] = None,
        approval_fingerprint: Optional[str] = None,
        packet_format: str = "executive",
        exhibit_files: Optional[Dict[str, bytes]] = None,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> bytes:
        """Compiles self-verifying evidence packet PDF."""
        n_dict = notice.to_dict() if isinstance(notice, NoticeData) else notice
        f_dict = folio.to_dict() if isinstance(folio, FolioData) else folio
        if not f_dict.get("hotel_name"):
            f_dict["hotel_name"] = self.settings.merchant_name

        first_pass = EvidencePacketGenerator.generate_packet(
            n_dict,
            f_dict,
            reconciliation,
            rebuttal_text,
            approved_by=approved_by,
            approved_at=approved_at,
            policy_text=policy_text,
            approval_fingerprint=approval_fingerprint,
            chain_head=self.audit_logger.chain_head,
            packet_format=packet_format,
            exhibit_files=exhibit_files,
        )
        packet_hash = AuditLogger.calculate_sha256(first_pass)

        final_packet = EvidencePacketGenerator.generate_packet(
            n_dict,
            f_dict,
            reconciliation,
            rebuttal_text,
            approved_by=approved_by,
            approved_at=approved_at,
            policy_text=policy_text,
            approval_fingerprint=approval_fingerprint,
            chain_head=self.audit_logger.chain_head,
            packet_sha256=packet_hash,
            packet_format=packet_format,
            exhibit_files=exhibit_files,
        )

        self.audit_logger.log_event(
            "packet_generated",
            {
                "case_id": n_dict.get("case_id"),
                "packet_sha256": packet_hash,
                "format": packet_format,
                "approved": bool(approved_by and approval_fingerprint),
                "tenant_id": tenant_id,
            },
            user=actor,
        )
        return final_packet

    # --- Submissions & Outcomes ---

    def record_submission(
        self,
        record: SubmissionRecord,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> SubmissionRecord:
        """Records an outgoing bank/portal submission."""
        if tenant_id:
            record.tenant_id = tenant_id
        res = self.submission_registry.register_submission(record)
        self.audit_logger.log_event(
            "submission_recorded",
            {
                "case_id": record.case_id,
                "portal_id": record.portal_id,
                "status": record.status,
                "tenant_id": record.tenant_id,
            },
            user=actor,
        )
        return res

    def record_outcome(
        self,
        record: OutcomeRecord,
        tenant_id: Optional[str] = None,
        actor: str = "system",
    ) -> OutcomeRecord:
        """Records a dispute outcome (Won / Lost / Split / Timed out)."""
        if tenant_id:
            record.tenant_id = tenant_id
        res = self.submission_registry.record_outcome(record)
        self.audit_logger.log_event(
            "outcome_recorded",
            {
                "case_id": record.case_id,
                "decision": record.decision,
                "amount_recovered": record.amount_recovered,
                "tenant_id": record.tenant_id,
            },
            user=actor,
        )
        return res
