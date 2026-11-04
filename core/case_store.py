"""
Durable Case Store for FolioShield (Phase 1 P0).

Persists case + evidence metadata in SQLite (stdlib sqlite3, WAL mode) so
a case survives server restarts and browser sessions. Evidence file BYTES
stay in the content-addressed ExhibitStore; this store keeps the metadata
(filename, sha256, stored_ref, probative details, vision check, court
provenance) plus the case draft/approval state.

Design rules:
  * Parameterized SQL only; tenant_id recorded for future isolation.
  * Optimistic concurrency: save_case(expected_updated_at=...) refuses to
    silently overwrite a newer record (raises CaseConflictError). Full
    multi-writer conflict resolution is Phase 2; detection is Phase 1.
  * The audit hash-chain stays in AuditLogger JSONL; each save records
    the session's chain head so a reopened case can be tied back to its
    custody trail.
  * A corrupt/unavailable DB raises CaseStoreError with a clear message;
    the UI falls back to session-only operation with a visible warning.
"""

import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS schema_meta (
    version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    tenant_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    status TEXT,
    notice_json TEXT NOT NULL DEFAULT '{}',
    folio_json TEXT NOT NULL DEFAULT '{}',
    draft_text TEXT,
    policy_text TEXT,
    custom_notes TEXT,
    approval_json TEXT,
    fingerprint TEXT,
    audit_session_id TEXT,
    audit_head_hash TEXT,
    audit_event_count INTEGER
);
CREATE TABLE IF NOT EXISTS evidence_items (
    case_id TEXT NOT NULL,
    doc_type TEXT NOT NULL,
    present INTEGER NOT NULL DEFAULT 0,
    filename TEXT,
    sha256 TEXT,
    stored_ref TEXT,
    size_bytes INTEGER,
    mime TEXT,
    verified_by TEXT,
    verified_at TEXT,
    details_json TEXT NOT NULL DEFAULT '{}',
    vision_check_json TEXT,
    provenance_json TEXT NOT NULL DEFAULT '{}',
    PRIMARY KEY (case_id, doc_type),
    FOREIGN KEY (case_id) REFERENCES cases(case_id) ON DELETE CASCADE
);
"""

_PROVENANCE_KEYS = ("original_type", "original_location", "extracted_by",
                    "extracted_at", "extraction_method", "system_name", "source", "notes")


class CaseStoreError(RuntimeError):
    """The case database is unavailable or corrupt."""


class CaseConflictError(CaseStoreError):
    """A save was refused because the stored case is newer than expected."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _json(value: Any, default: str = "{}") -> str:
    try:
        return json.dumps(value, default=str)
    except (TypeError, ValueError):
        return default


def _parse(text: Optional[str], fallback: Any) -> Any:
    if not text:
        return fallback
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return fallback


