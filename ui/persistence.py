"""
Durable persistence accessors for the Streamlit UI (extracted from app.py).

- exhibit_store_for: session ExhibitStore over the persistent
  content-addressed root (fail-loud in production, flagged fallback in dev).
- case_store_for: session CaseStore (None + degraded flag when unavailable).
- persist_case: saves the current case durably; conflicts are surfaced in
  state, never silently resolved.
- open_saved_case: restores a saved case into session state.
- retained_exhibit_files: exhibit letter -> retained bytes for bundling.
"""

from typing import Any, Callable, Dict, MutableMapping, Optional

from core.case_store import CaseConflictError, CaseStore, CaseStoreError
from core.config import config
from core.exhibit_store import ExhibitStore, ExhibitStoreError

from . import state as ui_state


def exhibit_store_for(state: MutableMapping[str, Any]) -> ExhibitStore:
    """Session exhibit store backed by the persistent content-addressed root.

    Bytes survive session/server restarts (keyed by SHA-256 under
    config.exhibit_store_dir). If the directory cannot be created, the app
    falls back to in-memory storage ONLY outside production and flags it
    via state["exhibit_store_degraded"] so the UI warns staff that
    exhibits will not survive a restart. In production the error is raised.
    """
    store = state.get("exhibit_store")
    if store is None:
        try:
            store = ExhibitStore(root=config.exhibit_store_dir)
            state["exhibit_store_degraded"] = False
        except OSError as exc:
            if config.is_production:
                raise ExhibitStoreError(
                    f"Exhibit store directory '{config.exhibit_store_dir}' is unavailable: {exc}. "
                    "Fix FOLIOSHIELD_EXHIBIT_DIR permissions before collecting evidence."
                ) from exc
            store = ExhibitStore()
            state["exhibit_store_degraded"] = True
        state["exhibit_store"] = store
    return store


def case_store_for(state: MutableMapping[str, Any]) -> Optional[CaseStore]:
    """Session case store; None (with a degraded flag) when unavailable."""
    store = state.get("case_store")
    if store is None and not state.get("case_store_failed"):
        try:
            store = CaseStore(config.case_db_path)
            state["case_store"] = store
            state["case_store_degraded"] = False
        except CaseStoreError:
            state["case_store_failed"] = True
            state["case_store_degraded"] = True
    return store


def persist_case(state: MutableMapping[str, Any]) -> None:
    """Saves the current case (notice/folio/evidence/draft/approval) durably.

    Called from mutation callbacks and once per run when the case
    fingerprint changed. Conflicts are surfaced, never silently resolved.
    """
    store = case_store_for(state)
    case_id = (state.get("notice_data") or {}).get("case_id")
    if store is None or not case_id:
        return
    try:
        head = state["audit_logger"].chain_head
        saved = store.save_case(
            case_id,
            state.get("notice_data") or {},
            state.get("folio_data") or {},
            state.get("evidence_items") or {},
            draft_text=state.get("rebuttal_editor") or None,
            policy_text=state.get("policy_text") or None,
            custom_notes=state.get("custom_notes") or None,
            approval=state.get("approval"),
            fingerprint=(state.get("approval") or {}).get("fingerprint"),
            audit_session_id=head.get("session_id"),
            audit_head_hash=head.get("head_hash"),
            audit_event_count=head.get("event_count"),
            status=(state.get("notice_data") or {}).get("dispute_stage") or None,
            expected_updated_at=state.get("case_store_updated_at"),
        )
        state["case_store_updated_at"] = saved["updated_at"]
        state.pop("case_store_conflict", None)
    except CaseConflictError as exc:
        state["case_store_conflict"] = str(exc)
    except CaseStoreError as exc:
        state["case_store_degraded"] = True
        state["case_store_conflict"] = f"Case could not be saved durably: {exc}"


def open_saved_case(state: MutableMapping[str, Any], case_id: str,
                    log_fn: Callable[[str, Dict[str, Any]], None]) -> bool:
    """Restores a saved case into session state. Returns False if missing."""
    store = case_store_for(state)
    if store is None:
        return False
    record = store.load_case(case_id)
    if record is None:
        return False
    ui_state.load_case(state, record["notice"] or {}, record["folio"] or {}, record["evidence_items"] or {})
    state["rebuttal_editor"] = record.get("draft_text") or ""
    state["policy_text"] = record.get("policy_text") or ""
    state["custom_notes"] = record.get("custom_notes") or ""
    state["approval"] = record.get("approval")
    state["case_store_updated_at"] = record.get("updated_at")
    state.pop("case_store_conflict", None)
    log_fn("saved_case_opened", {"case_id": case_id,
                                 "message": f"Reopened saved case {case_id} (saved {record.get('updated_at')})"})
    return True


def retained_exhibit_files(state: MutableMapping[str, Any], reconciliation: Dict[str, Any]) -> Dict[str, bytes]:
    """Exhibit letter -> retained bytes for exhibits whose files we still hold."""
    store = exhibit_store_for(state)
    out: Dict[str, bytes] = {}
    items_by_type = {i.get("doc_type"): i for i in (reconciliation.get("evidence_items") or [])}
    for exhibit in (reconciliation.get("exhibits") or []):
        if not exhibit.get("file_backed"):
            continue
        if exhibit.get("doc_type") == "__folio__":
            folio_bytes = state.get("folio_file_bytes")
            if folio_bytes is not None:
                out[exhibit["letter"]] = folio_bytes
            continue
        item = items_by_type.get(exhibit.get("doc_type")) or {}
        data = store.get(item.get("stored_ref") or exhibit.get("sha256"), item.get("filename") or "")
        if data is not None:
            out[exhibit["letter"]] = data
    return out
