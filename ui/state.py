"""
Session-state primitives for the Streamlit UI (extracted from app.py).

These functions operate on an explicit state mapping (Streamlit's
session_state in production, a plain dict in tests). app.py binds them
to st.session_state through thin wrappers.
"""

import hashlib
import json
from typing import Any, Dict, MutableMapping, Optional

from core.models import EvidenceItem
from core.rules import SUPPORTING_DOC_TYPES


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


def actor_from(state: MutableMapping[str, Any]) -> str:
    return (state.get("reviewer_name") or "").strip() or "Staff Reviewer"


def reset_outputs(state: MutableMapping[str, Any]) -> None:
    """Invalidates anything derived from the case data (draft, approval, packet, vision findings)."""
    state["rebuttal_editor"] = ""
    state["draft_engine"] = None
    state["approval"] = None
    state["generated_pdf"] = None
    state["pdf_fingerprint"] = None


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


def set_evidence_items(state: MutableMapping[str, Any], items: Dict[str, Dict[str, Any]]) -> None:
    state["evidence_items"] = items
    for key in SUPPORTING_DOC_TYPES:
        state[f"doc_{key}"] = bool(items.get(key, {}).get("present"))


def set_evidence_present(state: MutableMapping[str, Any], key: str, present: bool) -> None:
    """Set an evidence checkbox value from a callback or pre-widget code path."""
    state[f"doc_{key}"] = bool(present)


def load_case(state: MutableMapping[str, Any], notice: Dict[str, Any], folio: Dict[str, Any],
              docs: Dict[str, Any]) -> None:
    state["notice_data"] = {**empty_notice(), **json.loads(json.dumps(notice))}  # deep copy; never mutate reference-case data
    state["folio_data"] = {**empty_folio(), **json.loads(json.dumps(folio))}
    set_evidence_items(state, normalize_docs_input(docs))
    state["processed_uploads"] = {}
    state["vision_results"] = {}
    state["gate_override"] = False
    state["case_touched"] = has_case_data(state)
    reset_outputs(state)


def has_case_data(state: MutableMapping[str, Any]) -> bool:
    """True when any notice/folio field or evidence item has been populated."""
    notice = state.get("notice_data") or {}
    folio = state.get("folio_data") or {}
    if any(notice.get(k) for k in ("case_id", "arn", "card_network", "reason_code", "cardholder_name",
                                   "card_last_4", "claim_statement", "merchant_id", "transaction_date",
                                   "dispute_date", "response_deadline", "raw_text")):
        return True
    if float(notice.get("disputed_amount") or 0) > 0 or float(notice.get("original_amount") or 0) > 0:
        return True
    if any(folio.get(k) for k in ("guest_name", "folio_number", "confirmation_number", "room_number",
                                  "check_in", "check_out", "card_last_4", "auth_code", "merchant_id",
                                  "line_items", "raw_text")):
        return True
    if float(folio.get("total_charges") or 0) > 0 or float(folio.get("total_payments") or 0) > 0:
        return True
    for key in SUPPORTING_DOC_TYPES:
        if state.get(f"doc_{key}") or (state.get("evidence_items") or {}).get(key, {}).get("present"):
            return True
    if (state.get("rebuttal_editor") or "").strip():
        return True
    return False


def is_case_touched(state: MutableMapping[str, Any]) -> bool:
    """True once the user has interacted with the case or loaded non-empty data.

    Prevents a brand-new blank session from showing a wall of 'Collection
    Gaps' and missing-data errors before the user has uploaded a document
    or clicked an action button.
    """
    return bool(state.get("case_touched")) or has_case_data(state)


def mark_case_touched(state: MutableMapping[str, Any]) -> None:
    """Records that the user has taken an action on the current case."""
    state["case_touched"] = True



def current_evidence_items(state: MutableMapping[str, Any], exhibit_store: Any) -> Dict[str, Dict[str, Any]]:
    """Evidence registry view: checkbox attestations merged with collected files.

    Each file-backed item is annotated with ``bytes_retained`` — whether the
    exhibit store can actually produce its bytes right now — so exhibits are
    only cited as "attached" when they can truly be bundled.
    """
    items: Dict[str, Dict[str, Any]] = {}
    stored = state.get("evidence_items") or {}
    for key in SUPPORTING_DOC_TYPES:
        item = dict(stored.get(key) or {"doc_type": key, "present": False, "details": {}})
        item["present"] = bool(state.get(f"doc_{key}", item.get("present")))
        if item.get("filename") and item.get("sha256"):
            item["bytes_retained"] = exhibit_store.has(
                item.get("stored_ref") or item.get("sha256"), item.get("filename") or "")
        items[key] = item
    return items