class CaseStore:
    """SQLite-backed durable store for case + evidence metadata."""

    def __init__(self, db_path: str = "data/cases.db"):
        self.db_path = db_path
        conn = None
        try:
            if db_path != ":memory:":
                os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
            conn = sqlite3.connect(db_path, check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            self._conn = conn
            self._migrate()
        except (sqlite3.Error, OSError, CaseStoreError) as exc:
            if conn is not None:
                try:
                    conn.close()
                except sqlite3.Error:
                    pass
            if isinstance(exc, CaseStoreError):
                raise
            raise CaseStoreError(f"Case database '{db_path}' is unavailable: {exc}") from exc

    # ------------------------------------------------------------- schema

    def _migrate(self) -> None:
        row = None
        try:
            row = self._conn.execute("SELECT version FROM schema_meta LIMIT 1").fetchone()
        except sqlite3.Error:
            row = None
        if row is None:
            with self._conn:
                self._conn.executescript(_SCHEMA)
                self._conn.execute("INSERT INTO schema_meta(version) VALUES (?)", (SCHEMA_VERSION,))
        elif int(row[0]) != SCHEMA_VERSION:
            raise CaseStoreError(
                f"Case database schema version {row[0]} is not supported by this build ({SCHEMA_VERSION}).")

    # ---------------------------------------------------------------- CRUD

    def save_case(
        self,
        case_id: str,
        notice: Dict[str, Any],
        folio: Dict[str, Any],
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
    ) -> Dict[str, Any]:
        """Creates or updates a case. Returns {case_id, created_at, updated_at}.

        When expected_updated_at is given, the save is refused with
        CaseConflictError if the stored record has a different updated_at
        (someone else saved first) — never a silent overwrite.
        """
        if not case_id:
            raise ValueError("case_id is required")
        now = _now()
        try:
            existing = self._conn.execute(
                "SELECT created_at, updated_at FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            if existing and expected_updated_at is not None and existing["updated_at"] != expected_updated_at:
                raise CaseConflictError(
                    f"Case '{case_id}' was modified at {existing['updated_at']} by another session; "
                    "reload it before saving to avoid overwriting their work.")
            created_at = existing["created_at"] if existing else now
            with self._conn:
                self._conn.execute(
                    """INSERT INTO cases (case_id, tenant_id, created_at, updated_at, status,
                           notice_json, folio_json, draft_text, policy_text, custom_notes,
                           approval_json, fingerprint, audit_session_id, audit_head_hash, audit_event_count)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                       ON CONFLICT(case_id) DO UPDATE SET
                           tenant_id=excluded.tenant_id, updated_at=excluded.updated_at,
                           status=excluded.status, notice_json=excluded.notice_json,
                           folio_json=excluded.folio_json, draft_text=excluded.draft_text,
                           policy_text=excluded.policy_text, custom_notes=excluded.custom_notes,
                           approval_json=excluded.approval_json, fingerprint=excluded.fingerprint,
                           audit_session_id=excluded.audit_session_id,
                           audit_head_hash=excluded.audit_head_hash,
                           audit_event_count=excluded.audit_event_count""",
                    (case_id, tenant_id, created_at, now, status,
                     _json(notice), _json(folio), draft_text, policy_text, custom_notes,
                     _json(approval) if approval else None, fingerprint,
                     audit_session_id, audit_head_hash, audit_event_count))
                self._conn.execute("DELETE FROM evidence_items WHERE case_id = ?", (case_id,))
                for doc_type, item in (evidence_items or {}).items():
                    item = item or {}
                    provenance = {k: item.get(k) for k in _PROVENANCE_KEYS if item.get(k) is not None}
                    self._conn.execute(
                        """INSERT INTO evidence_items (case_id, doc_type, present, filename, sha256,
                               stored_ref, size_bytes, mime, verified_by, verified_at,
                               details_json, vision_check_json, provenance_json)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (case_id, doc_type, 1 if item.get("present") else 0,
                         item.get("filename"), item.get("sha256"), item.get("stored_ref"),
                         item.get("size_bytes"), item.get("mime"), item.get("verified_by"),
                         item.get("verified_at"), _json(item.get("details") or {}),
                         _json(item["vision_check"]) if item.get("vision_check") else None,
                         _json(provenance)))
        except CaseConflictError:
            raise
        except sqlite3.Error as exc:
            raise CaseStoreError(f"Could not save case '{case_id}': {exc}") from exc
        return {"case_id": case_id, "created_at": created_at, "updated_at": now}

    def load_case(self, case_id: str) -> Optional[Dict[str, Any]]:
        """Returns the full case record, or None when unknown."""
        try:
            row = self._conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
            if row is None:
                return None
            items: Dict[str, Dict[str, Any]] = {}
            for erow in self._conn.execute(
                    "SELECT * FROM evidence_items WHERE case_id = ?", (case_id,)).fetchall():
                item: Dict[str, Any] = {
                    "doc_type": erow["doc_type"],
                    "present": bool(erow["present"]),
                    "filename": erow["filename"],
                    "sha256": erow["sha256"],
                    "stored_ref": erow["stored_ref"],
                    "size_bytes": erow["size_bytes"],
                    "mime": erow["mime"],
                    "verified_by": erow["verified_by"],
                    "verified_at": erow["verified_at"],
                    "details": _parse(erow["details_json"], {}),
                }
                vision = _parse(erow["vision_check_json"], None)
                if vision:
                    item["vision_check"] = vision
                item.update(_parse(erow["provenance_json"], {}))
                items[erow["doc_type"]] = item
        except sqlite3.Error as exc:
            raise CaseStoreError(f"Could not load case '{case_id}': {exc}") from exc
        return {
            "case_id": row["case_id"],
            "tenant_id": row["tenant_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "status": row["status"],
            "notice": _parse(row["notice_json"], {}),
            "folio": _parse(row["folio_json"], {}),
            "draft_text": row["draft_text"],
            "policy_text": row["policy_text"],
            "custom_notes": row["custom_notes"],
            "approval": _parse(row["approval_json"], None),
            "fingerprint": row["fingerprint"],
            "audit_session_id": row["audit_session_id"],
            "audit_head_hash": row["audit_head_hash"],
            "audit_event_count": row["audit_event_count"],
            "evidence_items": items,
        }

    def list_cases(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """Case summaries, most recently updated first."""
        try:
            if tenant_id:
                rows = self._conn.execute(
                    "SELECT case_id, tenant_id, created_at, updated_at, status, fingerprint "
                    "FROM cases WHERE tenant_id = ? ORDER BY updated_at DESC", (tenant_id,)).fetchall()
            else:
                rows = self._conn.execute(
                    "SELECT case_id, tenant_id, created_at, updated_at, status, fingerprint "
                    "FROM cases ORDER BY updated_at DESC").fetchall()
        except sqlite3.Error as exc:
            raise CaseStoreError(f"Could not list cases: {exc}") from exc
        return [dict(r) for r in rows]

    def delete_case(self, case_id: str) -> bool:
        try:
            with self._conn:
                cur = self._conn.execute("DELETE FROM cases WHERE case_id = ?", (case_id,))
            return cur.rowcount > 0
        except sqlite3.Error as exc:
            raise CaseStoreError(f"Could not delete case '{case_id}': {exc}") from exc

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass
