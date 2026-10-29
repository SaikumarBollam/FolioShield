"""
Audit Logging and Chain of Custody for FolioShield.
Tracks document ingestion, extraction steps, human approvals, and packet generation.
Each event is hash-chained to its predecessor so after-the-fact edits are detectable.
"""

import hashlib
import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from .config import config

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64


class AuditLogger:
    """
    Maintains a tamper-evident (hash-chained), timestamped log of all dispute actions.
    """

    def __init__(self, log_dir: Optional[str] = None):
        self.log_dir = log_dir or config.log_dir
        os.makedirs(self.log_dir, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.session_id = f"disp_{stamp}_{uuid.uuid4().hex[:8]}"
        self.events: List[Dict[str, Any]] = []

    @staticmethod
    def calculate_sha256(data: bytes) -> str:
        """Computes SHA-256 hash of raw bytes for integrity verification."""
        return hashlib.sha256(data).hexdigest()

    @staticmethod
    def _event_hash(event: Dict[str, Any]) -> str:
        payload = {k: v for k, v in event.items() if k != "event_hash"}
        return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode("utf-8")).hexdigest()

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

    def verify_chain(self) -> bool:
        """Returns True if no event has been modified, removed, or reordered."""
        prev = GENESIS_HASH
        for evt in self.events:
            if evt.get("prev_hash") != prev or evt.get("event_hash") != self._event_hash(evt):
                return False
            prev = evt["event_hash"]
        return True

    def _persist_event(self, event: Dict[str, Any]) -> None:
        file_path = os.path.join(self.log_dir, f"audit_trail_{self.session_id}.jsonl")
        try:
            with open(file_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str) + "\n")
        except OSError as e:
            # Non-blocking if disk write fails; in-memory trail is still kept.
            logger.warning("Could not persist audit event to %s: %s", file_path, e)

    def get_events(self) -> List[Dict[str, Any]]:
        return list(self.events)

    def get_chain_of_custody_summary(self) -> str:
        """Returns a formatted summary suitable for inclusion in dispute packets."""
        lines = [
            f"AUDIT TRAIL & EVIDENCE CHAIN OF CUSTODY (Session: {self.session_id})",
            "-" * 65,
        ]
        for evt in self.events:
            ts = evt["timestamp"][:19].replace("T", " ")
            lines.append(f"[{ts} UTC] {evt['action'].upper()}: {evt.get('details', {}).get('message', '')}")
        return "\n".join(lines)
