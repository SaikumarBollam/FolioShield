"""
Cross-session audit index (Phase 3 P2).

Audit trails are hash-chained per session (audit_trail_<session>.jsonl),
so one case's custody events scatter across session files as staff work
on it over days. This module assembles a case's full trail across
sessions:

- events_for_case: every event linked to the case (top-level case_id or
  legacy details.case_id), in timestamp order, each tagged with its
  session id and source file.
- verify_case_history: per-session chain verification for the sessions
  that touched the case, so a tampered session is surfaced by name.
- case_history_head: the latest event hash for the case — compared
  against the head recorded in the CaseStore when a case is reopened.

Scanning is bounded (file count + per-file lines) and results are cached
by (path, mtime, size) so repeated UI renders stay cheap.
"""

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from .audit_logger import AuditLogger
from ._jsonl import read_jsonl

MAX_SESSION_FILES = 200
_cache: Dict[str, Tuple[float, int, List[Dict[str, Any]]]] = {}


def _session_files(log_dir: str) -> List[str]:
    if not os.path.isdir(log_dir):
        return []
    names = [n for n in os.listdir(log_dir)
             if n.startswith("audit_trail_") and n.endswith(".jsonl")]
    names.sort()
    return [os.path.join(log_dir, n) for n in names[-MAX_SESSION_FILES:]]


def _load_events(path: str) -> List[Dict[str, Any]]:
    try:
        stat = os.stat(path)
    except OSError:
        return []
    cached = _cache.get(path)
    if cached and cached[0] == stat.st_mtime and cached[1] == stat.st_size:
        return cached[2]
    events, _corrupt = read_jsonl(path)
    _cache[path] = (stat.st_mtime, stat.st_size, events)
    return events


def _event_case_id(event: Dict[str, Any]) -> Optional[str]:
    if event.get("case_id"):
        return str(event["case_id"])
    details = event.get("details") or {}
    value = details.get("case_id")
    return str(value) if value else None


def events_for_case(case_id: str, log_dir: str) -> List[Dict[str, Any]]:
    """All events for a case across session files, timestamp-ordered."""
    out: List[Dict[str, Any]] = []
    for path in _session_files(log_dir):
        for event in _load_events(path):
            if _event_case_id(event) == case_id:
                tagged = dict(event)
                tagged["_source_file"] = os.path.basename(path)
                out.append(tagged)
    out.sort(key=lambda e: (e.get("timestamp") or "", e.get("event_hash") or ""))
    return out


def sessions_for_case(case_id: str, log_dir: str) -> List[str]:
    """Session ids that recorded at least one event for the case."""
    seen: List[str] = []
    for event in events_for_case(case_id, log_dir):
        session = event.get("session_id")
        if session and session not in seen:
            seen.append(session)
    return seen


def verify_case_history(case_id: str, log_dir: str, hmac_key: Optional[str] = None) -> Dict[str, Any]:
    """Per-session chain verification for sessions touching the case.

    Returns {ok, sessions: [{session_id, file, ok, message, events}]}.
    A session that fails verification is named — never silently omitted.
    """
    results: List[Dict[str, Any]] = []
    overall = True
    for path in _session_files(log_dir):
        events = _load_events(path)
        if not any(_event_case_id(e) == case_id for e in events):
            continue
        ok, _events, message = AuditLogger.load_and_verify(path, hmac_key=hmac_key)
        session_id = events[0].get("session_id") if events else "unknown"
        results.append({"session_id": session_id, "file": os.path.basename(path),
                        "ok": ok, "message": message, "events": len(events)})
        overall = overall and ok
    return {"ok": overall, "sessions": results}


def case_history_head(case_id: str, log_dir: str) -> Optional[Dict[str, Any]]:
    """Latest custody anchor for a case: {event_hash, timestamp, session_id}."""
    events = events_for_case(case_id, log_dir)
    if not events:
        return None
    last = events[-1]
    return {"event_hash": last.get("event_hash"), "timestamp": last.get("timestamp"),
            "session_id": last.get("session_id"), "event_count": len(events)}


def merge_case_events(current_events: List[Dict[str, Any]], history_events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merges in-memory session events with indexed history, deduped by hash."""
    by_hash: Dict[str, Dict[str, Any]] = {}
    for event in history_events:
        if event.get("event_hash"):
            by_hash[event["event_hash"]] = event
    for event in current_events:
        if event.get("event_hash"):
            by_hash[event["event_hash"]] = event
    merged = list(by_hash.values())
    merged.sort(key=lambda e: (e.get("timestamp") or "", e.get("event_hash") or ""))
    return merged
