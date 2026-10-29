"""
FolioShield SDK / Library Integration Interface.
Enables programmatic, headless integration directly inside backend hotel services,
Property Management Systems (OPERA, Cloudbeds, Mews), and Building/Hotel Management Systems.
"""

import base64
from typing import Dict, Any, Optional, Union
from .models import NoticeData, FolioData, DisputePacketResponse
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

    def extract_notice_from_pdf(self, pdf_bytes: bytes) -> NoticeData:
        """Extracts structured notice data from raw PDF bytes."""
        raw_text = DocumentExtractor.extract_text_from_pdf(pdf_bytes)
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

        # Generate PDF if requested
        pdf_b64 = None
        sha_digest = None
        if generate_pdf:
            pdf_bytes = self.generate_pdf_packet(
                n_data, f_data, recon, rebuttal,
                approved_by=reviewer_name,
                policy_text=policy_text
            )
            sha_digest = AuditLogger.calculate_sha256(pdf_bytes)
            pdf_b64 = base64.b64encode(pdf_bytes).decode("utf-8")
            self.audit_logger.log_event("api_packet_generated", {
                "case_id": n_data.case_id,
                "sha256": sha_digest
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
            audit_highlights=recon.get("audit_highlights", [])
        )
