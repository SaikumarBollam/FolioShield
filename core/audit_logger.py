"""
Audit Logging and Chain of Custody for FolioShield.
Tracks document ingestion, extraction steps, human approvals, and packet generation.
Each event is hash-chained to its predecessor so after-the-fact edits are detectable.

Phase 5 (Approval & Chain of Custody):
  * The chain maintains an anchored HEAD (last event hash + event count).
    Truncating tail events or rewriting history changes the head, so both
    attacks fail verification against a previously recorded head.
  * When AUDIT_HMAC_KEY is configured, each event hash is HMAC-SHA256 —
    a full rewrite without the key cannot reproduce valid hashes.
  * Trails persist to JSONL and can be re-loaded and verified from disk
    (load_and_verify); a per-case custody manifest (case IDs, file/evidence
    hashes, approval fingerprint, chain head) can be exported for the bank.
"""

import hashlib
import hmac as hmac_module
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from .config import config

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


class AuditLogger:
    """
    Maintains a tamper-evident (hash-chained), timestamped log of all dispute actions.
    """

    def __init__(self, log_dir: Optional[str] = None, hmac_key: Optional[str] = None):
        self.log_dir = log_dir or config.log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_id = f"disp_{stamp}_{uuid.uuid4().hex[:8]}"
        self.events: List[Dict[str, Any]] = []
        key = hmac_key if hmac_key is not None else os.getenv("AUDIT_HMAC_KEY", "")
        self._hmac_key = key.encode("utf-8") if key else None

    # ------------------------------------------------------------------ hashing

    @staticmethod
    def calculate_sha256(data: bytes) -> str:
        """Computes SHA-256 hash of raw bytes for integrity verification."""
        return hashlib.sha256(data).hexdigest()

    def _event_hash(self, event: Dict[str, Any]) -> str:
        payload = {k: v for k, v in event.items() if k != "event_hash"}
        raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
        if self._hmac_key:
            return hmac_module.new(self._hmac_key, raw, hashlib.sha256).hexdigest()
        return hashlib.sha256(raw).hexdigest()

    @property
    def chain_head(self) -> Dict[str, Any]:
        """Anchored chain head: last event hash + event count + session."""
        return {
            "session_id": self.session_id,
            "event_count": len(self.events),
            "head_hash": self.events[-1]["event_hash"] if self.events else GENESIS_HASH,
            "hmac_protected": self._hmac_key is not None,
        }

    # ------------------------------------------------------------------ logging

    def log_event(self, action: str, details: Dict[str, Any], user: str = "Staff Reviewer") -> Dict[str, Any]:
        """Records a hash-chained audit event and persists it to disk."""
        event = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "session_id": self.session_id,
            "action": action,
            "actor": user,
            "details": details,
            "prev_hash": self.events[-1]["event_hash"] if self.events else GENESIS_HASH,
        }
        event["event_hash"] = self._event_hash(event)
        self.events.append(event)
        self._persist_event(event)
        return event

    def _persist_event(self, event: Dict[str, Any]) -> None:
        file_path = os.path.join(self.log_dir, f"audit_trail_{self.session_id}.jsonl")
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except OSError as e:
            # Non-blocking if disk write fails; in-memory trail is still kept.
            logger.warning("Could not persist audit event to %s: %s", file_path, e)

    # -------------------------------------------------------------- verification

    def verify_chain(self, expected_head: Optional[Dict[str, Any]] = None) -> bool:
        """
        Returns True if no event has been modified, removed, or reordered.
        When expected_head is supplied (e.g. the head printed in a PDF or
        manifest), truncation and full-rewrite attacks also fail: the
        recomputed head must match the anchored head exactly.
        """
        prev = GENESIS_HASH
        for evt in self.events:
            if evt.get("prev_hash") != prev or evt.get("event_hash") != self._event_hash(evt):
                return False
            prev = evt["event_hash"]
        if expected_head is not None:
            head = self.chain_head
            if head["event_count"] != expected_head.get("event_count"):
                return False
            if head["head_hash"] != expected_head.get("head_hash"):
                return False
        return True

    @classmethod
    def load_and_verify(cls, file_path: str, hmac_key: Optional[str] = None,
                        expected_head: Optional[Dict[str, Any]] = None) -> Tuple[bool, List[Dict[str, Any]], str]:
        """
        Re-reads a persisted JSONL trail and verifies its chain.
        Returns (ok, events, message). Detects edits, deletions, reordering,
        and — with expected_head — truncation/rewrites.
        """
        events: List[Dict[str, Any]] = []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                for line_no, line in enumerate(f, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        events.append(json.loads(line))
                    except json.JSONDecodeError:
                        return False, events, f"Line {line_no} is not valid JSON — trail is corrupted or hand-edited."
        except OSError as e:
            return False, [], f"Could not read audit trail: {e}"

        probe = cls.__new__(cls)
        probe.session_id = events[0].get("session_id", "loaded") if events else "loaded"
        probe.events = events
        key = hmac_key if hmac_key is not None else os.getenv("AUDIT_HMAC_KEY", "")
        probe._hmac_key = key.encode("utf-8") if key else None
        probe.log_dir = os.path.dirname(file_path)

        if not probe.verify_chain(expected_head=expected_head):
            return False, events, "Hash chain verification FAILED — events were modified, removed, reordered, truncated, or rewritten."
        return True, events, f"Chain verified: {len(events)} event(s), head {probe.chain_head['head_hash'][:16]}…"

    # ------------------------------------------------------------------ exports

    def get_events(self) -> List[Dict[str, Any]]:
        return list(self.events)

    def get_events_for_case(self, case_id: str) -> List[Dict[str, Any]]:
        """Events whose details reference the given case ID."""
        out = []
        for evt in self.events:
            details = evt.get("details") or {}
            if details.get("case_id") == case_id or case_id in json.dumps(details, default=str):
                out.append(evt)
        return out

    def build_case_manifest(self, case_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Case custody manifest: everything a bank (or auditor) needs to verify
        this case offline — file hashes, evidence hashes, approval record,
        and the anchored chain head.
        """
        events = self.get_events_for_case(case_id) if case_id else list(self.events)
        files: List[Dict[str, Any]] = []
        approval: Optional[Dict[str, Any]] = None
        packet: Optional[Dict[str, Any]] = None
        for evt in events:
            details = evt.get("details") or {}
            if evt["action"] in ("notice_uploaded", "folio_uploaded", "evidence_file_collected") and details.get("sha256"):
                files.append({
                    "action": evt["action"], "filename": details.get("filename"),
                    "doc_type": details.get("doc_type"), "sha256": details.get("sha256"),
                    "event_hash": evt["event_hash"], "timestamp": evt["timestamp"],
                })
            if evt["action"] == "rebuttal_approved":
                approval = {
                    "by": evt.get("actor"), "at": evt["timestamp"],
                    "fingerprint": details.get("fingerprint"),
                    "fingerprint_version": details.get("fingerprint_version"),
                    "rebuttal_sha256": details.get("rebuttal_sha256"),
                    "gate_override": details.get("gate_override"),
                    "event_hash": evt["event_hash"],
                }
            if evt["action"] == "pdf_packet_generated":
                packet = {"sha256": details.get("sha256"), "size_bytes": details.get("size_bytes"),
                          "event_hash": evt["event_hash"], "timestamp": evt["timestamp"]}
        return {
            "manifest_version": "1",
            "case_id": case_id,
            "session_id": self.session_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "chain_head": self.chain_head,
            "files": files,
            "approval": approval,
            "packet": packet,
            "event_count": len(events),
        }

    def get_chain_of_custody_summary(self) -> str:
        """Returns a formatted summary suitable for inclusion in dispute packets."""
        lines = [
            f"AUDIT TRAIL & EVIDENCE CHAIN OF CUSTODY (Session: {self.session_id})",
            "-" * 65,
        ]
        for evt in self.events:
            ts = evt["timestamp"][:19].replace("T", " ")
            lines.append(f"[{ts} UTC] {evt['action'].upper()}: {evt.get('details', {}).get('message', '')}")
        head = self.chain_head
        lines.append(f"Chain head: {head['head_hash'][:16]}… ({head['event_count']} events)")
        return "\n".join(lines)
