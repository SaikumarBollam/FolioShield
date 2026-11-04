"""
Evidence callbacks for the Streamlit UI (extracted from app.py).

Single-file collection, ZIP bulk import, removal, and the per-exhibit
vision check. Each function takes the session-state mapping plus its
collaborators explicitly (actor/log callables, exhibit store, persist
hook, vision engine) so the behavior is unit-testable without Streamlit;
app.py binds st.session_state and the real engines via thin wrappers
with the historical names/signatures.
"""

from datetime import datetime, timezone
from typing import Any, Callable, Dict, MutableMapping

from core.audit_logger import AuditLogger
from core.config import config
from core.exhibit_store import ExhibitStoreError
from core.extractor import DocumentExtractor, ExtractionError
from core.models import EvidenceItem
from core.rules import SUPPORTING_DOC_TYPES
from core.security import validate_upload
from core.zip_import import plan_zip_import

from . import state as ui_state

LogFn = Callable[[str, Dict[str, Any]], None]
ActorFn = Callable[[], str]

VISION_DOC_TYPES = [
    "Registration Card", "Government Photo ID", "POS Signed Slip",
    "Terminal Receipt", "Booking Confirmation", "Other Supporting Document",
]


def infer_vision_doc_type(filename: str) -> str:
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


# Evidence slots whose files are visual documents a vision model can review.
VISION_CHECKABLE_DOC_TYPES = {
    "signed_registration_card", "id_verification_log", "pos_signed_slips",
    "emv_terminal_receipt", "cancellation_policy_acceptance",
    "incident_damage_evidence", "cctv_footage", "suspect_id_copy",
    "witness_declaration", "demand_letter", "refund_credit_receipt",
    "guest_service_log", "guest_communication_log", "booking_confirmation",
}
VISION_DOC_TYPE_LABELS = {
    "signed_registration_card": "Registration Card",
    "id_verification_log": "Government Photo ID",
    "suspect_id_copy": "Government Photo ID",
    "pos_signed_slips": "POS Signed Slip",
    "emv_terminal_receipt": "Terminal Receipt",
    "booking_confirmation": "Booking Confirmation",
}


def store_evidence_bytes(state: MutableMapping[str, Any], key: str, label: str, filename: str,
                         data: bytes, *, exhibit_store: Any, actor_fn: ActorFn, log_fn: LogFn,
                         persist_fn: Callable[[], None], via: str = "upload") -> str:
    """Stores evidence bytes into a slot (shared by single upload + ZIP import).

    Returns the SHA-256 digest. Raises ValueError on validation failure.
    Preserves probative details/provenance/vision check when replacing a
    file with identical bytes; clears them when the bytes change.
    """
    digest = AuditLogger.calculate_sha256(data)
    validate_upload(data, filename, max_bytes=config.max_upload_bytes)
    stored = exhibit_store.put(data, filename)
    stored_docs = dict(state.get("evidence_items") or {})
    previous = stored_docs.get(key) or {}
    new_item = EvidenceItem(
        doc_type=key, present=True, filename=filename, sha256=digest,
        verified_by=actor_fn(), verified_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        size_bytes=stored["size_bytes"], mime=stored["mime"], stored_ref=stored["stored_ref"],
    ).to_dict()
    auto_details = DocumentExtractor.extract_evidence_details(key, filename, data)
    if previous.get("sha256") == digest:
        for preserved in ("details", "vision_check", "original_type", "original_location",
                          "extracted_by", "extracted_at", "extraction_method", "system_name"):
            if previous.get(preserved):
                new_item[preserved] = previous[preserved]
    if auto_details:
        new_item["details"] = {**auto_details, **(new_item.get("details") or {})}
    stored_docs[key] = new_item
    state["evidence_items"] = stored_docs
    state["processed_uploads"][f"evidence_{key}"] = digest
    ui_state.set_evidence_present(state, key, True)
    ui_state.mark_case_touched(state)
    persist_fn()
    log_fn("evidence_file_collected", {"doc_type": key, "filename": filename, "sha256": digest,
                                       "size_bytes": stored["size_bytes"], "via": via,
                                       "message": f"{label} collected as evidence file"})
    return digest


def collect_evidence_file(state: MutableMapping[str, Any], key: str, label: str, *,
                          exhibit_store: Any, actor_fn: ActorFn, log_fn: LogFn,
                          persist_fn: Callable[[], None]) -> None:
    """File-uploader callback; runs before widgets are rebuilt on the next run."""
    ev_file = state.get(f"evfile_{key}")
    if ev_file is None:
        return
    ev_bytes = ev_file.getvalue()
    digest = AuditLogger.calculate_sha256(ev_bytes)
    if state["processed_uploads"].get(f"evidence_{key}") == digest:
        return
    try:
        store_evidence_bytes(state, key, label, ev_file.name, ev_bytes,
                             exhibit_store=exhibit_store, actor_fn=actor_fn,
                             log_fn=log_fn, persist_fn=persist_fn)
    except (ValueError, ExhibitStoreError) as e:
        state["processed_uploads"].pop(f"evidence_{key}", None)
        state["evidence_upload_error"] = f"{e}"
        return
    ui_state.reset_outputs(state)


