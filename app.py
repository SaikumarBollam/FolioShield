"""
FolioShield: Hotel Chargeback Defense & Evidence Management

Workflow: Upload → Extract → (Vision/OCR) → Review fields → Collect evidence files
          → Reconcile → Draft (Llama 3.3 70B / template) → Submission gate
          → Human approval → 3-page PDF packet.

Phase 1 (Collection): every bank-notice and PMS field is reviewable; supporting
evidence is collected as hashed files (EvidenceItem), not just checkboxes; the
cardholder's actual claim statement drives the rebuttal; approval is blocked
while critical collection gaps remain (explicit override is logged).
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.audit_logger import AuditLogger
from core.exhibit_store import ExhibitStore, ExhibitStoreError
from core.extractor import DocumentExtractor, ExtractionError
from core.llm_engine import OFFLINE_PROVIDER, PROVIDERS, LlamaEngine
from core.models import EvidenceItem
from core.pdf_generator import EvidencePacketGenerator
from core.reconciler import Reconciler
from core.rules import SUPPORTING_DOC_GROUPS, SUPPORTING_DOC_GUIDANCE, SUPPORTING_DOC_TYPES
from core.security import validate_upload
from core.zip_import import plan_zip_import
from core.case_store import CaseStore, CaseStoreError, CaseConflictError
from core.config import config
from data.sample_scenarios import SCENARIOS

load_dotenv()
logging.basicConfig(level=config.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DEFAULT_MERCHANT = config.merchant_name
CARD_NETWORKS = ["Visa", "Mastercard", "American Express", "Discover"]
PROVIDER_OPTIONS = {
    "Local Processing (No External AI)": OFFLINE_PROVIDER,
    "Groq": "groq",
    "Together AI": "together",
    "OpenRouter": "openrouter",
}
SCENARIO_OPTIONS = {
    "visa_fraud_10_4": "Visa 10.4 — Unauthorized Transaction Claim",
    "mc_cancellation_4853": "Mastercard 4853 — Cancellation Dispute",
    "amex_partial_c08": "American Express C08 — Partial Charge Dispute",
    "ota_virtual_card_10_4": "Visa 10.4 — OTA Virtual Card",
    "visa_refund_issued_13_6": "Visa 13.6 — Refund Already Issued",
    "mc_damage_4859": "Mastercard 4859 — Post-Checkout Charge",
    "custom": "📂 New Dispute Case",
}
DEFAULT_SCENARIO = "visa_fraud_10_4" if config.enable_test_scenarios else "custom"
VISION_DOC_TYPES = [
    "Registration Card", "Government Photo ID", "POS Signed Slip",
    "Terminal Receipt", "Booking Confirmation", "Other Supporting Document",
]


def _infer_vision_doc_type(filename: str) -> str:
    """Best-effort document-type guess from a filename; staff can override per file."""
    name = (filename or "").lower()
    if "registration" in name:
        return "Registration Card"
    if "passport" in name or "photo_id" in name or "_id" in name or name.startswith("id"):
        return "Government Photo ID"
    if "pos" in name or "slip" in name:
        return "POS Signed Slip"
    if "emv" in name or "terminal" in name or "receipt" in name:
        return "Terminal Receipt"
    if "booking" in name or "confirmation" in name:
        return "Booking Confirmation"
    return "Other Supporting Document"
BOOKING_CHANNELS = ["", "direct_web", "direct_phone", "ota", "gds", "walk_in", "corporate"]
STAY_STATUSES = ["", "occupied", "no_show", "cancelled", "early_departure", "day_use"]
DISPUTE_STAGES = ["", "inquiry", "chargeback", "pre_arbitration", "second_chargeback", "arbitration"]


# -----------------------------------------------------------------------------
# PAGE SETUP & STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="FolioShield | Hotel Chargeback Defense",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    :root {
        --fs-primary: #1E3A8A;
        --fs-accent: #2563EB;
        --fs-bg: #FFFFFF;
        --fs-text: #0F172A;
        --fs-font: sans-serif;
        --fs-radius: 6px;
    }
    .main-header { font-size: 2.2rem; font-weight: 700; color: var(--fs-primary); margin-bottom: 0px; font-family: var(--fs-font); }
    .sub-header { font-size: 1.05rem; color: #475569; margin-bottom: 20px; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 10px 18px; border-radius: var(--fs-radius) var(--fs-radius) 0px 0px; font-weight: 600; }
    .badge { display: inline-block; padding: 3px 8px; font-size: 12px; font-weight: 600;
             border-radius: 4px; background-color: #DBEAFE; color: #1E40AF; }
    .fs-brand-logo { max-height: 44px; margin-bottom: 6px; }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# STATE HELPERS
# -----------------------------------------------------------------------------
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty_notice() -> Dict[str, Any]:
    return {k: None for k in ("case_id", "card_network", "reason_code", "reason_description", "transaction_date",
                              "dispute_date", "response_deadline", "cardholder_name", "card_last_4", "arn",
                              "claim_statement", "dispute_stage", "processor", "statement_descriptor",
                              "merchant_id", "prior_case_id")} | {
        "disputed_amount": 0.0, "original_amount": 0.0, "currency": "USD", "raw_text": ""}


def empty_folio() -> Dict[str, Any]:
    return {k: None for k in ("hotel_name", "hotel_address", "guest_name", "folio_number", "room_number",
                              "check_in", "check_out", "card_last_4", "auth_code", "merchant_id",
                              "confirmation_number", "booking_channel", "booking_source", "booking_date",
                              "stay_status", "check_in_time", "check_out_time", "rate_plan", "guest_email",
                              "guest_phone", "payer_name", "payer_relationship", "avs_result", "cvv_result",
                              "three_ds_status", "three_ds_eci", "entry_mode", "terminal_id", "auth_date",
                              "refund_date", "refund_reference", "cancellation_timestamp",
                              "cancellation_number")} | {
        "rate_per_night": 0.0, "total_charges": 0.0, "total_payments": 0.0, "balance": 0.0,
        "auth_amount": 0.0, "refund_amount": 0.0, "num_guests": None,
        "line_items": [], "raw_text": ""}


def actor() -> str:
    return (st.session_state.get("reviewer_name") or "").strip() or "Staff Reviewer"


def log(action: str, details: Dict[str, Any]) -> None:
    st.session_state.audit_logger.log_event(action, details, user=actor())


def reset_outputs() -> None:
    """Invalidates anything derived from the case data (draft, approval, packet, vision findings)."""
    st.session_state.rebuttal_editor = ""
    st.session_state.draft_engine = None
    st.session_state.approval = None
    st.session_state.generated_pdf = None
    st.session_state.pdf_fingerprint = None


def normalize_docs_input(docs: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Reference/API-shaped supporting docs -> EvidenceItem dicts keyed by registry key."""
    out: Dict[str, Dict[str, Any]] = {}
    for key in SUPPORTING_DOC_TYPES:
        value = (docs or {}).get(key)
        if isinstance(value, dict):
            out[key] = EvidenceItem.from_dict({**value, "doc_type": key}).to_dict()
        else:
            out[key] = EvidenceItem(doc_type=key, present=bool(value)).to_dict()
    return out


def set_evidence_items(items: Dict[str, Dict[str, Any]]) -> None:
    st.session_state.evidence_items = items
    for key in SUPPORTING_DOC_TYPES:
        st.session_state[f"doc_{key}"] = bool(items.get(key, {}).get("present"))


def _set_evidence_present(key: str, present: bool) -> None:
    """Set an evidence checkbox value from a callback or pre-widget code path."""
    st.session_state[f"doc_{key}"] = bool(present)


def _exhibit_store() -> ExhibitStore:
    """Session exhibit store backed by the persistent content-addressed root.

    Bytes survive session/server restarts (keyed by SHA-256 under
    config.exhibit_store_dir). If the directory cannot be created, the app
    falls back to in-memory storage ONLY outside production and flags it
    via st.session_state.exhibit_store_degraded so the UI warns staff that
    exhibits will not survive a restart. In production the error is raised.
    """
    store = st.session_state.get("exhibit_store")
    if store is None:
        try:
            store = ExhibitStore(root=config.exhibit_store_dir)
            st.session_state.exhibit_store_degraded = False
        except OSError as exc:
            if config.is_production:
                raise ExhibitStoreError(
                    f"Exhibit store directory '{config.exhibit_store_dir}' is unavailable: {exc}. "
                    "Fix FOLIOSHIELD_EXHIBIT_DIR permissions before collecting evidence."
                ) from exc
            store = ExhibitStore()
            st.session_state.exhibit_store_degraded = True
        st.session_state.exhibit_store = store
    return store


def _store_evidence_bytes(key: str, label: str, filename: str, data: bytes, via: str = "upload") -> str:
    """Stores evidence bytes into a slot (shared by single upload + ZIP import).

    Returns the SHA-256 digest. Raises ValueError on validation failure.
    Preserves probative details/provenance/vision check when replacing a
    file with identical bytes; clears them when the bytes change.
    """
    digest = AuditLogger.calculate_sha256(data)
    validate_upload(data, filename, max_bytes=config.max_upload_bytes)
    store = _exhibit_store()
    stored = store.put(data, filename)
    stored_docs = dict(st.session_state.get("evidence_items") or {})
    previous = stored_docs.get(key) or {}
    new_item = EvidenceItem(
        doc_type=key, present=True, filename=filename, sha256=digest,
        verified_by=actor(), verified_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        size_bytes=stored["size_bytes"], mime=stored["mime"], stored_ref=stored["stored_ref"],
    ).to_dict()
    if previous.get("sha256") == digest:
        for preserved in ("details", "vision_check", "original_type", "original_location",
                          "extracted_by", "extracted_at", "extraction_method", "system_name"):
            if previous.get(preserved):
                new_item[preserved] = previous[preserved]
    stored_docs[key] = new_item
    st.session_state.evidence_items = stored_docs
    st.session_state.processed_uploads[f"evidence_{key}"] = digest
    _set_evidence_present(key, True)
    _persist_case()
    log("evidence_file_collected", {"doc_type": key, "filename": filename, "sha256": digest,
                                    "size_bytes": stored["size_bytes"], "via": via,
                                    "message": f"{label} collected as evidence file"})
    return digest


def _collect_evidence_file(key: str, label: str) -> None:
    """File-uploader callback; runs before widgets are rebuilt on the next run."""
    ev_file = st.session_state.get(f"evfile_{key}")
    if ev_file is None:
        return
    ev_bytes = ev_file.getvalue()
    digest = AuditLogger.calculate_sha256(ev_bytes)
    if st.session_state.processed_uploads.get(f"evidence_{key}") == digest:
        return
    try:
        _store_evidence_bytes(key, label, ev_file.name, ev_bytes)
    except (ValueError, ExhibitStoreError) as e:
        st.session_state.processed_uploads.pop(f"evidence_{key}", None)
        st.session_state.evidence_upload_error = f"❌ {e}"
        return
    reset_outputs()


def _import_evidence_zip() -> None:
    """ZIP-uploader callback: routes each archived file to its evidence slot."""
    zip_file = st.session_state.get("evidence_zip_uploader")
    if zip_file is None:
        return
    zip_bytes = zip_file.getvalue()
    zip_digest = AuditLogger.calculate_sha256(zip_bytes)
    if st.session_state.processed_uploads.get("evidence_zip") == zip_digest:
        return
    st.session_state.processed_uploads["evidence_zip"] = zip_digest
    max_total = max(config.max_upload_bytes * 5, 10 * 1024 * 1024)
    if len(zip_bytes) > max_total:
        st.session_state.evidence_zip_report = {
            "error": f"'{zip_file.name}' is {len(zip_bytes) / 1_048_576:.1f} MB; the ZIP limit is {max_total // 1_048_576} MB. "
                     "Split the archive and retry."
        }
        return
    plan = plan_zip_import(zip_bytes, max_file_bytes=config.max_upload_bytes,
                           max_total_bytes=max_total)
    if not plan.get("ok"):
        st.session_state.evidence_zip_report = {"error": plan.get("error") or "Could not read that ZIP archive."}
        return
    imported, failed = [], []
    for doc_type, entry in (plan.get("matched") or {}).items():
        label = SUPPORTING_DOC_TYPES.get(doc_type, doc_type)
        try:
            digest = _store_evidence_bytes(doc_type, label, entry["filename"], entry["data"], via=f"zip:{entry.get('via')}")
            imported.append({"doc_type": doc_type, "label": label, "filename": entry["filename"],
                             "via": entry.get("via"), "sha256": digest})
        except (ValueError, ExhibitStoreError) as e:
            failed.append({"filename": entry["filename"], "reason": str(e)})
    st.session_state.evidence_zip_report = {
        "archive": zip_file.name, "imported": imported, "failed": failed,
        "unmatched": plan.get("unmatched") or [], "skipped": plan.get("skipped") or [],
    }
    log("evidence_zip_imported", {"archive": zip_file.name, "archive_sha256": zip_digest,
                                  "imported": [{"doc_type": i["doc_type"], "filename": i["filename"], "sha256": i["sha256"]} for i in imported],
                                  "unmatched": plan.get("unmatched") or [],
                                  "skipped": plan.get("skipped") or [],
                                  "message": f"ZIP import: {len(imported)} file(s) collected from {zip_file.name}"})
    if imported:
        reset_outputs()


def _remove_evidence_file(key: str, label: str) -> None:
    """Remove-button callback; runs before widgets are rebuilt on the next run."""
    stored = dict(st.session_state.get("evidence_items") or {})
    stored[key] = EvidenceItem(doc_type=key, present=False).to_dict()
    st.session_state.evidence_items = stored
    _set_evidence_present(key, False)
    st.session_state.processed_uploads.pop(f"evidence_{key}", None)
    reset_outputs()
    _persist_case()
    log("evidence_file_removed", {"doc_type": key, "message": f"{label} evidence file removed"})


# Evidence slots whose files are visual documents a vision model can review.
VISION_CHECKABLE_DOC_TYPES = {
    "signed_registration_card", "id_verification_log", "pos_signed_slips",
    "emv_terminal_receipt", "cancellation_policy_acceptance",
    "incident_damage_evidence", "cctv_footage", "suspect_id_copy",
    "witness_declaration", "demand_letter", "refund_credit_receipt",
    "guest_service_log", "guest_communication_log", "booking_confirmation",
}
_VISION_DOC_TYPE_LABELS = {
    "signed_registration_card": "Registration Card",
    "id_verification_log": "Government Photo ID",
    "suspect_id_copy": "Government Photo ID",
    "pos_signed_slips": "POS Signed Slip",
    "emv_terminal_receipt": "Terminal Receipt",
    "booking_confirmation": "Booking Confirmation",
}


