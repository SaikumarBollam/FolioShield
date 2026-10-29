"""
FolioShield Core Engine Package.
Exposes both low-level modules and high-level SDK interface for PMS/BMS integration.
"""

from .extractor import DocumentExtractor
from .reconciler import Reconciler
from .llm_engine import LlamaEngine
from .pdf_generator import EvidencePacketGenerator
from .security import mask_card_number, mask_pii, sanitize_untrusted_text
from .audit_logger import AuditLogger
from .rules import lookup_reason_code, get_evidence_checklist_for_dispute
from .config import config, get_settings, Settings
from .models import NoticeData, FolioData, FolioLineItem, DisputePacketResponse
from .client import FolioShield
from .api import FolioShieldAPIHandler, run_api_server

__all__ = [
    # High-level SDK client for BMS / PMS integrations
    "FolioShield",
    "NoticeData",
    "FolioData",
    "FolioLineItem",
    "DisputePacketResponse",
    "run_api_server",
    "FolioShieldAPIHandler",

    # Core sub-systems
    "DocumentExtractor",
    "Reconciler",
    "LlamaEngine",
    "EvidencePacketGenerator",
    "mask_card_number",
    "mask_pii",
    "sanitize_untrusted_text",
    "AuditLogger",
    "lookup_reason_code",
    "get_evidence_checklist_for_dispute",
    "config",
    "get_settings",
    "Settings",
]
