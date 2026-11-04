"""Tests: audit relationships (Phase 3 P2).

Explicit case linkage, cross-session history assembly/verification,
manifest history merge, and tamper detection.
"""

import json
import tempfile
import unittest
from pathlib import Path

from core.audit_index import (case_history_head, events_for_case,
                              merge_case_events, verify_case_history)
from core.audit_logger import AuditLogger


def _logger_with_events(log_dir, actions):
    logger = AuditLogger(log_dir=log_dir)
    for action, details in actions:
        logger.log_event(action, details, user="Tester",
                         case_id=details.get("case_id"))
    return logger


class TestAuditRelationships(unittest.TestCase):
    def test_explicit_case_linkage_and_no_substring_match(self):
        with tempfile.TemporaryDirectory() as tmp:
            logger = _logger_with_events(tmp, [
                ("evidence_file_collected", {"case_id": "CB-100", "filename": "a.pdf"}),
                ("note_added", {"message": "Guest mentioned CB-100 in a comment"}),
                ("evidence_file_collected", {"case_id": "CB-1000", "filename": "b.pdf"}),
            ])
            mine = logger.get_events_for_case("CB-100")
            # Only the explicitly linked event — not the substring mention,
            # not the different case CB-1000.
            self.assertEqual(len(mine), 1)
            self.assertEqual(mine[0]["details"]["filename"], "a.pdf")
            self.assertEqual(mine[0]["case_id"], "CB-100")

    def test_cross_session_history_and_verification(self):
        with tempfile.TemporaryDirectory() as tmp:
            _logger_with_events(tmp, [("notice_uploaded", {"case_id": "CB-200", "filename": "n.pdf"})])
            _logger_with_events(tmp, [("rebuttal_approved", {"case_id": "CB-200", "fingerprint": "f" * 64}),
                                      ("pdf_packet_generated", {"case_id": "CB-200", "sha256": "a" * 64})])
            history = events_for_case("CB-200", tmp)
            self.assertEqual([e["action"] for e in history],
                             ["notice_uploaded", "rebuttal_approved", "pdf_packet_generated"])
            self.assertEqual(len({e["session_id"] for e in history}), 2)
            verification = verify_case_history("CB-200", tmp)
            self.assertTrue(verification["ok"])
            self.assertEqual(len(verification["sessions"]), 2)
            head = case_history_head("CB-200", tmp)
            self.assertEqual(head["event_count"], 3)

    def test_tampered_session_is_named(self):
        with tempfile.TemporaryDirectory() as tmp:
            _logger_with_events(tmp, [("notice_uploaded", {"case_id": "CB-300", "filename": "n.pdf"})])
            trail = next(Path(tmp).glob("audit_trail_*.jsonl"))
            lines = trail.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[0])
            event["details"]["filename"] = "tampered.pdf"  # hash no longer matches
            trail.write_text(json.dumps(event) + "\n", encoding="utf-8")
            verification = verify_case_history("CB-300", tmp)
            self.assertFalse(verification["ok"])
            self.assertEqual(len(verification["sessions"]), 1)
            self.assertFalse(verification["sessions"][0]["ok"])

    def test_manifest_merges_history_deduped(self):
        with tempfile.TemporaryDirectory() as tmp:
            first = _logger_with_events(tmp, [("notice_uploaded", {"case_id": "CB-400", "filename": "n.pdf", "sha256": "b" * 64})])
            second = AuditLogger(log_dir=tmp)
            second.log_event("rebuttal_approved", {"case_id": "CB-400", "fingerprint": "f" * 64},
                             user="Manager", case_id="CB-400")
            manifest = second.build_case_manifest("CB-400", include_history=True)
            self.assertEqual(manifest["event_count"], 2)  # merged, not duplicated
            self.assertEqual(len(manifest["history_sessions"]), 2)
            self.assertTrue(all(s["ok"] for s in manifest["history_sessions"]))
            self.assertEqual(manifest["approval"]["fingerprint"], "f" * 64)
            self.assertEqual(manifest["files"][0]["filename"], "n.pdf")
            # Without history, only the current session is covered.
            session_only = second.build_case_manifest("CB-400")
            self.assertEqual(session_only["event_count"], 1)
            self.assertEqual(session_only["history_sessions"], [])

    def test_merge_dedupes_by_event_hash(self):
        event = {"event_hash": "h1", "timestamp": "2026-01-01T00:00:00+00:00", "action": "x"}
        merged = merge_case_events([event], [event, {"event_hash": "h2", "timestamp": "2026-01-02T00:00:00+00:00", "action": "y"}])
        self.assertEqual([e["event_hash"] for e in merged], ["h1", "h2"])


if __name__ == "__main__":
    unittest.main()