def _run_vision_check(key: str, label: str) -> None:
    """Vision-Check button callback: analyzes the collected exhibit file.

    The finding is stored on the evidence item, bound to the exhibit's
    SHA-256. It is advisory only — it never changes presence or readiness.
    Runs as a callback so session state updates before widgets rebuild.
    """
    stored = dict(st.session_state.get("evidence_items") or {})
    item = dict(stored.get(key) or {})
    if not llama_engine.is_api_configured():
        st.session_state.vision_check_error = (
            "No vision provider is configured, so the document was not analyzed. In the sidebar under "
            "AI Processing, choose Groq, Together AI, or OpenRouter and enter an API key — or set "
            "LLAMA_PROVIDER and the provider's API key in .env — then run the check again."
        )
        return
    store = _exhibit_store()
    data = store.get(item.get("stored_ref") or item.get("sha256"), item.get("filename") or "")
    if not data:
        st.session_state.vision_check_error = "The collected file bytes are no longer available in this session. Re-attach the file, then run the check again."
        return
    filename = item.get("filename") or ""
    is_pdf = filename.lower().endswith(".pdf") or data.startswith(b"%PDF")
    analysis_bytes = data
    rendered_hash = None
    if is_pdf:
        try:
            analysis_bytes = DocumentExtractor.pdf_first_page_to_image(data)
            rendered_hash = AuditLogger.calculate_sha256(analysis_bytes)
        except ExtractionError as e:
            st.session_state.vision_check_error = str(e)
            return
    doc_type_label = _VISION_DOC_TYPE_LABELS.get(key) or _infer_vision_doc_type(filename)
    result = llama_engine.analyze_visual_evidence(analysis_bytes, document_type=doc_type_label)
    check = {
        **result,
        "sha256": item.get("sha256"),
        "filename": filename,
        "source_type": "pdf" if is_pdf else "image",
        "checked_by": actor(),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    if is_pdf:
        check["rendered_sha256"] = rendered_hash
        check["page_analyzed"] = 1
    item["vision_check"] = check
    stored[key] = item
    st.session_state.evidence_items = stored
    _persist_case()
    log("vision_check_completed", {"doc_type": key, **check,
                                   "message": f"Vision check completed for {label}"})


def load_case(notice: Dict[str, Any], folio: Dict[str, Any], docs: Dict[str, Any]) -> None:
    st.session_state.notice_data = {**empty_notice(), **json.loads(json.dumps(notice))}  # deep copy; never mutate reference-case data
    st.session_state.folio_data = {**empty_folio(), **json.loads(json.dumps(folio))}
    set_evidence_items(normalize_docs_input(docs))
    st.session_state.processed_uploads = {}
    st.session_state.vision_results = {}
    st.session_state.gate_override = False
    reset_outputs()


def init_state() -> None:
    if "audit_logger" in st.session_state:
        return
    st.session_state.audit_logger = AuditLogger()
    st.session_state.current_scenario_key = DEFAULT_SCENARIO
    st.session_state.custom_notes = ""
    st.session_state.policy_text = ""
    if DEFAULT_SCENARIO in SCENARIOS:
        s = SCENARIOS[DEFAULT_SCENARIO]
        load_case(s["notice"], s["folio"], s["supporting_docs"])
    else:  # "custom" — production mode starts from a blank case
        load_case(empty_notice(), empty_folio(), {})


def current_evidence_items() -> Dict[str, Dict[str, Any]]:
    """Evidence registry view: checkbox attestations merged with collected files.

    Each file-backed item is annotated with ``bytes_retained`` — whether the
    exhibit store can actually produce its bytes right now — so exhibits are
    only cited as "attached" when they can truly be bundled.
    """
    items: Dict[str, Dict[str, Any]] = {}
    stored = st.session_state.get("evidence_items") or {}
    store = _exhibit_store()
    for key in SUPPORTING_DOC_TYPES:
        item = dict(stored.get(key) or {"doc_type": key, "present": False, "details": {}})
        item["present"] = bool(st.session_state.get(f"doc_{key}", item.get("present")))
        if item.get("filename") and item.get("sha256"):
            item["bytes_retained"] = store.has(item.get("stored_ref") or item.get("sha256"), item.get("filename") or "")
        items[key] = item
    return items


# ---------------------------------------------------------------------------
# Durable case persistence (Phase 1 P0): cases survive restarts/sessions.
# ---------------------------------------------------------------------------

def _case_store() -> Optional[CaseStore]:
    """Session case store; None (with a degraded flag) when unavailable."""
    store = st.session_state.get("case_store")
    if store is None and not st.session_state.get("case_store_failed"):
        try:
            store = CaseStore(config.case_db_path)
            st.session_state.case_store = store
            st.session_state.case_store_degraded = False
        except CaseStoreError:
            st.session_state.case_store_failed = True
            st.session_state.case_store_degraded = True
    return store


def _persist_case() -> None:
    """Saves the current case (notice/folio/evidence/draft/approval) durably.

    Called from mutation callbacks and once per run when the case
    fingerprint changed. Conflicts are surfaced, never silently resolved.
    """
    store = _case_store()
    case_id = (st.session_state.get("notice_data") or {}).get("case_id")
    if store is None or not case_id:
        return
    try:
        head = st.session_state.audit_logger.chain_head
        saved = store.save_case(
            case_id,
            st.session_state.get("notice_data") or {},
            st.session_state.get("folio_data") or {},
            st.session_state.get("evidence_items") or {},
            draft_text=st.session_state.get("rebuttal_editor") or None,
            policy_text=st.session_state.get("policy_text") or None,
            custom_notes=st.session_state.get("custom_notes") or None,
            approval=st.session_state.get("approval"),
            fingerprint=(st.session_state.get("approval") or {}).get("fingerprint"),
            audit_session_id=head.get("session_id"),
            audit_head_hash=head.get("head_hash"),
            audit_event_count=head.get("event_count"),
            status=(st.session_state.get("notice_data") or {}).get("dispute_stage") or None,
            expected_updated_at=st.session_state.get("case_store_updated_at"),
        )
        st.session_state.case_store_updated_at = saved["updated_at"]
        st.session_state.pop("case_store_conflict", None)
    except CaseConflictError as exc:
        st.session_state.case_store_conflict = str(exc)
    except CaseStoreError as exc:
        st.session_state.case_store_degraded = True
        st.session_state.case_store_conflict = f"Case could not be saved durably: {exc}"


def _open_saved_case(case_id: str) -> bool:
    """Restores a saved case into session state. Returns False if missing."""
    store = _case_store()
    if store is None:
        return False
    record = store.load_case(case_id)
    if record is None:
        return False
    load_case(record["notice"] or {}, record["folio"] or {}, record["evidence_items"] or {})
    st.session_state.rebuttal_editor = record.get("draft_text") or ""
    st.session_state.policy_text = record.get("policy_text") or ""
    st.session_state.custom_notes = record.get("custom_notes") or ""
    st.session_state.approval = record.get("approval")
    st.session_state.case_store_updated_at = record.get("updated_at")
    st.session_state.pop("case_store_conflict", None)
    log("saved_case_opened", {"case_id": case_id,
                              "message": f"Reopened saved case {case_id} (saved {record.get('updated_at')})"})
    return True


def case_fingerprint(notice: Dict[str, Any], folio: Dict[str, Any], evidence: Dict[str, Any], draft: str, policy: str) -> str:
    """Legacy single-hash fingerprint (kept for compatibility)."""
    payload = json.dumps({"n": notice, "f": folio, "e": evidence, "r": draft, "p": policy}, sort_keys=True, default=str)
    return sha256_text(payload)


from core.fingerprint import case_fingerprint as canonical_fingerprint, changed_components


def current_fingerprint_bundle() -> Dict[str, Any]:
    """Canonical v2 fingerprint bundle (version + fingerprint + components)."""
    return canonical_fingerprint(
        notice_data, folio_data, evidence_items,
        st.session_state.get("rebuttal_editor", ""),
        st.session_state.get("policy_text", ""),
        st.session_state.get("custom_notes", ""),
        merchant_name,
    )


def current_packet_format() -> str:
    """Selected packet format; part of packet identity (not the approval fingerprint)."""
    return "complete" if st.session_state.get("packet_format") == "complete" else "executive"


def new_upload(slot: str, data: bytes) -> bool:
    """True only the first time a given file is seen in a slot (Streamlit reruns the script on every click)."""
    digest = AuditLogger.calculate_sha256(data)
    if st.session_state.processed_uploads.get(slot) == digest:
        return False
    st.session_state.processed_uploads[slot] = digest
    return True


init_state()


# -----------------------------------------------------------------------------
# SIDEBAR CONTROLS
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🛡️ **FolioShield**")
    st.caption("**Hotel Chargeback Defense & Evidence Management**")

    # Environment Badge
    if config.is_production:
        st.markdown("<span class='badge' style='background-color:#DCFCE7; color:#15803D;'>🟢 PRODUCTION</span>", unsafe_allow_html=True)
    elif config.is_testing:
        st.markdown("<span class='badge' style='background-color:#FEF3C7; color:#B45309;'>🧪 TESTING</span>", unsafe_allow_html=True)
    else:
        st.markdown("<span class='badge' style='background-color:#E0E7FF; color:#4338CA;'>🛠️ DEVELOPMENT</span>", unsafe_allow_html=True)
    st.markdown("---")

    if config.enable_test_scenarios:
        st.markdown("### 📚 **Reference Case Library**")
        selected_scenario = st.selectbox(
            "Open a reference case or start a new dispute:",
            options=list(SCENARIO_OPTIONS.keys()),
            format_func=SCENARIO_OPTIONS.get,
            index=list(SCENARIO_OPTIONS).index(st.session_state.current_scenario_key),
        )
        if selected_scenario != st.session_state.current_scenario_key:
            st.session_state.current_scenario_key = selected_scenario
            if selected_scenario == "custom":
                load_case(empty_notice(), empty_folio(), {})
                log("custom_case_started", {"message": "Started new dispute case"})
            else:
                s_data = SCENARIOS[selected_scenario]
                load_case(s_data["notice"], s_data["folio"], s_data["supporting_docs"])
                log("reference_case_loaded", {"scenario": selected_scenario, "message": f"Opened reference case: {s_data['title']}"})
            st.rerun()
    else:
        st.markdown("### 📂 **Document Intake**")
        st.caption("Upload dispute notices and guest folios in Tab 1.")

    st.markdown("---")
    st.markdown("### 👤 **Reviewer**")
    st.text_input("Reviewer name (recorded in audit log):", key="reviewer_name", placeholder="Full name and title")
    st.selectbox("Reviewer role:", ["Manager", "Front Office Manager", "General Manager", "Revenue Manager", "Night Auditor", "Finance"], key="reviewer_role")
    merchant_name = st.text_input("Merchant / property name:", value=DEFAULT_MERCHANT,
                                  help="Used when the uploaded folio does not state the property name.")

    st.markdown("---")
    st.markdown("### 🤖 **AI Processing**")
    env_provider = config.llama_provider
    provider_labels = list(PROVIDER_OPTIONS)
    default_label = next((lbl for lbl, code in PROVIDER_OPTIONS.items() if code == env_provider), provider_labels[0])
    provider_label = st.selectbox("Inference Provider:", options=provider_labels, index=provider_labels.index(default_label))
    provider_code = PROVIDER_OPTIONS[provider_label]

    api_key_input = ""
    if provider_code != OFFLINE_PROVIDER:
        env_var = PROVIDERS[provider_code].api_key_env
        configured_key = config.get_api_key_for_provider(provider_code)
        api_key_input = st.text_input(
            "Provider API Key:",
            value=configured_key or "",
            type="password",
            placeholder=f"Leave blank to use ${env_var}",
            help="Keys can be set in .env or passed here for this session.",
        )

    llama_engine = LlamaEngine(provider=provider_code, api_key=api_key_input or None)
    if llama_engine.is_api_configured():
        st.success(f"🟢 {provider_label} connected")
    elif provider_code == OFFLINE_PROVIDER:
        st.info("🟡 Local processing enabled — documents are processed on this system")
    else:
        st.warning("🟠 AI provider not configured — local processing will be used")

    st.markdown("---")
    st.markdown("### 💾 **Saved Cases**")
    _store_for_list = _case_store()
    if _store_for_list is None:
        st.warning("Case database unavailable — work is kept in this session only and will be lost on restart.")
    else:
        try:
            _saved_cases = _store_for_list.list_cases()
        except CaseStoreError:
            _saved_cases = []
            st.warning("Case database unavailable — work is kept in this session only and will be lost on restart.")
        _current_case_id = (st.session_state.get("notice_data") or {}).get("case_id")
        if _saved_cases:
            _saved_options = {c["case_id"]: f"{c['case_id']} · saved {str(c['updated_at'])[:16].replace('T', ' ')} UTC" for c in _saved_cases}
            _picked_case = st.selectbox("Reopen a saved case:", options=[""] + list(_saved_options.keys()),
                                        format_func=lambda cid: _saved_options.get(cid, "Select a saved case…"),
                                        key="saved_case_picker")
            if _picked_case and _picked_case != _current_case_id and st.button("📂 Open saved case", width="stretch"):
                if _open_saved_case(_picked_case):
                    st.rerun()
                else:
                    st.error("That saved case could not be loaded.")
        else:
            st.caption("No saved cases yet — cases save automatically as you work.")
        if _current_case_id:
            if st.session_state.get("case_store_conflict"):
                st.error(f"⚠️ Save conflict: {st.session_state.case_store_conflict}")
            elif st.session_state.get("case_store_updated_at"):
                st.caption(f"💾 Case `{_current_case_id}` saved {str(st.session_state.case_store_updated_at)[:16].replace('T', ' ')} UTC — it survives restarts.")

    st.markdown("---")
    st.markdown("### 🔐 **Compliance Safeguards**")
    st.checkbox("PCI-DSS Card Masking (PAN Redaction)", value=True, disabled=True,
                help="Always enforced: card numbers are masked at extraction time, before storage or display.")
    st.caption("Full card numbers are never stored; only the last 4 digits are retained.")


# -----------------------------------------------------------------------------
# DERIVED CASE STATE (computed before rendering so metrics are never one click behind)
# -----------------------------------------------------------------------------
evidence_items = current_evidence_items()
notice_data: Dict[str, Any] = st.session_state.notice_data
folio_data: Dict[str, Any] = {**st.session_state.folio_data,
                              "hotel_name": st.session_state.folio_data.get("hotel_name") or merchant_name}
reconciliation = Reconciler.reconcile(notice_data, folio_data, evidence_items)
collection_gaps: List[Dict[str, Any]] = reconciliation.get("collection_gaps") or []
critical_gaps = [g for g in collection_gaps if g.get("severity") == "critical"]

# Durable auto-save: persist whenever the case fingerprint changes (covers
# form corrections, draft edits, checkbox attestations — not just uploads).
try:
    _fp_now = current_fingerprint_bundle()["fingerprint"]
except Exception:
    _fp_now = None
if _fp_now and _fp_now != st.session_state.get("_last_persisted_fingerprint"):
    _persist_case()
    st.session_state._last_persisted_fingerprint = _fp_now


def current_fingerprint() -> str:
    return current_fingerprint_bundle()["fingerprint"]


def retained_exhibit_files() -> Dict[str, bytes]:
    """Exhibit letter -> retained bytes for exhibits whose files we still hold."""
    store = _exhibit_store()
    out: Dict[str, bytes] = {}
    items_by_type = {i.get("doc_type"): i for i in (reconciliation.get("evidence_items") or [])}
    for exhibit in (reconciliation.get("exhibits") or []):
        if not exhibit.get("file_backed"):
            continue
        item = items_by_type.get(exhibit.get("doc_type")) or {}
        data = store.get(item.get("stored_ref") or exhibit.get("sha256"), item.get("filename") or "")
        if data is not None:
            out[exhibit["letter"]] = data
    return out


# -----------------------------------------------------------------------------
# MAIN HEADER & METRICS
# -----------------------------------------------------------------------------
st.markdown("<h1 class='main-header'>🛡️ FolioShield: Autonomous Chargeback Defense</h1>", unsafe_allow_html=True)
st.markdown(
    "<p class='sub-header'>Outside-in document reconciliation, multimodal evidence auditing, "
    "and automated 3-page dispute packet generation powered by <b>Meta Llama 3.3 70B</b> &amp; <b>Llama Vision</b>.</p>",
    unsafe_allow_html=True,
)

network_code = f"{notice_data.get('card_network') or 'Unknown'} {notice_data.get('reason_code') or ''}".strip()
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("Disputed Amount", f"${reconciliation['disputed_amount']:,.2f}", delta=network_code, delta_color="off")
with m2:
    st.metric("Total Folio Charges", f"${reconciliation['folio_charges']:,.2f}",
              delta=f"Settled: ${reconciliation['folio_payments']:,.2f}", delta_color="off")
with m3:
    diff = reconciliation["folio_charges"] - reconciliation["disputed_amount"]
    if reconciliation["is_exact_match"]:
        diff_label = "Exact Match"
    elif reconciliation["is_partial"]:
        diff_label = "Partial Dispute"
    elif reconciliation["disputed_amount"] <= 0:
        diff_label = "Amount Missing"
    else:
        diff_label = "Over-Disputed"
    st.metric("Variance / Status", f"${abs(diff):,.2f}", delta=diff_label,
              delta_color="normal" if reconciliation["is_exact_match"] else "off")
with m4:
    st.metric("Evidence Completeness", f"{reconciliation['completeness_score']}%",
              delta=reconciliation["completeness_assessment"].split("(")[0].strip(),
              delta_color="normal" if reconciliation["status_color"] == "green" else "inverse")
with m5:
    days = reconciliation["days_to_deadline"]
    st.metric("Response Deadline", notice_data.get("response_deadline") or "Unknown",
              delta=("Overdue" if days < 0 else f"{days} day(s) left") if days is not None else "Not found",
              delta_color="inverse" if days is not None and days <= 5 else "off")

if collection_gaps:
    gap_preview = "; ".join(g["message"] for g in collection_gaps[:3])
    st.warning(f"📥 **Collection gaps ({len(collection_gaps)}):** {gap_preview}"
               + (" …resolve in Tab 1 / Tab 2 before approval." if len(collection_gaps) > 3 else ""))

st.markdown("<br/>", unsafe_allow_html=True)

# Embedded mode: only server-validated signed context is trusted. Raw query
# parameters such as tenant/role are never used for authorization by themselves.
# Theming follows the same rule: host theme values are accepted only from the
# signed context (or server-side env defaults); otherwise the FolioShield
# default theme applies unchanged.
embedded_context = None
active_theme = None
try:
    from embedded.configuration import EmbeddedConfiguration
    from embedded.context import validate_context_token
    from embedded.theme import HostTheme

    _embedded_cfg = EmbeddedConfiguration.from_env()
    active_theme = _embedded_cfg.resolve_theme()
    _embedded_token = st.query_params.get("fs_embed_token") if hasattr(st, "query_params") else None
    if isinstance(_embedded_token, list):
        _embedded_token = _embedded_token[0] if _embedded_token else None
    if _embedded_cfg.enabled and _embedded_token:
        embedded_context = validate_context_token(
            _embedded_token, _embedded_cfg.signing_secret, issuer=_embedded_cfg.issuer,
            audience=_embedded_cfg.audience, allowed_origins=_embedded_cfg.allowed_origins or None,
            origin=st.query_params.get("fs_embed_origin") if hasattr(st, "query_params") else None)
        active_theme = _embedded_cfg.resolve_theme(embedded_context.theme)
        st.info(
            f"🔗 Embedded session validated for tenant `{embedded_context.tenant_id}` · "
            f"user `{embedded_context.user_id}` · view `{_embedded_cfg.validate_view(embedded_context.view)}` · "
            f"case `{embedded_context.case_id or 'not specified'}`. "
            "Identity and permissions were verified server-side from a signed, short-lived context token."
        )
        log("embedded_session_validated", {"tenant_id": embedded_context.tenant_id,
                                           "user_id": embedded_context.user_id,
                                           "view": embedded_context.view,
                                           "case_id": embedded_context.case_id,
                                           "message": "Embedded context validated"})
    elif _embedded_cfg.enabled and _embedded_token is None and st.query_params.get("fs_embed") == "1":
        st.warning("Embedded mode is enabled, but no signed FolioShield context token was supplied. Browser-supplied tenant/role parameters are not trusted.")
except Exception as embedded_error:
    st.error(f"Embedded session rejected: {embedded_error}")
    log("embedded_session_rejected", {"error": str(embedded_error), "message": "Embedded context validation failed"})

if active_theme is not None:
    st.markdown(active_theme.css(), unsafe_allow_html=True)
    if active_theme.logo_url:
        st.markdown(f'<img class="fs-brand-logo" src="{active_theme.logo_url}" alt="Host brand logo"/>', unsafe_allow_html=True)
    if active_theme.brand_name and active_theme.brand_name != "FolioShield":
        st.caption(f"🏨 {active_theme.brand_name} · Powered by FolioShield")

tab_ingest, tab_audit, tab_rebuttal, tab_pdf, tab_legal, tab_integrations, tab_logs = st.tabs([
    "📄 1. Upload Notice & Guest Folio",
    "🔍 2. Stay & Billing Verification",
    "✍️ 3. Dispute Response Letter",
    "📑 4. Generate Bank Evidence Packet",
    "⚖️ 5. Court / Legal Track",
    "🔌 6. Integration Management",
    "🔒 7. Staff Activity & History",
])


# -----------------------------------------------------------------------------
# TAB 1: UPLOAD NOTICE & GUEST FOLIO
# -----------------------------------------------------------------------------
with tab_ingest:
    st.subheader("Front Desk & Back Office Document Intake")
    st.markdown(
        "Upload the bank's dispute notice and the guest's folio ledger (PDF or CSV export from Oracle OPERA, Cloudbeds, Mews, etc.). "
        "No direct PMS connection needed — FolioShield reads your existing hotel exports directly."
    )

    c_up1, c_up2 = st.columns(2)
    with c_up1:
        st.markdown("#### 1. Bank Dispute Notice (PDF)")
        notice_file = st.file_uploader("Upload Acquirer / Issuer Dispute Notice:", type=["pdf"], key="notice_uploader")
        if notice_file:
            notice_bytes = notice_file.getvalue()
            if new_upload("notice", notice_bytes):
                try:
                    validate_upload(notice_bytes, notice_file.name, max_bytes=config.max_upload_bytes)
                    try:
                        notice_text = DocumentExtractor.extract_text_from_pdf(notice_bytes)
                    except ExtractionError:
                        # Scanned / image-only notice: OCR via the vision model, then parse.
                        recognized = llama_engine.extract_text_from_image(notice_bytes)
                        if not recognized:
                            raise ExtractionError(
                                "This notice appears to be a scanned image with no text layer. "
                                "Configure a Llama Vision provider for OCR, or upload a text-based PDF."
                            )
                        from core.security import mask_card_number, sanitize_untrusted_text
                        notice_text = sanitize_untrusted_text(mask_card_number(recognized))
                        log("notice_ocr_fallback", {"filename": notice_file.name, "message": "Scanned notice transcribed via Llama Vision OCR"})
                    parsed_notice = DocumentExtractor.parse_dispute_notice(notice_text)
                except (ExtractionError, ValueError) as e:
                    st.session_state.processed_uploads.pop("notice", None)
                    st.error(f"❌ {e}")
                    log("notice_rejected", {"filename": notice_file.name, "error": str(e)})
                else:
                    st.session_state.notice_data = {**empty_notice(), **parsed_notice}
                    reset_outputs()
                    log("notice_uploaded", {
                        "filename": notice_file.name,
                        "sha256": AuditLogger.calculate_sha256(notice_bytes),
                        "disputed_amount": parsed_notice["disputed_amount"],
                        "message": f"Notice {parsed_notice.get('case_id') or '(no case ID)'} ingested",
                    })
                    st.rerun()
            st.success(f"✓ Notice ingested: Case #{notice_data.get('case_id') or 'not detected'} "
                       f"(${float(notice_data.get('disputed_amount') or 0):,.2f})")

        if config.show_debug_details:
            with st.expander("View Ingested Notice Details", expanded=False):
                st.json({k: v for k, v in notice_data.items() if k != "raw_text"})
            if notice_data.get("raw_text"):
                with st.expander("View extracted notice text (card numbers masked)"):
                    st.code(notice_data["raw_text"][:5000], language=None)

    with c_up2:
        st.markdown("#### 2. Hotel Guest Folio (PDF or CSV)")
        folio_file = st.file_uploader("Upload Itemized Guest Folio / PMS Ledger:", type=["pdf", "csv"], key="folio_uploader")
        if folio_file:
            folio_bytes = folio_file.getvalue()
            if new_upload("folio", folio_bytes):
                try:
                    validate_upload(folio_bytes, folio_file.name, max_bytes=config.max_upload_bytes)
                    if folio_file.name.lower().endswith(".csv"):
                        parsed_folio = DocumentExtractor.parse_folio_csv(folio_bytes)
                    else:
                        parsed_folio = DocumentExtractor.parse_folio_pdf(DocumentExtractor.extract_text_from_pdf(folio_bytes))
                except (ExtractionError, ValueError) as e:
                    st.session_state.processed_uploads.pop("folio", None)
                    st.error(f"❌ {e}")
                    log("folio_rejected", {"filename": folio_file.name, "error": str(e)})
                else:
                    st.session_state.folio_data = {**empty_folio(), **parsed_folio}
                    reset_outputs()
                    log("folio_uploaded", {
                        "filename": folio_file.name,
                        "sha256": AuditLogger.calculate_sha256(folio_bytes),
                        "total_charges": parsed_folio["total_charges"],
                        "message": f"Folio with {len(parsed_folio['line_items'])} line items ingested",
                    })
                    st.rerun()
            st.success(f"✓ Folio parsed: Room #{folio_data.get('room_number') or 'N/A'} "
                       f"(${float(folio_data.get('total_charges') or 0):,.2f})")

        if config.show_debug_details:
            with st.expander("View Ingested Folio Details", expanded=False):
                st.json({k: v for k, v in folio_data.items() if k not in ("line_items", "raw_text")})

    # --- Human review of extracted fields -------------------------------------------------
    with st.expander("✏️ Review & Correct Collected Fields (Notice, Folio, Booking, Authorization)", expanded=False):
        st.caption("Verify every collected field against the notice and your PMS. Any staff corrections are automatically recorded in the audit log.")
        with st.form("field_review"):
            fc1, fc2 = st.columns(2)
            with fc1:
                st.markdown("**Bank notice**")
                n_case = st.text_input("Case ID", value=notice_data.get("case_id") or "")
                current_net = notice_data.get("card_network")
                n_net = st.selectbox("Card network", CARD_NETWORKS,
                                     index=CARD_NETWORKS.index(current_net) if current_net in CARD_NETWORKS else 0)
                n_code = st.text_input("Reason code", value=notice_data.get("reason_code") or "")
                n_amt = st.number_input("Disputed amount", min_value=0.0, step=0.01, format="%.2f",
                                        value=float(notice_data.get("disputed_amount") or 0.0))
                n_orig = st.number_input("Original transaction amount", min_value=0.0, step=0.01, format="%.2f",
                                         value=float(notice_data.get("original_amount") or 0.0))
                n_currency = st.text_input("Currency", value=notice_data.get("currency") or "USD", max_chars=3)
                n_name = st.text_input("Cardholder name", value=notice_data.get("cardholder_name") or "")
                n_last4 = st.text_input("Card last 4 (notice)", value=notice_data.get("card_last_4") or "", max_chars=4)
                n_arn = st.text_input("ARN (23-digit Acquirer Reference Number)", value=notice_data.get("arn") or "")
                n_mid = st.text_input("Merchant ID on notice (MID)", value=notice_data.get("merchant_id") or "")
                n_txn = st.text_input("Transaction date", value=notice_data.get("transaction_date") or "")
                n_disp = st.text_input("Dispute date", value=notice_data.get("dispute_date") or "")
                n_deadline = st.text_input("Response deadline", value=notice_data.get("response_deadline") or "")
                current_stage = notice_data.get("dispute_stage") or ""
                n_stage = st.selectbox("Dispute stage", DISPUTE_STAGES,
                                       index=DISPUTE_STAGES.index(current_stage) if current_stage in DISPUTE_STAGES else 0)
                n_processor = st.text_input("Processor / acquirer", value=notice_data.get("processor") or "")
                n_descriptor = st.text_input("Statement descriptor", value=notice_data.get("statement_descriptor") or "")
                n_claim = st.text_area("Cardholder claim statement (their exact words)", value=notice_data.get("claim_statement") or "", height=80)
            with fc2:
                st.markdown("**Guest folio / PMS**")
                raw_folio = st.session_state.folio_data
                f_hotel = st.text_input("Property name", value=raw_folio.get("hotel_name") or "")
                f_address = st.text_input("Property address", value=raw_folio.get("hotel_address") or "")
                f_mid = st.text_input("Merchant ID (MID)", value=raw_folio.get("merchant_id") or "")
                f_guest = st.text_input("Guest name", value=raw_folio.get("guest_name") or "")
                f_folio = st.text_input("Folio number", value=raw_folio.get("folio_number") or "")
                f_conf = st.text_input("Confirmation / reservation number", value=raw_folio.get("confirmation_number") or "")
                f_room = st.text_input("Room number", value=raw_folio.get("room_number") or "")
                f_in = st.text_input("Check-in date", value=raw_folio.get("check_in") or "")
                f_in_time = st.text_input("Check-in time", value=raw_folio.get("check_in_time") or "")
                f_out = st.text_input("Check-out date", value=raw_folio.get("check_out") or "")
                current_status = raw_folio.get("stay_status") or ""
                f_status = st.selectbox("Stay status", STAY_STATUSES,
                                        index=STAY_STATUSES.index(current_status) if current_status in STAY_STATUSES else 0)
                current_channel = raw_folio.get("booking_channel") or ""
                f_channel = st.selectbox("Booking channel", BOOKING_CHANNELS,
                                         index=BOOKING_CHANNELS.index(current_channel) if current_channel in BOOKING_CHANNELS else 0)
                f_source = st.text_input("Booking source / channel partner", value=raw_folio.get("booking_source") or "")
                f_rate_plan = st.text_input("Rate plan", value=raw_folio.get("rate_plan") or "")
                f_rate = st.number_input("Rate per night", min_value=0.0, step=0.01, format="%.2f",
                                         value=float(raw_folio.get("rate_per_night") or 0.0))
                f_email = st.text_input("Guest email", value=raw_folio.get("guest_email") or "")
                f_payer = st.text_input("Payer name (if different from guest)", value=raw_folio.get("payer_name") or "")
                f_last4 = st.text_input("Card last 4 (folio)", value=raw_folio.get("card_last_4") or "", max_chars=4)
                f_auth = st.text_input("Authorization code", value=raw_folio.get("auth_code") or "")
                f_avs = st.text_input("AVS result", value=raw_folio.get("avs_result") or "")
                f_cvv = st.text_input("CVV result", value=raw_folio.get("cvv_result") or "")
                f_3ds = st.text_input("3-D Secure status / ECI", value=" ".join(filter(None, [raw_folio.get("three_ds_status") or "", raw_folio.get("three_ds_eci") or ""])))
                f_entry = st.text_input("Entry mode (chip/contactless/keyed/ecommerce)", value=raw_folio.get("entry_mode") or "")
                f_refund_amt = st.number_input("Refund already issued ($)", min_value=0.0, step=0.01, format="%.2f",
                                               value=float(raw_folio.get("refund_amount") or 0.0))
                f_refund_ref = st.text_input("Refund date / reference", value=" ".join(filter(None, [raw_folio.get("refund_date") or "", raw_folio.get("refund_reference") or ""])))
                f_cancel = st.text_input("Cancellation timestamp / number", value=" ".join(filter(None, [raw_folio.get("cancellation_timestamp") or "", raw_folio.get("cancellation_number") or ""])))
            if st.form_submit_button("Save corrections", type="primary"):
                bad_last4 = [v for v in (n_last4, f_last4) if v and not (v.isdigit() and len(v) == 4)]
                if bad_last4:
                    st.error("Card last 4 must be exactly four digits.")
                elif n_arn and not (n_arn.isdigit() and len(n_arn) == 23):
                    st.error("ARN must be exactly 23 digits (or blank). Verify it against the bank notice.")
                else:
                    notice_updates = {"case_id": n_case, "card_network": n_net, "reason_code": n_code,
                                      "disputed_amount": round(n_amt, 2), "original_amount": round(n_orig, 2),
                                      "currency": n_currency.upper(), "cardholder_name": n_name, "card_last_4": n_last4,
                                      "arn": n_arn, "merchant_id": n_mid, "transaction_date": n_txn,
                                      "dispute_date": n_disp, "response_deadline": n_deadline,
                                      "dispute_stage": n_stage, "processor": n_processor,
                                      "statement_descriptor": n_descriptor, "claim_statement": n_claim}
                    folio_updates = {"hotel_name": f_hotel, "hotel_address": f_address, "merchant_id": f_mid,
                                     "guest_name": f_guest, "folio_number": f_folio, "confirmation_number": f_conf,
                                     "room_number": f_room, "check_in": f_in, "check_in_time": f_in_time,
                                     "check_out": f_out, "stay_status": f_status, "booking_channel": f_channel,
                                     "booking_source": f_source, "rate_plan": f_rate_plan,
                                     "rate_per_night": round(f_rate, 2), "guest_email": f_email,
                                     "payer_name": f_payer, "card_last_4": f_last4, "auth_code": f_auth,
                                     "avs_result": f_avs, "cvv_result": f_cvv, "entry_mode": f_entry,
                                     "refund_amount": round(f_refund_amt, 2)}
                    # Split combined convenience fields back into their schema fields.
                    tds_parts = f_3ds.split()
                    folio_updates["three_ds_status"] = tds_parts[0] if tds_parts else ""
                    folio_updates["three_ds_eci"] = tds_parts[1] if len(tds_parts) > 1 else ""
                    refund_parts = f_refund_ref.split()
                    folio_updates["refund_date"] = refund_parts[0] if refund_parts else ""
                    folio_updates["refund_reference"] = " ".join(refund_parts[1:])
                    cancel_parts = f_cancel.split()
                    folio_updates["cancellation_timestamp"] = " ".join(cancel_parts[:-1]) if len(cancel_parts) > 1 else f_cancel
                    folio_updates["cancellation_number"] = cancel_parts[-1] if len(cancel_parts) > 1 else ""
                    clean = lambda v: (v.strip() or None) if isinstance(v, str) else v  # noqa: E731
                    changed = [f"notice.{k}" for k, v in notice_updates.items() if clean(v) != notice_data.get(k)]
                    changed += [f"folio.{k}" for k, v in folio_updates.items() if clean(v) != raw_folio.get(k)]
                    if changed:
                        st.session_state.notice_data = {**notice_data, **{k: clean(v) for k, v in notice_updates.items()}}
                        st.session_state.folio_data = {**raw_folio, **{k: clean(v) for k, v in folio_updates.items()}}
                        reset_outputs()
                        log("fields_corrected", {"fields": changed, "message": f"{len(changed)} field(s) corrected"})
                        st.rerun()
                    else:
                        st.info("No changes to save.")

    if collection_gaps:
        st.markdown("#### 📥 Collection Gaps")
        for gap in collection_gaps:
            render = st.error if gap.get("severity") == "critical" else st.warning
            render(f"**{gap.get('field')}:** {gap.get('message')}")

    st.markdown("---")
    st.info(
        "👁️ **Looking for the scan/signature check?** It now lives with the evidence itself: attach the file in "
        "**Tab 2 → Compelling Evidence Collection**, then open **Vision check** under that exhibit. One upload — "
        "the finding is recorded against the collected file's SHA-256 in the chain of custody."
    )


# -----------------------------------------------------------------------------
# TAB 2: STAY & BILLING VERIFICATION
# -----------------------------------------------------------------------------
with tab_audit:
    st.subheader("Stay & Billing Verification")
    st.markdown(
        "Cross-checks the bank's dispute notice against your hotel folio records to verify guest stay dates, card numbers, and billed charges."
    )

    rule_info = reconciliation.get("rule_details") or {}
    net_col1, net_col2 = st.columns([1, 2])
    with net_col1:
        st.markdown(f"### **{network_code}**")
        st.markdown(f"<span class='badge'>{rule_info.get('category', 'Dispute')}</span>", unsafe_allow_html=True)
        st.write(f"**Dispute Reason:** {rule_info.get('name', 'Reason code not in knowledge base')}")
        st.write(f"**Rulebook description:** {rule_info.get('description', 'Verify reason code requirements with your processor.')}")
        if notice_data.get("claim_statement"):
            st.info(f"**🗣️ Cardholder's actual claim:** “{notice_data['claim_statement']}”")
        else:
            st.warning("🗣️ **Cardholder claim statement not collected** — add it in Tab 1 so the rebuttal answers the guest's actual words.")
    with net_col2:
        st.info(f"**🏨 Hotel Defense Playbook (How to Win):**\n{rule_info.get('win_strategy', 'Provide proof of authorization and service delivery.')}")
    st.caption("Reason-code guidance is a simplified hospitality reference — validate against current card-network rules.")

    st.markdown("---")
    st.markdown("#### 1. Stay & Billing Match Highlights")
    for highlight in reconciliation["audit_highlights"]:
        st.success(f"✓ **{highlight}**")
    for disc in reconciliation["discrepancies"]:
        render = {"critical": (st.error, "❌"), "warning": (st.warning, "⚠️")}.get(disc["severity"], (st.info, "ℹ️"))
        render[0](f"{render[1]} **{disc['type']}:** {disc['message']}")

    st.markdown("#### 🧮 Mathematical Proof Panel")
    st.caption(reconciliation.get("proof_summary", ""))
    proof_icon = {"proven": "✅", "failed": "❌", "unverifiable": "❔"}
    proof_rows = [{
        "Proof": p["proof"].replace("_", " ").title(),
        "Result": f"{proof_icon.get(p['status'], '')} {p['status'].upper()}",
        "Arithmetic / Basis": p["detail"],
    } for p in (reconciliation.get("proofs") or [])]
    if proof_rows:
        st.dataframe(pd.DataFrame(proof_rows), width="stretch", hide_index=True)
    pc1, pc2, pc3 = st.columns(3)
    with pc1:
        conf = reconciliation.get("identity_confidence")
        st.metric("Folio Identity Confidence", f"{conf}%" if conf is not None else "—",
                  help="Composite of card last-4, guest-name, and amount signals. Low values suggest the wrong folio.")
    with pc2:
        st.metric("Settlement State", reconciliation.get("settlement_state", "—"),
                  help="SETTLED / SETTLED_THEN_REFUNDED / OVERPAID / OPEN (refunds netted).")
    with pc3:
        bd = reconciliation.get("business_days_to_deadline")
        st.metric("Business Days to Deadline", bd if bd is not None else "—",
                  help="Business-day countdown alongside the calendar-day metric above.")

    st.markdown("---")
    st.markdown("#### 2. Room Charges & Incidentals Breakdown")
    items = folio_data.get("line_items") or []
    if items:
        st.dataframe(pd.DataFrame(items), width="stretch", hide_index=True)
        st.caption("For partial disputes, mark the contested lines in the PMS/folio data (`disputed: true`) or via the SDK/API — "
                   "the reconciler scopes the defense to those items and asks for per-item signed slips.")
    else:
        st.write(f"No explicit line items extracted. Folio total charges: ${float(folio_data.get('total_charges') or 0):,.2f}")

    st.markdown("---")
    st.markdown("#### 3. Compelling Evidence Collection (Files Win Cases)")
    st.caption("Check only documents you actually have. **Attach the file** so it is hashed into the chain of custody — "
               "collected files score higher than attestations and are indexed as exhibits in the packet. "
               "For scans and PDFs, an optional **Vision check** under each exhibit reviews signature/legibility.")
    if st.session_state.get("exhibit_store_degraded"):
        st.warning("⚠️ **Exhibit storage is degraded**: the persistent exhibit directory is unavailable, so files are "
                   "held in memory only and will NOT survive a restart. Fix `FOLIOSHIELD_EXHIBIT_DIR` before relying on collected exhibits.")

    with st.expander("📦 Bulk import — upload a ZIP of evidence files", expanded=False):
        st.caption(
            "Export from your PMS / lock system / gateway, zip the files, and drop the archive here. Each file is routed to its "
            "evidence slot below and hashed into the chain of custody, exactly as if attached individually. "
            "Matching: a `manifest.json` in the ZIP (`{\"wifi_usage_log\": \"wifi.csv\"}`) wins, then filenames containing the slot key "
            "(e.g. `wifi_usage_log.csv`), then filename keywords (e.g. `keycard`, `3ds`, `cctv`). Unmatched files are reported, never guessed."
        )
        st.file_uploader("Evidence ZIP archive", type=["zip"], key="evidence_zip_uploader",
                         on_change=_import_evidence_zip)
        zip_report = st.session_state.get("evidence_zip_report")
        if zip_report:
            if zip_report.get("error"):
                st.error(f"❌ {zip_report['error']}")
            else:
                imported = zip_report.get("imported") or []
                if imported:
                    st.success(f"✓ Imported {len(imported)} file(s) from {zip_report.get('archive')}:")
                    for entry in imported:
                        st.write(f"- **{entry['label']}** ← `{entry['filename']}` (matched by {entry['via']})")
                else:
                    st.warning("No files were imported from that archive.")
                for failure in zip_report.get("failed") or []:
                    st.error(f"❌ `{failure['filename']}` — {failure['reason']}")
                for skipped in zip_report.get("skipped") or []:
                    st.warning(f"⚠️ Skipped `{skipped['filename']}` — {skipped['reason']}")
                unmatched = zip_report.get("unmatched") or []
                if unmatched:
                    st.warning("⚠️ **Not matched to a slot** (attach manually below, or rename / add a manifest.json): "
                               + ", ".join(f"`{name}`" for name in unmatched))
                st.caption("Probative details (recipient, timestamps, amounts) are still recorded per exhibit below — "
                           "the ZIP fills the file slots, the details prove them.")

    for group_key, group in SUPPORTING_DOC_GROUPS.items():
        st.markdown(f"##### {group['label']}")
        for key in group["keys"]:
            label = SUPPORTING_DOC_TYPES[key]
            item = evidence_items.get(key) or {}
            cols = st.columns([2, 2, 1])
            with cols[0]:
                st.checkbox(label, key=f"doc_{key}", help=SUPPORTING_DOC_GUIDANCE.get(key))
                if item.get("filename"):
                    if item.get("bytes_retained"):
                        st.caption(f"📎 {item['filename']} · SHA-256 {str(item.get('sha256') or '')[:12]}…"
                                   + (f" · ✓ {item['verified_by']}" if item.get("verified_by") else "")
                                   + " · file retained")
                    else:
                        st.caption(f"📎 {item['filename']} · SHA-256 {str(item.get('sha256') or '')[:12]}…"
                                   " · ⚠️ metadata only — file bytes not retained. Re-attach the file so it can be bundled as an exhibit.")
                elif item.get("present"):
                    st.caption("Attested only — attach the file to strengthen this exhibit.")
            with cols[1]:
                st.file_uploader(f"Attach {label}", type=["pdf", "png", "jpg", "jpeg", "csv", "eml", "txt"],
                                 key=f"evfile_{key}", label_visibility="collapsed",
                                 on_change=_collect_evidence_file, args=(key, label))
                if st.session_state.get("evidence_upload_error"):
                    st.error(st.session_state.pop("evidence_upload_error"))
            with cols[2]:
                if item.get("filename"):
                    st.button("Remove", key=f"evremove_{key}", on_click=_remove_evidence_file, args=(key, label))
            # Vision check: advisory scan/signature review of the collected file.
            if item.get("filename") and key in VISION_CHECKABLE_DOC_TYPES:
                with st.expander(f"👁️ Vision check — {label}", expanded=False):
                    st.caption("Optional AI review of the collected scan: signature visible? guest name / date legible? "
                               "Advisory only — it does not change evidence status. For PDFs, page 1 is reviewed.")
                    if llama_engine.is_api_configured():
                        st.caption(f"Vision provider ready: {llama_engine.provider} · {llama_engine._vision_model()}")
                    else:
                        st.warning("No vision provider configured — the check cannot analyze the document yet. "
                                   "In the sidebar under AI Processing, choose Groq, Together AI, or OpenRouter and enter an API key "
                                   "(or set LLAMA_PROVIDER and the provider key in .env).")
                    if st.session_state.get("vision_check_error"):
                        st.error(st.session_state.pop("vision_check_error"))
                    st.button("Run Vision Check", key=f"visioncheck_{key}", on_click=_run_vision_check, args=(key, label))
                    check = item.get("vision_check") or {}
                    if check and check.get("sha256") == item.get("sha256"):
                        if not check.get("analyzed"):
                            reason = str(check.get("notes") or "").strip()
                            if reason.startswith("Vision model call failed"):
                                st.warning(f"⚠️ The vision provider call failed, so this document was not analyzed. Verify it visually. Details: {reason}")
                            else:
                                st.warning("⚠️ This check was recorded without a configured vision provider, so the document was not analyzed. Configure a provider in the sidebar (AI Processing), then run the check again.")
                        elif check.get("signature_detected") is True:
                            st.success(f"✓ Model reports a signature is visible · {check.get('checked_by', '')} · {check.get('checked_at', '')}")
                        else:
                            st.warning("⚠️ Model did not confirm a signature on this document. Verify visually before relying on it.")
                        with st.expander("Vision check details", expanded=False):
                            st.json(check)
                    elif check:
                        st.caption("A vision check exists for a previous version of this file. Run it again for the current file.")
            # Probative detail capture for validators (Phase 3)
            detail_fields = {
                "pos_signed_slips": [("slip_reference", "Slip / check reference"), ("amount", "Slip amount ($)")],
                "guest_service_log": [("unresolved_complaints", "Unresolved complaints (0 = clean log)")],
                "keycard_lock_audit": [("first_entry", "First door entry (YYYY-MM-DD HH:MM)"), ("last_entry", "Last door entry")],
                "wifi_usage_log": [("first_entry", "First seen (YYYY-MM-DD HH:MM)"), ("last_entry", "Last seen")],
                "booking_confirmation": [("recipient", "Recipient email"), ("sent_at", "Sent at (timestamp)")],
                "cancellation_policy_acceptance": [("accepted_at", "Accepted at (timestamp)")],
                "avs_cvv_result": [("avs_result", "AVS result code"), ("cvv_result", "CVV result")],
                "refund_credit_receipt": [("amount", "Refund amount ($)"), ("reference", "Refund reference")],
            }.get(key)
            if detail_fields and item.get("present"):
                with st.expander(f"Probative details — {label}", expanded=False):
                    current_details = dict(item.get("details") or {})
                    new_details = dict(current_details)
                    dcols = st.columns(len(detail_fields))
                    for di, (dkey, dlabel) in enumerate(detail_fields):
                        with dcols[di]:
                            raw_val = st.text_input(dlabel, value=str(current_details.get(dkey, "")), key=f"evdetail_{key}_{dkey}")
                            if raw_val.strip():
                                new_details[dkey] = float(raw_val) if dkey == "amount" else (int(raw_val) if dkey == "unresolved_complaints" and raw_val.strip().isdigit() else raw_val.strip())
                            else:
                                new_details.pop(dkey, None)
                    if key == "pos_signed_slips" and (new_details.get("slip_reference") or new_details.get("amount") is not None):
                        new_details["slips"] = [{"reference": new_details.get("slip_reference"), "amount": new_details.get("amount")}]
                    if new_details != current_details and st.button("Save details", key=f"evsave_{key}"):
                        stored = dict(st.session_state.get("evidence_items") or {})
                        updated = dict(stored.get(key) or item)
                        updated["details"] = new_details
                        updated["present"] = True
                        stored[key] = updated
                        st.session_state.evidence_items = stored
                        reset_outputs()
                        log("evidence_details_updated", {"doc_type": key, "details": new_details,
                                                         "message": f"{label} probative details recorded"})
                        st.rerun()
            # Phase 10: court provenance (original type / extraction custody)
            if item.get("present") and key in ("signed_registration_card", "keycard_lock_audit", "id_verification_log",
                                               "wifi_usage_log", "cctv_footage", "booking_confirmation"):
                with st.expander(f"Court provenance — {label}", expanded=False):
                    st.caption("What kind of original do we hold, where is it, and (for electronic logs) who extracted it, when, and how? Courts ask exactly this.")
                    prov = dict(item)
                    pcols = st.columns(2)
                    with pcols[0]:
                        otype = st.selectbox("Original type:", ["", "wet_original", "copy", "scan", "e_signature", "system_export"],
                                             index=(["", "wet_original", "copy", "scan", "e_signature", "system_export"].index(prov.get("original_type") or "")),
                                             key=f"prov_type_{key}")
                        oloc = st.text_input("Original location:", value=prov.get("original_location") or "", key=f"prov_loc_{key}",
                                             placeholder="Physical file location or e-signature platform")
                    with pcols[1]:
                        exby = st.text_input("Extracted/collected by:", value=prov.get("extracted_by") or "", key=f"prov_by_{key}")
                        exmethod = st.text_input("Extraction method / system:", value=prov.get("extraction_method") or prov.get("system_name") or "",
                                                 key=f"prov_method_{key}", placeholder="System name, export method, and filters used")
                    if st.button("Save provenance", key=f"prov_save_{key}"):
                        stored = dict(st.session_state.get("evidence_items") or {})
                        updated = dict(stored.get(key) or item)
                        updated.update({"original_type": otype or None, "original_location": oloc.strip() or None,
                                        "extracted_by": exby.strip() or None,
                                        "extraction_method": exmethod.strip() or None,
                                        "extracted_at": datetime.now(timezone.utc).isoformat()})
                        stored[key] = updated
                        st.session_state.evidence_items = stored
                        reset_outputs()
                        log("evidence_provenance_updated", {"doc_type": key, "original_type": otype,
                                                            "message": f"{label} court provenance recorded"})
                        st.rerun()

    st.markdown("##### Evidence coverage status")
    checklist_df = pd.DataFrame(reconciliation["evidence_checklist"])
    st.dataframe(
        checklist_df[["item", "criticality", "status", "validation_detail"]].rename(
            columns={"item": "Required evidence", "criticality": "Tier", "status": "Status", "validation_detail": "Validation"}),
        width="stretch", hide_index=True,
    )
    readiness = reconciliation.get("evidence_readiness") or {}
    if readiness.get("missing_dispositive"):
        st.error("⛔ **Case-deciding (dispositive) evidence missing for this reason code:** "
                 + "; ".join(readiness["missing_dispositive"])
                 + " — approval in Tab 3 is blocked until collected (or overridden with a logged reason).")
    if readiness.get("adverse"):
        st.warning("⚠️ **Adverse evidence on file (do not cite):** " + "; ".join(readiness["adverse"]))
    if not readiness.get("mapping_curated", True):
        st.info("ℹ️ Generic evidence mapping applied — no curated mapping for this reason code. Verify requirements with your processor.")

    st.markdown("##### Cancellation & booking terms on file (optional)")
    st.text_area("Exact cancellation wording shown to the guest during reservation (printed on page 3 of the packet):",
                 key="policy_text", height=100)


# -----------------------------------------------------------------------------
# TAB 3: DISPUTE RESPONSE LETTER
# -----------------------------------------------------------------------------
with tab_rebuttal:
    st.subheader("Dispute Response Letter Studio")
    st.markdown(
        "Generate and review an evidence-backed dispute rebuttal letter for the bank. "
        "Generated drafts only assert proof confirmed in the checklist above, and **must be approved by a manager or designated staff** before compiling the final packet."
    )

    col_reb_ctrl, col_reb_gen = st.columns([3, 1])
    with col_reb_ctrl:
        st.text_area(
            "Front Desk Notes / Special Guest Context (Optional):",
            key="custom_notes",
            placeholder="Add verified operational context: check-in details, services used, guest communications, and staff observations.",
            help="Included in the drafting prompt as front desk notes (sanitized, max 2,000 characters).",
        )
    with col_reb_gen:
        st.markdown("<br/>", unsafe_allow_html=True)
        if st.button("✨ Draft Response Letter", type="primary", width="stretch"):
            with st.spinner("Drafting response letter..."):
                draft = llama_engine.draft_rebuttal(notice_data, folio_data, reconciliation,
                                                    custom_instructions=st.session_state.custom_notes)
            st.session_state.rebuttal_editor = draft
            st.session_state.draft_engine = llama_engine.last_engine_used
            st.session_state.draft_by = actor()
            st.session_state.approval = None
            log("rebuttal_drafted", {"word_count": len(draft.split()), "engine": llama_engine.last_engine_used,
                                     "sha256": sha256_text(draft), "message": f"Draft generated by {llama_engine.last_engine_used}"})

    if st.session_state.draft_engine:
        st.caption(f"Last draft generated by: `{st.session_state.draft_engine}`")

    st.markdown("#### ✍️ Review Letter & Manager Sign-Off")
    st.text_area("Review and refine the defense letter before signing off and compiling the packet:", key="rebuttal_editor", height=420,
                 placeholder="Click “Draft Response Letter” to generate a starting draft, or write your own.")
    draft_text: str = st.session_state.rebuttal_editor or ""
    unresolved = draft_text.count("[MISSING")

    # --- Submission gate ------------------------------------------------------
    st.markdown("#### 🚦 Submission Readiness Gate")
    missing_dispositive = (reconciliation.get("evidence_readiness") or {}).get("missing_dispositive") or []
    gate_reasons = [f"{g.get('field')}: {g.get('message')}" for g in critical_gaps]
    gate_reasons += [f"Dispositive evidence missing: {label}" for label in missing_dispositive]
    if unresolved:
        gate_reasons.append(f"Draft contains {unresolved} unresolved [MISSING] marker(s) — resolve them or override with a reason")
    if gate_reasons:
        for reason in gate_reasons:
            st.error(f"❌ **{reason}**")
        st.checkbox("Override gate — approve anyway (reason is recorded in the audit log)", key="gate_override")
        if st.session_state.get("gate_override"):
            st.text_input("Override reason (required):", key="gate_override_reason", placeholder="Document the reason and supporting reference for this override")
    elif collection_gaps:
        for gap in collection_gaps:
            st.warning(f"⚠️ **{gap.get('field')}:** {gap.get('message')}")
        st.success("No critical collection gaps — warnings above are advisory.")
    else:
        st.success("✓ All required collection items are present.")

    gate_blocked = bool(gate_reasons) and not (
        st.session_state.get("gate_override") and (st.session_state.get("gate_override_reason") or "").strip()
    )

    approval: Optional[Dict[str, Any]] = st.session_state.approval
    approval_current = bool(approval and approval["fingerprint"] == current_fingerprint())
    stale_components: List[str] = []
    if approval and not approval_current and approval.get("components"):
        stale_components = changed_components(
            {"components": approval["components"]}, current_fingerprint_bundle())

    drafter_name = st.session_state.get("draft_by") or ""
    same_person = bool(drafter_name and drafter_name.strip().lower() == actor().strip().lower())

    col_app1, col_app2 = st.columns([1, 3])
    with col_app1:
        approve_disabled = not draft_text.strip() or not (st.session_state.get("reviewer_name") or "").strip() or gate_blocked
        if st.button("✅ Manager Sign-Off & Approve", disabled=approve_disabled):
            bundle = current_fingerprint_bundle()
            approval_event = st.session_state.audit_logger.log_event("rebuttal_approved", {
                "case_id": notice_data.get("case_id"),
                "rebuttal_sha256": sha256_text(draft_text), "length": len(draft_text),
                "fingerprint": bundle["fingerprint"], "fingerprint_version": bundle["version"],
                "components": bundle["components"],
                "unresolved_missing_markers": unresolved,
                "gate_override": bool(gate_reasons),
                "gate_override_reason": (st.session_state.get("gate_override_reason") or "") if gate_reasons else "",
                "readiness_score": reconciliation.get("completeness_score"),
                "readiness_submittable": (reconciliation.get("evidence_readiness") or {}).get("submittable"),
                "drafted_by": drafter_name or None,
                "via": "streamlit_ui",
                "message": "Rebuttal approved",
            }, user=actor())
            st.session_state.approval = {
                "by": actor(),
                "role": (st.session_state.get("reviewer_role") or "Manager"),
                "at": datetime.now(timezone.utc).isoformat(),
                "fingerprint": bundle["fingerprint"],
                "fingerprint_version": bundle["version"],
                "components": bundle["components"],
                "sha256": sha256_text(draft_text),
                "event_hash": approval_event["event_hash"],
                "drafted_by": drafter_name or None,
            }
            _persist_case()
            st.rerun()
    with col_app2:
        if approval_current:
            st.success(f"Approved by **{approval['by']}** ({approval.get('role', 'Manager')}) at {approval['at']}. "
                       f"Fingerprint `{str(approval['fingerprint'])[:16]}…` · audit event `{str(approval.get('event_hash') or '')[:12]}…`")
            if approval.get("drafted_by") and approval["drafted_by"].strip().lower() == approval["by"].strip().lower():
                st.warning("⚠️ Drafter and approver are the same person — consider a second reviewer for segregation of duties.")
        elif approval:
            changed_txt = f" Changed since approval: **{', '.join(stale_components)}**." if stale_components else ""
            st.warning(f"The case changed after approval.{changed_txt} Review and approve again.")
        elif gate_blocked:
            st.error("🔒 Approval blocked by the submission gate — resolve the critical collection gaps above, or override with a recorded reason.")
        elif approve_disabled:
            st.info("Enter your staff reviewer name in the sidebar and provide a draft to enable manager sign-off.")
        if unresolved:
            st.warning(f"Draft contains {unresolved} `[MISSING ...]` marker(s) — approval is gated until they are resolved or overridden with a logged reason (see Submission Gate above).")

    # System-verified facts hint (Phase 4): what the system can vouch for
    with st.expander("🔎 System-Verified Facts (what FolioShield can verify in this draft)", expanded=False):
        st.caption("Sentences in the draft are system-verified only when they trace to a validated exhibit or a completed verification check below. Anything else is staff-typed and attested by the approver.")
        verified_lines = [f"Exhibit {e.get('letter')}: {e.get('label')}" for e in (reconciliation.get("exhibits") or [])]
        verified_lines += [f"Proof — {p['proof']}: {p['detail']}" for p in (reconciliation.get("proofs") or []) if p["status"] == "proven"]
        if verified_lines:
            for line in verified_lines:
                st.markdown(f"- ✓ {line}")
        else:
            st.info("No validated exhibits or proofs yet — collect evidence in Tab 2.")


# -----------------------------------------------------------------------------
# TAB 4: GENERATE BANK EVIDENCE PACKET & SUBMISSION
# -----------------------------------------------------------------------------
with tab_pdf:
    st.subheader("Bank Submission (Representment)")
    st.markdown(
        "Compile the approved 3-page packet, bundle it with the retained exhibit files, validate the bundle "
        "against your acquirer's portal rules, and track the issuer's decision. FolioShield prepares the "
        "submission — the portal upload itself is performed by hotel staff."
    )

    fingerprint = current_fingerprint()
    approval = st.session_state.approval
    is_approved = bool(approval and approval["fingerprint"] == fingerprint)
    packet_format = current_packet_format()
    pdf_identity = f"{fingerprint}:{packet_format}"
    pdf_current = st.session_state.generated_pdf is not None and st.session_state.pdf_fingerprint == pdf_identity

    if not is_approved:
        st.info("🔒 Approve the defense letter in Tab 3 (Manager Sign-Off) to unlock packet compilation.")

    st.radio(
        "Packet format:",
        options=["executive", "complete"],
        format_func=lambda value: "Executive Packet — 3 pages (cover, folio audit, evidence annex)" if value == "executive" else "Complete Packet — 3 pages + exhibit appendix",
        key="packet_format",
        horizontal=True,
        help="Executive keeps the standard three-page packet. Complete appends exhibit appendix pages after page 3 using retained evidence files.",
    )
    packet_format = current_packet_format()
    pdf_identity = f"{fingerprint}:{packet_format}"
    pdf_current = st.session_state.generated_pdf is not None and st.session_state.pdf_fingerprint == pdf_identity

    col_btn_gen, col_btn_dl = st.columns(2)
    with col_btn_gen:
        compile_label = "🔨 Compile Executive Packet (3 Pages)" if packet_format == "executive" else "🔨 Compile Complete Packet (3 Pages + Appendix)"
        if st.button(compile_label, type="primary", width="stretch", disabled=not is_approved):
            with st.spinner("Generating PDF evidence packet..."):
                from core.client import FolioShield as _FS
                _fs = _FS()
                pdf_bytes = _fs.generate_pdf_packet_hashed(
                    notice_data, folio_data, reconciliation, draft_text,
                    approved_by=f"{approval['by']} ({approval.get('role', 'Manager')})",
                    approved_at=approval["at"],
                    policy_text=st.session_state.policy_text,
                    approval_fingerprint=approval["fingerprint"],
                    chain_head=st.session_state.audit_logger.chain_head,
                    packet_format=packet_format,
                    exhibit_files=retained_exhibit_files() if packet_format == "complete" else None,
                )
            st.session_state.generated_pdf = pdf_bytes
            st.session_state.pdf_fingerprint = pdf_identity
            pdf_current = True
            log("pdf_packet_generated", {"case_id": notice_data.get("case_id"), "size_bytes": len(pdf_bytes),
                                         "packet_format": packet_format,
                                         "sha256": AuditLogger.calculate_sha256(pdf_bytes),
                                         "approval_fingerprint": approval["fingerprint"],
                                         "approval_event_hash": approval.get("event_hash"),
                                         "message": "Evidence packet compiled"})
            st.success("✓ Bank Evidence Packet successfully generated (self-verifying custody block on page 3).")

    with col_btn_dl:
        if pdf_current:
            safe_case = "".join(ch for ch in str(notice_data.get("case_id") or "Packet") if ch.isalnum() or ch in "-_")
            if st.download_button(
                label="📥 Download Bank Dispute Packet (PDF)",
                data=st.session_state.generated_pdf,
                file_name=f"FolioShield_Dispute_{safe_case}.pdf",
                mime="application/pdf",
                width="stretch",
                on_click=lambda: log("pdf_packet_downloaded", {
                    "case_id": notice_data.get("case_id"),
                    "sha256": AuditLogger.calculate_sha256(st.session_state.generated_pdf or b""),
                    "message": "Evidence packet downloaded by staff"}),
            ):
                pass
        else:
            if st.session_state.generated_pdf is not None:
                st.warning("Stay data changed since the last compile — recompile to download.")
            st.button("📥 Download Ready After Compilation", disabled=True, width="stretch")

    if pdf_current:
        st.markdown("#### 👁️ Preview Bank Dispute Packet")
        st.caption("Preview the exact compiled PDF before downloading or building the submission bundle. Use the PDF viewer's page controls to inspect the cover, folio audit, evidence annex, and any appendix pages.")
        preview_col, preview_meta = st.columns([3, 1])
        with preview_meta:
            pdf_hash = AuditLogger.calculate_sha256(st.session_state.generated_pdf or b"")
            st.metric("Packet Size", f"{len(st.session_state.generated_pdf or b'') / 1024:.1f} KB")
            st.metric("Packet SHA-256", f"{pdf_hash[:12]}…")
            st.caption("If the preview does not load in your browser, use the Download button above to open the same PDF locally.")
        with preview_col:
            try:
                st.pdf(st.session_state.generated_pdf, height=900)
            except Exception as preview_error:
                st.warning(f"Inline PDF preview is unavailable in this browser/session: {preview_error}. Download the PDF above to view the identical file.")
                log("pdf_preview_failed", {"case_id": notice_data.get("case_id"), "error": str(preview_error),
                                           "message": "Inline packet preview failed; download fallback shown"})

    # --- Phase 6: Submission bundle ------------------------------------------
    st.markdown("---")
    st.markdown("#### 📦 Submission Bundle (Packet + Exhibits)")
    from core.portals import list_portals, get_portal_profile
    from core.submission import build_submission_bundle, validate_bundle, SubmissionRegistry
    from core.models import SubmissionRecord, OutcomeRecord

    portal_options = {p["name"]: p["id"] for p in list_portals()}
    portal_label = st.selectbox("Acquirer / processor portal:", list(portal_options.keys()), key="portal_picker")
    portal_id = portal_options[portal_label]
    profile = get_portal_profile(portal_id)
    st.caption(f"{profile['portal_hint']} · accepts {', '.join(profile['accepted_types'])} · max {profile['max_bundle_mb']} MB · "
               f"issuer decision typically {profile['decision_window_days'][0]}–{profile['decision_window_days'][1]} days")

    registry = SubmissionRegistry()
    case_key = notice_data.get("case_id") or "unknown"
    prior = registry.load(case_key)
    exhibit_files_now = retained_exhibit_files()
    retained_letters = sorted(exhibit_files_now.keys())
    cited_letters = [e["letter"] for e in (reconciliation.get("exhibits") or []) if e.get("file_backed")]
    unretained = [l for l in cited_letters if l not in retained_letters]
    if unretained:
        st.warning(f"⚠️ Exhibit(s) {', '.join(unretained)} are cited as collected but their file bytes are not retained in this session "
                   "(reference data may not include retained file bytes). Re-upload those files in Tab 2 so they can be bundled.")

    validation = None
    if pdf_current:
        validation = validate_bundle(
            notice_data, reconciliation, draft_text, st.session_state.generated_pdf or b"",
            exhibit_files_now, portal_id=portal_id, approval=approval,
            current_fingerprint=fingerprint, prior_submissions=prior["submissions"])
        st.markdown("##### Pre-submission validation")
        for chk in validation["checks"]:
            (st.success if chk["ok"] else st.error)(f"{'✓' if chk['ok'] else '✗'} **{chk['rule']}** — {chk['detail']}")

    bundle_ready = bool(pdf_current and validation and validation["ok"])
    if st.button("📦 Build Submission Bundle (ZIP)", type="primary", width="stretch", disabled=not bundle_ready):
        manifest = st.session_state.audit_logger.build_case_manifest(case_key)
        zip_bytes, info = build_submission_bundle(
            notice_data, folio_data, reconciliation, st.session_state.generated_pdf or b"",
            exhibit_files_now, manifest, portal_id=portal_id)
        st.session_state.submission_bundle = zip_bytes
        st.session_state.submission_info = info
        log("submission_bundle_built", {"case_id": case_key, "portal": portal_id,
                                        "bundle_sha256": info["bundle_sha256"], "size_bytes": info["size_bytes"],
                                        "exhibits": [m["letter"] for m in info["exhibit_map"]],
                                        "message": "Submission bundle built"})
        st.rerun()

    if st.session_state.get("submission_bundle"):
        info = st.session_state.submission_info
        st.success(f"Bundle ready: `{info['filename']}` ({info['size_bytes'] / 1024:.0f} KB, SHA-256 `{info['bundle_sha256'][:16]}…`, "
                   f"{len(info['exhibit_map'])} exhibit file(s))")
        st.download_button(
            "📥 Download Submission Bundle (ZIP)",
            data=st.session_state.submission_bundle,
            file_name=info["filename"], mime="application/zip", width="stretch",
            on_click=lambda: log("submission_bundle_downloaded", {"case_id": case_key,
                                                                  "bundle_sha256": info["bundle_sha256"],
                                                                  "message": "Submission bundle downloaded"}),
        )
        with st.expander("Portal submission instructions", expanded=True):
            st.text(profile["instructions"])

        st.markdown("##### Mark as submitted (after portal upload)")
        with st.form("mark_submitted"):
            conf_ref = st.text_input("Portal confirmation / reference number:")
            submitted_when = st.text_input("Submitted at (ISO, blank = now UTC):", value="")
            if st.form_submit_button("✅ Mark as Submitted"):
                record = SubmissionRecord(
                    case_id=case_key, arn=notice_data.get("arn"), portal_id=portal_id,
                    portal_name=profile["name"], submitted_by=actor(),
                    submitted_at=submitted_when.strip() or datetime.now(timezone.utc).isoformat(),
                    confirmation_reference=conf_ref.strip() or None,
                    bundle_sha256=info["bundle_sha256"], packet_sha256=info["packet_sha256"],
                    approval_fingerprint=approval["fingerprint"] if approval else None,
                    status="submitted")
                registry.register_submission(record)
                # Phase 7-9: freeze the round snapshot (what the issuer saw)
                from core.escalation import EscalationRegistry, snapshot_round
                esc = EscalationRegistry()
                round_no = len(esc.load(case_key)["rounds"]) + 1
                esc.save_round_snapshot(case_key, snapshot_round(round_no, reconciliation, record.to_dict()))
                try:
                    esc.transition(case_key, "submitted", network=notice_data.get("card_network"), actor=actor())
                except ValueError:
                    pass
                log("submission_registered", {"case_id": case_key, "portal": portal_id,
                                              "confirmation_reference": record.confirmation_reference,
                                              "bundle_sha256": record.bundle_sha256,
                                              "expected_decision_by": record.expected_decision_by,
                                              "message": "Representment submitted via portal (staff-confirmed)"})
                st.success(f"Submitted. Issuer decision expected by {record.expected_decision_by} "
                           f"({profile['decision_window_days'][0]}–{profile['decision_window_days'][1]} day window).")
                st.rerun()

    # --- Outcome tracking -------------------------------------------------------
    st.markdown("---")
    st.markdown("#### 🏁 Issuer Decision & Outcome Tracking")
    status_info = registry.decision_status(case_key)
    oc1, oc2, oc3 = st.columns(3)
    with oc1:
        st.metric("Case Status", status_info["status"].replace("_", " ").title())
    with oc2:
        latest_sub = status_info["latest_submission"] or {}
        st.metric("Submitted", (latest_sub.get("submitted_at") or "—")[:10],
                  delta=f"ref {latest_sub.get('confirmation_reference') or '—'}" if latest_sub else None, delta_color="off")
    with oc3:
        if status_info["decision_overdue"]:
            st.metric("Issuer Decision", "OVERDUE", delta=f"{-status_info['decision_days_left']} day(s) past window", delta_color="inverse")
        elif status_info["decision_days_left"] is not None:
            st.metric("Issuer Decision", f"{status_info['decision_days_left']} day(s) left", delta="within window", delta_color="off")
        else:
            st.metric("Issuer Decision", (status_info["latest_outcome"] or {}).get("decision", "—"))
    if status_info["latest_outcome"]:
        lo = status_info["latest_outcome"]
        st.info(f"Latest outcome: **{lo.get('decision')}** on {(lo.get('decided_at') or '')[:10]} · "
                f"recovered ${float(lo.get('amount_recovered') or 0):,.2f} · next stage: {lo.get('next_stage') or '—'}"
                + (f" · deadline {lo.get('next_deadline')}" if lo.get("next_deadline") else ""))

    with st.form("record_outcome"):
        st.markdown("**Record issuer decision**")
        oc_decision = st.selectbox("Decision:", ["won", "lost", "partially_won"])
        oc_amount = st.number_input("Amount recovered (USD):", min_value=0.0, step=0.01, format="%.2f")
        oc_stage = st.selectbox("Next stage:", ["closed", "pre_arbitration", "second_chargeback", "arbitration"])
        oc_deadline = st.text_input("Next-stage deadline (YYYY-MM-DD, if any):", value="")
        if st.form_submit_button("Record Outcome"):
            outcome = OutcomeRecord(case_id=case_key, decision=oc_decision,
                                    decided_at=datetime.now(timezone.utc).isoformat(),
                                    amount_recovered=round(oc_amount, 2),
                                    next_stage=oc_stage, next_deadline=oc_deadline.strip() or None)
            registry.record_outcome(outcome)
            log("issuer_outcome_recorded", {"case_id": case_key, "decision": oc_decision,
                                            "amount_recovered": round(oc_amount, 2), "next_stage": oc_stage,
                                            "message": "Issuer outcome recorded"})
            st.rerun()

    # --- Phases 7-9: If You Lose ------------------------------------------------
    st.markdown("---")
    st.markdown("#### ⚖️ If You Lose — Escalation Workspace (Second Chargeback · Pre-Arb · Arbitration)")
    from core.escalation import (EscalationRegistry, LOSS_REASONS, NEW_EVIDENCE_ADMISSIBLE,
                                 arbitration_assessment, gap_analysis, round_diff, snapshot_round)
    esc_registry = EscalationRegistry()
    esc_status = esc_registry.status(case_key)
    rounds = esc_status["rounds"]
    prior_round = rounds[-1] if rounds else None

    ec1, ec2, ec3 = st.columns(3)
    with ec1:
        st.metric("Escalation Stage", esc_status["stage"].replace("_", " ").title())
    with ec2:
        if esc_status["stage_deadline"]:
            st.metric("Stage Deadline", esc_status["stage_deadline"],
                      delta=("OVERDUE" if esc_status["stage_overdue"] else f"{esc_status['stage_days_left']} day(s) left"),
                      delta_color="inverse" if esc_status["stage_overdue"] else "off")
        else:
            st.metric("Stage Deadline", "—")
    with ec3:
        st.metric("Rounds Submitted", len(rounds))

    if esc_status["stage_history"]:
        timeline = " → ".join(
            f"{h['stage'].replace('_', ' ')} ({(h.get('entered_at') or '')[:10]})" for h in esc_status["stage_history"])
        st.caption(f"Stage history: {timeline}")
    legal_next = esc_status["legal_next_stages"]
    if legal_next:
        st.caption(f"Legal next stages from here: {', '.join(s.replace('_', ' ') for s in legal_next)}")

    if esc_status["stage"] in ("lost", "second_chargeback", "pre_arbitration") or prior_round:
        st.markdown("##### 1. Why did we lose? (loss analysis)")
        with st.form("record_loss"):
            loss_reason = st.selectbox("Issuer's stated basis:", list(LOSS_REASONS.keys()),
                                       format_func=lambda k: LOSS_REASONS[k])
            issuer_text = st.text_area("Issuer's exact wording (from the determination):", height=70)
            if st.form_submit_button("Record Loss & Analyze Gaps"):
                loss_rec = esc_registry.record_loss(case_key, loss_reason, issuer_text.strip(), actor=actor())
                if esc_status["stage"] not in ("second_chargeback", "pre_arbitration", "arbitration"):
                    try:
                        esc_registry.transition(case_key, "lost", network=notice_data.get("card_network"), actor=actor())
                    except ValueError:
                        pass
                log("loss_recorded", {"case_id": case_key, "loss_reason": loss_reason,
                                      "message": "Issuer loss recorded for escalation"})
                st.session_state.latest_loss = loss_rec
                st.rerun()

        gaps = gap_analysis(prior_round) if prior_round else []
        if gaps:
            st.markdown("##### 2. Gap checklist — what round 1 failed to prove (collect these in Tab 2)")
            for g in gaps:
                icon = "⛔" if g["validation"] == "adverse" else ("❌" if g["validation"] == "missing" else "⚠️")
                st.markdown(f"- {icon} **[{g['criticality']}] {g['item']}** — {g['validation']}: {g['detail']} → *{g['action']}*")
            stage_now = esc_status["stage"]
            if stage_now in NEW_EVIDENCE_ADMISSIBLE:
                admissible = NEW_EVIDENCE_ADMISSIBLE[stage_now]
                if admissible:
                    st.success(f"✓ New evidence is generally admissible at **{stage_now.replace('_', ' ')}** — collect the items above in Tab 2, then draft the supplemental response below. (Verify with your acquirer.)")
                else:
                    st.warning(f"⚠️ New evidence is generally **not** admissible at **{stage_now.replace('_', ' ')}** (notably Visa second chargebacks). The supplemental response should emphasize that round 1 was complete; consider pre-arbitration instead. (Verify with your acquirer.)")

        st.markdown("##### 3. Supplemental response (new evidence round)")
        diff = round_diff(prior_round, reconciliation) if prior_round else None
        if diff:
            st.caption(f"Since round {diff['prior_round']}: {len(diff['new_exhibits'])} new exhibit(s), "
                       f"{len(diff['resolved_gaps'])} gap(s) resolved, {len(diff['still_open_gaps'])} still open.")
        latest_loss = (esc_status["losses"] or [None])[-1]
        if st.button("✍️ Draft Supplemental Rebuttal", disabled=prior_round is None):
            supp = llama_engine.draft_supplemental_rebuttal(
                notice_data, folio_data, reconciliation, prior_round,
                loss=latest_loss, custom_instructions=st.session_state.get("custom_notes"))
            st.session_state.supplemental_draft = supp
            log("supplemental_rebuttal_drafted", {"case_id": case_key, "sha256": sha256_text(supp),
                                                  "message": "Supplemental rebuttal drafted"})
            st.rerun()
        if st.session_state.get("supplemental_draft"):
            st.text_area("Supplemental rebuttal (review before submitting via the portal):",
                         value=st.session_state.supplemental_draft, height=300, key="supplemental_view")
            if st.button("📦 Build Supplemental Bundle (ZIP)"):
                manifest = st.session_state.audit_logger.build_case_manifest(case_key)
                zip_bytes, info = build_submission_bundle(
                    notice_data, folio_data, reconciliation, st.session_state.generated_pdf or b"",
                    exhibit_files_now, manifest, portal_id=portal_id)
                st.session_state.submission_bundle = zip_bytes
                st.session_state.submission_info = info
                log("supplemental_bundle_built", {"case_id": case_key, "bundle_sha256": info["bundle_sha256"],
                                                  "message": "Supplemental bundle built"})
                st.success("Supplemental bundle built — download it in the Submission Bundle section above and submit via the portal, then mark submitted.")

        st.markdown("##### 4. Arbitration decision support")
        assessment = arbitration_assessment(
            notice_data.get("card_network"), float(notice_data.get("disputed_amount") or 0),
            reconciliation.get("completeness_score"))
        ac1, ac2, ac3 = st.columns(3)
        with ac1:
            st.metric("Amount at Stake", f"${assessment['disputed_amount']:,.2f}")
        with ac2:
            st.metric("Fees at Risk (loser pays)", f"${assessment['total_fees_at_risk']:,.2f}",
                      delta=f"filing ${assessment['filing_fee']:,.0f} + review ${assessment['review_fee']:,.0f}", delta_color="off")
        with ac3:
            st.metric("Expected Value (heuristic)", f"${assessment['ev_estimate']:,.2f}",
                      delta=f"break-even strength {assessment['breakeven_strength_pct']}%", delta_color="off")
        rec_label = {"arbitrate": ("success", "⚖️ Recommendation: ARBITRATE"), "consider": ("warning", "⚖️ Recommendation: CONSIDER — strengthen evidence first"),
                     "accept_loss": ("error", "⚖️ Recommendation: ACCEPT THE LOSS")}[assessment["recommendation"]]
        getattr(st, rec_label[0])(f"{rec_label[1]} — {assessment['rationale']}")
        st.caption(assessment["disclaimer"])
        with st.form("record_arbitration"):
            arb_action = st.selectbox("Action:", ["filed", "accepted_loss", "won", "lost"])
            arb_fee_paid = st.number_input("Fee paid / liable (USD):", min_value=0.0, step=0.01, format="%.2f")
            if st.form_submit_button("Record Arbitration Action"):
                esc_registry.record_arbitration(case_key, {
                    "action": arb_action, "fee_paid_or_liable": round(arb_fee_paid, 2),
                    "assessment": assessment, "recorded_by": actor(),
                    "recorded_at": datetime.now(timezone.utc).isoformat()})
                target_stage = {"filed": "arbitration", "accepted_loss": "accepted_loss",
                                "won": "won", "lost": "lost"}[arb_action]
                try:
                    esc_registry.transition(case_key, target_stage, network=notice_data.get("card_network"), actor=actor())
                except ValueError:
                    pass
                log("arbitration_action_recorded", {"case_id": case_key, "action": arb_action,
                                                    "fee": round(arb_fee_paid, 2), "message": "Arbitration action recorded"})
                st.rerun()

    st.markdown("---")
    st.markdown("#### 📑 What's Inside the 3-Page Packet")
    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown("""
        **📄 Page 1: Dispute Cover Letter**
        - Hotel branding & case reference
        - ARN, MID & bank reason code
        - Cardholder's actual claim, quoted
        - Manager-approved defense statement
        - Staff signature & sign-off block
        """)
    with p2:
        st.markdown("""
        **📊 Page 2: Itemized Folio & Stay Audit**
        - Folio #, confirmation #, booking channel
        - Check-in/out dates, room #, and auth code
        - Itemized charges with category & voucher refs
        - Computed ledger balance ($0.00 settled)
        - Stay verification check summary
        """)
    with p3:
        st.markdown("""
        **🏛️ Page 3: Evidence Annex & Certification**
        - Card network compelling evidence checklist
        - Collected evidence files with SHA-256 provenance
        - Collection gaps to resolve
        - Booking cancellation terms disclosure
        - SHA-256 tamper-evident integrity certification
        """)


# -----------------------------------------------------------------------------
# TAB 5: COURT / LEGAL TRACK (Phase 10)
# -----------------------------------------------------------------------------
with tab_legal:
    st.subheader("Court / Legal Track (Beyond the Bank)")
    st.warning("⚖️ **Templates only.** FolioShield assembles court-track documents and checklists. Affidavits must be signed and "
               "notarized, declarations signed by the witness, and all filings reviewed by counsel. Nothing here is legal advice "
               "or an executed document.")
    from core.legal import (LegalRegistry, build_court_bundle, build_fraud_report, compute_damages,
                            generate_business_records_affidavit, generate_demand_letter,
                            generate_witness_declaration, validate_court_bundle)
    from core.models import LegalFilingRecord, WitnessRecord
    from core.chronology import build_chronology as _build_chrono

    legal_registry = LegalRegistry()
    legal_data = legal_registry.load(case_key)
    esc_for_damages = EscalationRegistry()
    esc_data = esc_for_damages.load(case_key)
    damages = compute_damages(notice_data, folio_data,
                              outcomes=status_info.get("outcomes"),
                              arbitration=esc_data.get("arbitration"),
                              chargeback_fee=float(st.session_state.get("chargeback_fee") or 0.0))

    st.markdown("#### 💰 Damages (Statement of Loss)")
    dc1, dc2, dc3, dc4 = st.columns(4)
    with dc1:
        st.metric("Amount Debited", f"${damages['amount_disputed_debited']:,.2f}")
    with dc2:
        st.metric("Fees (CB + Arb)", f"${damages['chargeback_fee'] + damages['arbitration_fees']:,.2f}")
    with dc3:
        st.metric("Recovered", f"${damages['amount_recovered']:,.2f}")
    with dc4:
        st.metric("Net Loss", f"${damages['net_loss']:,.2f}")
    st.number_input("Chargeback fee charged by processor (USD, if any):", min_value=0.0, step=0.01,
                    format="%.2f", key="chargeback_fee")
    st.caption(damages["basis"])

    st.markdown("#### 👤 Witnesses")
    if legal_data["witnesses"]:
        for w in legal_data["witnesses"]:
            st.markdown(f"- **{w.get('name')}** — {w.get('role')} ({', '.join(w.get('linked_events') or [])})")
    with st.form("add_witness"):
        w_name = st.text_input("Witness name:")
        w_role = st.text_input("Role:", value="Front Desk Agent")
        w_events = st.multiselect("Linked events:", ["check_in", "id_verified", "key_issued", "checkout"])
        if st.form_submit_button("Register Witness"):
            if w_name.strip():
                legal_registry.add_witness(case_key, WitnessRecord(name=w_name.strip(), role=w_role.strip() or "Front Desk Agent",
                                                                   linked_events=w_events))
                log("witness_registered", {"case_id": case_key, "witness": w_name.strip(), "message": "Witness registered for legal track"})
                st.rerun()

    st.markdown("#### 📄 Legal Documents (TEMPLATE — sign/notarize offline)")
    affiant_name = st.text_input("Affiant name (records custodian):", key="affiant_name")
    affiant_title = st.text_input("Affiant title:", value="Front Office Manager / Custodian of Records", key="affiant_title")
    doc_col1, doc_col2, doc_col3 = st.columns(3)
    manifest_for_legal = st.session_state.audit_logger.build_case_manifest(case_key)
    chrono_for_legal = _build_chrono(notice_data, folio_data,
                                     {i.get("doc_type"): i for i in reconciliation["evidence_items"]}, reconciliation)
    with doc_col1:
        if st.button("📜 Business Records Affidavit (PDF)"):
            pdf = generate_business_records_affidavit(
                notice_data, folio_data, manifest_for_legal,
                affiant={"name": affiant_name, "title": affiant_title})
            st.session_state.legal_affidavit = pdf
            log("affidavit_generated", {"case_id": case_key, "message": "Business records affidavit template generated"})
        if st.session_state.get("legal_affidavit"):
            st.download_button("⬇️ Affidavit Template", data=st.session_state.legal_affidavit,
                               file_name=f"Affidavit_{case_key}.pdf", mime="application/pdf")
    with doc_col2:
        witness_names = [w.get("name") for w in legal_data["witnesses"]]
        selected_witness = st.selectbox("Witness for declaration:", witness_names or ["(register a witness first)"])
        if st.button("🗣️ Witness Declaration (PDF)", disabled=not witness_names):
            w_rec = next(WitnessRecord.from_dict(w) for w in legal_data["witnesses"] if w.get("name") == selected_witness)
            pdf = generate_witness_declaration(w_rec, notice_data, folio_data, chrono_for_legal["events"])
            st.session_state.legal_declaration = pdf
            log("witness_declaration_generated", {"case_id": case_key, "witness": selected_witness,
                                                  "message": "Witness declaration template generated"})
        if st.session_state.get("legal_declaration"):
            st.download_button("⬇️ Declaration Template", data=st.session_state.legal_declaration,
                               file_name=f"Declaration_{case_key}.pdf", mime="application/pdf")
    with doc_col3:
        pay_by = st.text_input("Demand pay-by date:", value="", placeholder="Payment due date")
        if st.button("✉️ Demand Letter (PDF)"):
            pdf = generate_demand_letter(notice_data, folio_data, damages, pay_by or "[PAY-BY DATE]")
            st.session_state.legal_demand = pdf
            log("demand_letter_generated", {"case_id": case_key, "amount": damages["net_loss"],
                                            "message": "Demand letter template generated"})
        if st.session_state.get("legal_demand"):
            st.download_button("⬇️ Demand Letter Template", data=st.session_state.legal_demand,
                               file_name=f"DemandLetter_{case_key}.pdf", mime="application/pdf")

    st.markdown("#### 🚓 Criminal Fraud Report Pack")
    st.caption("For police / FBI IC3 filings. **Preserve CCTV immediately** — most systems overwrite within days.")
    suspect_desc = st.text_input("Suspect description / fake-ID indicators:", key="suspect_desc",
                                 placeholder="Describe identity-document concerns or fraud indicators")
    if st.button("Build Fraud Report (JSON)"):
        report = build_fraud_report(notice_data, folio_data, damages, chrono_for_legal["events"],
                                    suspect={"description": suspect_desc})
        st.session_state.fraud_report = report
        log("fraud_report_built", {"case_id": case_key, "message": "Fraud incident summary built"})
    if st.session_state.get("fraud_report"):
        st.json(st.session_state.fraud_report)
        st.download_button("⬇️ Fraud Report (JSON)", data=json.dumps(st.session_state.fraud_report, indent=2, default=str),
                           file_name=f"FraudReport_{case_key}.json", mime="application/json")

    st.markdown("#### 🗂️ Filings Tracker")
    with st.form("record_filing"):
        f_kind = st.selectbox("Filing kind:", ["demand_letter", "small_claims_filing", "police_report", "ic3_report"])
        f_status = st.selectbox("Status:", ["draft", "sent", "filed", "received", "closed"])
        f_ref = st.text_input("Report / case / certified-mail article #:")
        f_agency = st.text_input("Court / agency:")
        if st.form_submit_button("Record Filing"):
            legal_registry.record_filing(case_key, LegalFilingRecord(
                case_id=case_key, track="criminal" if f_kind in ("police_report", "ic3_report") else "civil",
                kind=f_kind, status=f_status,
                certified_mail_article=f_ref.strip() or None if f_kind == "demand_letter" else None,
                report_or_case_number=f_ref.strip() or None if f_kind != "demand_letter" else None,
                agency_or_court=f_agency.strip() or None,
                sent_at=datetime.now(timezone.utc).isoformat() if f_status in ("sent", "filed") else None))
            log("legal_filing_recorded", {"case_id": case_key, "kind": f_kind, "status": f_status,
                                          "message": "Legal filing recorded"})
            st.rerun()
    if legal_data["filings"]:
        st.dataframe(pd.DataFrame(legal_data["filings"]), width="stretch", hide_index=True)

    st.markdown("#### ⚖️ Court Bundle")
    court_validation = validate_court_bundle(reconciliation["evidence_items"], legal_data["witnesses"],
                                             legal_data["filings"], damages)
    for chk in court_validation["checks"]:
        (st.success if chk["ok"] else st.warning)(f"{'✓' if chk['ok'] else '✗'} **{chk['rule']}** — {chk['detail']}")
    legal_docs_now: Dict[str, bytes] = {}
    if st.session_state.get("legal_affidavit"):
        legal_docs_now["Business_Records_Affidavit_Template.pdf"] = st.session_state.legal_affidavit
    if st.session_state.get("legal_declaration"):
        legal_docs_now["Witness_Declaration_Template.pdf"] = st.session_state.legal_declaration
    if st.session_state.get("legal_demand"):
        legal_docs_now["Demand_Letter_Template.pdf"] = st.session_state.legal_demand
    if st.button("⚖️ Build Court Bundle (ZIP)", disabled=not court_validation["ok"]):
        zip_bytes, info = build_court_bundle(
            notice_data, folio_data, st.session_state.generated_pdf or b"",
            exhibit_files_now, legal_docs_now, manifest_for_legal, damages,
            fraud_report=st.session_state.get("fraud_report"))
        st.session_state.court_bundle = zip_bytes
        st.session_state.court_info = info
        log("court_bundle_built", {"case_id": case_key, "bundle_sha256": info["bundle_sha256"],
                                   "contents": info["contents"], "message": "Court bundle built"})
        st.rerun()
    if st.session_state.get("court_bundle"):
        info = st.session_state.court_info
        st.success(f"Court bundle ready: `{info['filename']}` ({len(info['contents'])} files, SHA-256 `{info['bundle_sha256'][:16]}…`)")
        st.download_button("📥 Download Court Bundle (ZIP)", data=st.session_state.court_bundle,
                           file_name=info["filename"], mime="application/zip", width="stretch",
                           on_click=lambda: log("court_bundle_downloaded", {"case_id": case_key,
                                                                            "bundle_sha256": info["bundle_sha256"],
                                                                            "message": "Court bundle downloaded"}))


# -----------------------------------------------------------------------------
# TAB 6: INTEGRATION MANAGEMENT
# -----------------------------------------------------------------------------
with tab_integrations:
    st.subheader("Integration Management")
    st.markdown(
        "Manage tenant API credentials, on-premises connector agents, webhooks, embedded configuration, "
        "and integration health. These controls manage integrations only; dispute processing still uses the "
        "existing FolioShield engine and human approval remains explicit."
    )
    st.warning("🔐 Management actions are recorded in the audit log. Raw API secrets are shown once at issuance — store them in your credential manager.")

    from core.integrations.registry import IntegrationRegistry
    from core.integrations.webhooks import WebhookManager

    integration_root = os.getenv("FOLIOSHIELD_INTEGRATION_ROOT", "data/integrations")
    integration_registry = IntegrationRegistry(root=integration_root)
    webhook_manager = WebhookManager(integration_registry)

    mgmt_tenant = st.text_input("Tenant ID to manage:", value=st.session_state.get("mgmt_tenant", ""), key="mgmt_tenant",
                                placeholder="Organization identifier")
    mgmt_confirmed = st.checkbox("I am authorized to manage integrations for this tenant", key="mgmt_confirmed")
    tenant_record = integration_registry.get_tenant(mgmt_tenant) if mgmt_tenant else None

    if mgmt_tenant and not tenant_record:
        st.info("Tenant not found. Create it below to begin enrollment.")
        with st.form("create_tenant"):
            tenant_name = st.text_input("Tenant / hotel group name:")
            tenant_props = st.text_input("Property IDs (comma-separated):", value="")
            if st.form_submit_button("Create Tenant"):
                if not mgmt_confirmed:
                    st.error("Confirm tenant management authorization first.")
                elif tenant_name.strip():
                    created = integration_registry.create_tenant(
                        mgmt_tenant, tenant_name.strip(),
                        property_ids=[p.strip() for p in tenant_props.split(",") if p.strip()])
                    log("integration_tenant_created", {"tenant_id": created["tenant_id"], "message": "Integration tenant created"})
                    st.success(f"Tenant created: {created['tenant_id']}")
                    st.rerun()

    if tenant_record and mgmt_confirmed:
        snapshot = integration_registry.monitoring_snapshot(mgmt_tenant)
        im1, im2, im3, im4 = st.columns(4)
        with im1:
            st.metric("Agents", f"{snapshot['agents']['active']}/{snapshot['agents']['total']} active")
        with im2:
            st.metric("Cases", snapshot["cases"])
        with im3:
            st.metric("Failed Jobs", snapshot["jobs"]["failed"])
        with im4:
            st.metric("Webhook Failures", snapshot["webhook_deliveries"]["failed"])

        st.markdown("#### 🔑 API Credentials")
        credentials = integration_registry.list_credentials(mgmt_tenant)
        if credentials:
            st.dataframe(pd.DataFrame(credentials), width="stretch", hide_index=True)
        with st.form("issue_credential"):
            cred_label = st.text_input("Credential label:", value="PMS integration")
            cred_scopes = st.multiselect(
                "Scopes:",
                ["cases:read", "cases:write", "cases:process", "documents:write", "packets:generate", "audit:read", "webhooks:manage", "agent:sync"],
                default=["cases:read", "cases:write", "cases:process", "documents:write"])
            if st.form_submit_button("Issue API Credential"):
                public, raw_secret = integration_registry.issue_credential(mgmt_tenant, cred_label, cred_scopes)
                st.session_state.last_issued_secret = raw_secret
                st.session_state.last_issued_credential = public["credential_id"]
                log("integration_credential_issued", {"tenant_id": mgmt_tenant, "credential_id": public["credential_id"],
                                                      "message": "Integration API credential issued"})
                st.rerun()
        if st.session_state.get("last_issued_secret"):
            st.error("Copy this secret now. It will not be shown again.")
            st.code(st.session_state.last_issued_secret)
            if st.button("I have stored the secret"):
                st.session_state.last_issued_secret = ""
                st.rerun()
        if credentials:
            revoke_id = st.selectbox("Credential to revoke/suspend:", [c["credential_id"] for c in credentials], key="revoke_cred_id")
            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("Suspend Credential"):
                    integration_registry.suspend_credential(mgmt_tenant, revoke_id)
                    log("integration_credential_suspended", {"tenant_id": mgmt_tenant, "credential_id": revoke_id, "message": "Credential suspended"})
                    st.rerun()
            with rc2:
                if st.button("Revoke Credential", type="primary"):
                    integration_registry.revoke_credential(mgmt_tenant, revoke_id)
                    log("integration_credential_revoked", {"tenant_id": mgmt_tenant, "credential_id": revoke_id, "message": "Credential revoked"})
                    st.rerun()

        st.markdown("#### 🖥️ Connector Agents")
        agents = integration_registry.list_agents(mgmt_tenant)
        if agents:
            st.dataframe(pd.DataFrame(agents), width="stretch", hide_index=True)
        with st.form("register_agent"):
            agent_id = st.text_input("Agent ID:", value="front-office-agent-1")
            agent_name = st.text_input("Agent name:", value="Front Office Connector")
            agent_version = st.text_input("Agent version:", value="0.1.0")
            if st.form_submit_button("Register Agent & Issue Agent Credential"):
                agent, raw_secret = integration_registry.register_agent(mgmt_tenant, agent_id, agent_name, version=agent_version)
                st.session_state.last_agent_secret = raw_secret
                log("integration_agent_registered", {"tenant_id": mgmt_tenant, "agent_id": agent_id,
                                                     "message": "Connector agent registered"})
                st.rerun()
        if st.session_state.get("last_agent_secret"):
            st.error("Copy this agent secret now. Configure it through the agent credential file or environment variable.")
            st.code(st.session_state.last_agent_secret)
            if st.button("I have stored the agent secret"):
                st.session_state.last_agent_secret = ""
                st.rerun()
        if agents:
            selected_agent = st.selectbox("Agent to suspend/revoke:", [a["agent_id"] for a in agents], key="selected_agent")
            ac1, ac2 = st.columns(2)
            with ac1:
                if st.button("Suspend Agent"):
                    integration_registry.set_agent_status(mgmt_tenant, selected_agent, "suspended")
                    log("integration_agent_suspended", {"tenant_id": mgmt_tenant, "agent_id": selected_agent, "message": "Agent suspended"})
                    st.rerun()
            with ac2:
                if st.button("Revoke Agent", type="primary"):
                    integration_registry.set_agent_status(mgmt_tenant, selected_agent, "revoked")
                    log("integration_agent_revoked", {"tenant_id": mgmt_tenant, "agent_id": selected_agent, "message": "Agent revoked"})
                    st.rerun()

        st.markdown("#### 🔔 Webhooks")
        subscriptions = webhook_manager.list_subscriptions(mgmt_tenant)
        if subscriptions:
            st.dataframe(pd.DataFrame(subscriptions), width="stretch", hide_index=True)
        with st.form("create_webhook"):
            hook_url = st.text_input("Webhook HTTPS URL:")
            hook_events = st.multiselect("Events:", ["dispute.received", "document.processed", "reconciliation.completed",
                                                     "evidence.missing_identified", "rebuttal.drafted", "approval.recorded",
                                                     "packet.generated", "processing.failed"], default=["rebuttal.drafted", "packet.generated"])
            if st.form_submit_button("Create Webhook Subscription"):
                try:
                    sub = webhook_manager.subscribe(mgmt_tenant, hook_url, hook_events)
                except ValueError as exc:
                    st.error(str(exc))
                else:
                    st.session_state.last_webhook_secret = sub["secret_shown_once"]
                    log("integration_webhook_created", {"tenant_id": mgmt_tenant, "subscription_id": sub["subscription_id"],
                                                        "message": "Webhook subscription created"})
                    st.rerun()
        if st.session_state.get("last_webhook_secret"):
            st.error("Copy this webhook signing secret now. It will not be shown again.")
            st.code(st.session_state.last_webhook_secret)
            if st.button("I have stored the webhook secret"):
                st.session_state.last_webhook_secret = ""
                st.rerun()
        deliveries = webhook_manager.list_deliveries(mgmt_tenant)
        if deliveries:
            st.markdown("**Recent webhook deliveries**")
            st.dataframe(pd.DataFrame(deliveries[-20:]), width="stretch", hide_index=True)

        st.markdown("#### 🔗 Embedded Configuration")
        from embedded.configuration import EmbeddedConfiguration
        embedded_cfg = EmbeddedConfiguration.from_env()
        st.json({
            "enabled": embedded_cfg.enabled,
            "default_view": embedded_cfg.default_view,
            "allowed_origins": embedded_cfg.allowed_origins,
            "frame_ancestors": embedded_cfg.frame_ancestors(),
            "content_security_policy": embedded_cfg.content_security_policy(),
            "oidc_status": "Requires identity-provider validation (not production-verified)",
        })

        st.markdown("#### 🩺 Diagnostics")
        diagnostics = {
            "tenant": tenant_record,
            "monitoring": snapshot,
            "integration_root": integration_root,
            "api_note": "Built-in API server is for development/controlled testing; production requires TLS termination and network controls.",
            "agent_sql_status": "SQL connectors require vendor validation; filesystem and generic REST connectors are implemented.",
        }
        st.download_button(
            "⬇️ Download redacted integration diagnostics (JSON)",
            data=json.dumps(diagnostics, indent=2, default=str),
            file_name=f"integration_diagnostics_{mgmt_tenant}.json",
            mime="application/json",
            on_click=lambda: log("integration_diagnostics_exported", {"tenant_id": mgmt_tenant,
                                                                      "message": "Redacted integration diagnostics exported"}),
        )
    elif mgmt_tenant and tenant_record and not mgmt_confirmed:
        st.warning("Confirm tenant management authorization to reveal integration controls.")


# -----------------------------------------------------------------------------
# TAB 7: STAFF ACTIVITY & HISTORY
# -----------------------------------------------------------------------------
with tab_logs:
    st.subheader("Staff Activity Log & Chain of Custody")
    st.markdown(
        "Complete chronological history of all staff actions, document uploads, reviewer corrections, "
        "manager approvals, and PDF generations with tamper-evident SHA-256 verification."
    )

    logger_obj: AuditLogger = st.session_state.audit_logger
    events = logger_obj.get_events()
    if events:
        head = logger_obj.chain_head
        if logger_obj.verify_chain():
            st.success(f"🔗 Chain verified — {len(events)} event(s), session `{logger_obj.session_id}` · "
                       f"head `{head['head_hash'][:16]}…`{' · HMAC-protected' if head['hmac_protected'] else ''}")
        else:
            st.error("⛔ Audit chain verification FAILED — log integrity compromised.")
        df_events = pd.DataFrame(events)
        df_events["details"] = df_events["details"].apply(lambda d: json.dumps(d, default=str))
        df_events["event_hash"] = df_events["event_hash"].str[:12]
        st.dataframe(df_events.drop(columns=["prev_hash", "session_id"]), width="stretch", hide_index=True)
        dl1, dl2 = st.columns(2)
        with dl1:
            st.download_button(
                "⬇️ Download staff activity history (JSONL)",
                data="\n".join(json.dumps(e, default=str) for e in events),
                file_name=f"audit_trail_{logger_obj.session_id}.jsonl",
                mime="application/jsonl",
                on_click="ignore",
            )
        with dl2:
            manifest = logger_obj.build_case_manifest(notice_data.get("case_id"))
            st.download_button(
                "⬇️ Download case custody manifest (JSON)",
                data=json.dumps(manifest, indent=2, default=str),
                file_name=f"custody_manifest_{notice_data.get('case_id') or 'case'}.json",
                mime="application/json",
                on_click=lambda: log("custody_manifest_exported", {"case_id": notice_data.get("case_id"),
                                                                    "message": "Case custody manifest exported"}),
            )
        with st.expander("🔍 Verify a saved audit trail from disk", expanded=False):
            st.caption("Re-reads a downloaded/persisted JSONL trail and verifies its hash chain — including truncation/rewrite detection when the expected chain head is supplied.")
            trail_file = st.file_uploader("Audit trail JSONL:", type=["jsonl", "json", "txt"], key="trail_verify_uploader")
            expected_head_hash = st.text_input("Expected chain head hash (optional, from PDF/manifest):", value="")
            expected_count = st.number_input("Expected event count (optional):", min_value=0, value=0, step=1)
            if trail_file and st.button("Verify saved trail"):
                import tempfile, os as _os
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jsonl") as tf:
                    tf.write(trail_file.getvalue())
                    tmp_path = tf.name
                expected = None
                if expected_head_hash.strip():
                    expected = {"head_hash": expected_head_hash.strip(), "event_count": int(expected_count) or None}
                ok, loaded_events, message = AuditLogger.load_and_verify(tmp_path, expected_head=expected)
                _os.unlink(tmp_path)
                if ok:
                    st.success(f"✓ {message}")
                else:
                    st.error(f"⛔ {message}")
                log("audit_trail_disk_verification", {"ok": ok, "events": len(loaded_events), "message": message})
    else:
        st.write("No events recorded in current session.")

    st.markdown("---")
    st.markdown("#### ⚖️ Responsible AI & Legal Disclaimer")
    st.caption("""
    FolioShield is an evidence preparation and decision-support tool. It does not guarantee chargeback reversals,
    legal compliance, or acceptance of generated documents by banks, payment processors, or card networks.
    All generated content should be reviewed by an authorized person before submission. Applicable deadlines,
    dispute reason codes, evidence requirements, and submission procedures must be verified with the relevant payment processor.
    """)