def import_evidence_zip(state: MutableMapping[str, Any], *, exhibit_store: Any, actor_fn: ActorFn,
                        log_fn: LogFn, persist_fn: Callable[[], None]) -> None:
    """ZIP-uploader callback: routes each archived file to its evidence slot."""
    zip_file = state.get("evidence_zip_uploader")
    if zip_file is None:
        return
    zip_bytes = zip_file.getvalue()
    zip_digest = AuditLogger.calculate_sha256(zip_bytes)
    if state["processed_uploads"].get("evidence_zip") == zip_digest:
        return
    state["processed_uploads"]["evidence_zip"] = zip_digest
    max_total = max(config.max_upload_bytes * 5, 10 * 1024 * 1024)
    if len(zip_bytes) > max_total:
        state["evidence_zip_report"] = {
            "error": f"'{zip_file.name}' is {len(zip_bytes) / 1_048_576:.1f} MB; the ZIP limit is {max_total // 1_048_576} MB. "
                     "Split the archive and retry."
        }
        return
    plan = plan_zip_import(zip_bytes, max_file_bytes=config.max_upload_bytes,
                           max_total_bytes=max_total)
    if not plan.get("ok"):
        state["evidence_zip_report"] = {"error": plan.get("error") or "Could not read that ZIP archive."}
        return
    imported, failed = [], []
    for doc_type, entry in (plan.get("matched") or {}).items():
        label = SUPPORTING_DOC_TYPES.get(doc_type, doc_type)
        try:
            digest = store_evidence_bytes(state, doc_type, label, entry["filename"], entry["data"],
                                          exhibit_store=exhibit_store, actor_fn=actor_fn,
                                          log_fn=log_fn, persist_fn=persist_fn,
                                          via=f"zip:{entry.get('via')}")
            imported.append({"doc_type": doc_type, "label": label, "filename": entry["filename"],
                             "via": entry.get("via"), "sha256": digest})
        except (ValueError, ExhibitStoreError) as e:
            failed.append({"filename": entry["filename"], "reason": str(e)})
    state["evidence_zip_report"] = {
        "archive": zip_file.name, "imported": imported, "failed": failed,
        "unmatched": plan.get("unmatched") or [], "skipped": plan.get("skipped") or [],
    }
    if failed:
        # Partial failure: allow re-uploading the same archive to retry the
        # failed files once the underlying problem is fixed.
        state["processed_uploads"].pop("evidence_zip", None)
    log_fn("evidence_zip_imported", {"archive": zip_file.name, "archive_sha256": zip_digest,
                                     "imported": [{"doc_type": i["doc_type"], "filename": i["filename"], "sha256": i["sha256"]} for i in imported],
                                     "unmatched": plan.get("unmatched") or [],
                                     "skipped": plan.get("skipped") or [],
                                     "message": f"ZIP import: {len(imported)} file(s) collected from {zip_file.name}"})
    if imported:
        ui_state.reset_outputs(state)


def remove_evidence_file(state: MutableMapping[str, Any], key: str, label: str, *,
                         log_fn: LogFn, persist_fn: Callable[[], None]) -> None:
    """Remove-button callback; runs before widgets are rebuilt on the next run."""
    stored = dict(state.get("evidence_items") or {})
    stored[key] = EvidenceItem(doc_type=key, present=False).to_dict()
    state["evidence_items"] = stored
    ui_state.set_evidence_present(state, key, False)
    state["processed_uploads"].pop(f"evidence_{key}", None)
    ui_state.reset_outputs(state)
    persist_fn()
    log_fn("evidence_file_removed", {"doc_type": key, "message": f"{label} evidence file removed"})


def run_vision_check(state: MutableMapping[str, Any], key: str, label: str, *,
                     exhibit_store: Any, vision_engine: Any, actor_fn: ActorFn,
                     log_fn: LogFn, persist_fn: Callable[[], None]) -> None:
    """Vision-Check button callback: analyzes the collected exhibit file.

    The finding is stored on the evidence item, bound to the exhibit's
    SHA-256. It is advisory only — it never changes presence or readiness.
    Runs as a callback so session state updates before widgets rebuild.
    """
    stored = dict(state.get("evidence_items") or {})
    item = dict(stored.get(key) or {})
    if not vision_engine.is_api_configured():
        state["vision_check_error"] = (
            "No vision provider is configured, so the document was not analyzed. In the sidebar under "
            "AI Processing, choose Groq, Together AI, or OpenRouter and enter an API key — or set "
            "LLAMA_PROVIDER and the provider's API key in .env — then run the check again."
        )
        return
    data = exhibit_store.get(item.get("stored_ref") or item.get("sha256"), item.get("filename") or "")
    if not data:
        state["vision_check_error"] = "The collected file bytes are no longer available in this session. Re-attach the file, then run the check again."
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
            state["vision_check_error"] = str(e)
            return
    doc_type_label = VISION_DOC_TYPE_LABELS.get(key) or infer_vision_doc_type(filename)
    result = vision_engine.analyze_visual_evidence(analysis_bytes, document_type=doc_type_label)
    check = {
        **result,
        "sha256": item.get("sha256"),
        "filename": filename,
        "source_type": "pdf" if is_pdf else "image",
        "checked_by": actor_fn(),
        "checked_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    }
    if is_pdf:
        check["rendered_sha256"] = rendered_hash
        check["page_analyzed"] = 1
    item["vision_check"] = check
    stored[key] = item
    state["evidence_items"] = stored
    persist_fn()
    log_fn("vision_check_completed", {"doc_type": key, **check,
                                      "message": f"Vision check completed for {label}"})
