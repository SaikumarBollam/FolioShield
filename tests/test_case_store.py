"""Tests: durable case store (SQLite) round-trip, conflicts, corruption."""

import tempfile
import unittest
from pathlib import Path

from core.case_store import CaseConflictError, CaseStore, CaseStoreError

NOTICE = {"case_id": "CB-2026-001", "card_network": "Visa", "reason_code": "10.4",
          "disputed_amount": 842.10, "cardholder_name": "Jonathan Davis"}
FOLIO = {"guest_name": "Jonathan Davis", "folio_number": "F-100", "total_charges": 842.10}
EVIDENCE = {
    "signed_registration_card": {
        "doc_type": "signed_registration_card", "present": True,
        "filename": "reg_card.pdf", "sha256": "a" * 64, "stored_ref": "a" * 64,
        "size_bytes": 1234, "mime": "application/pdf", "verified_by": "Front Desk",
        "verified_at": "2026-11-04 10:00 UTC",
        "details": {"signature_type": "wet"},
        "vision_check": {"analyzed": False, "signature_detected": None},
        "original_type": "wet_original", "original_location": "Cabinet 3",
    },
    "wifi_usage_log": {"doc_type": "wifi_usage_log", "present": False},
}


class TestCaseStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db = str(Path(self._tmp.name) / "cases.db")
        self._stores = []

    def tearDown(self):
        for store in self._stores:
            store.close()
        self._tmp.cleanup()

    def _open(self) -> CaseStore:
        store = CaseStore(self.db)
        self._stores.append(store)
        return store

    def test_save_load_round_trip(self):
        store = self._open()
        saved = store.save_case(
            "CB-2026-001", NOTICE, FOLIO, EVIDENCE,
            draft_text="Draft rebuttalâ€¦", policy_text="Non-refundable.",
            approval={"by": "Duty Manager", "fingerprint": "f" * 64},
            fingerprint="f" * 64, audit_session_id="disp_test", audit_head_hash="h" * 64,
            audit_event_count=7, tenant_id="grand-horizon")
        self.assertEqual(saved["case_id"], "CB-2026-001")
        loaded = self._open().load_case("CB-2026-001")  # fresh instance = restart
        self.assertIsNotNone(loaded)
        self.assertEqual(loaded["notice"]["cardholder_name"], "Jonathan Davis")
        self.assertEqual(loaded["draft_text"], "Draft rebuttalâ€¦")
        self.assertEqual(loaded["approval"]["by"], "Duty Manager")
        self.assertEqual(loaded["audit_event_count"], 7)
        card = loaded["evidence_items"]["signed_registration_card"]
        self.assertTrue(card["present"])
        self.assertEqual(card["details"]["signature_type"], "wet")
        self.assertEqual(card["vision_check"]["analyzed"], False)
        self.assertEqual(card["original_type"], "wet_original")
        self.assertFalse(loaded["evidence_items"]["wifi_usage_log"]["present"])

    def test_list_and_delete(self):
        store = self._open()
        store.save_case("CB-1", NOTICE, FOLIO, {})
        store.save_case("CB-2", NOTICE, FOLIO, {})
        self.assertEqual({c["case_id"] for c in store.list_cases()}, {"CB-1", "CB-2"})
        self.assertTrue(store.delete_case("CB-1"))
        self.assertIsNone(store.load_case("CB-1"))
        self.assertFalse(store.delete_case("CB-1"))

    def test_update_preserves_created_at(self):
        store = self._open()
        first = store.save_case("CB-1", NOTICE, FOLIO, {})
        second = store.save_case("CB-1", NOTICE, FOLIO, {}, draft_text="v2")
        self.assertEqual(first["created_at"], second["created_at"])
        self.assertEqual(store.load_case("CB-1")["draft_text"], "v2")

    def test_optimistic_conflict_detected(self):
        store = self._open()
        saved = store.save_case("CB-1", NOTICE, FOLIO, {})
        store.save_case("CB-1", NOTICE, FOLIO, {}, draft_text="other session",
                        expected_updated_at=saved["updated_at"])
        with self.assertRaises(CaseConflictError):
            store.save_case("CB-1", NOTICE, FOLIO, {}, draft_text="stale write",
                            expected_updated_at=saved["updated_at"])

    def test_corrupt_db_raises_clear_error(self):
        bad = Path(self._tmp.name) / "bad.db"
        bad.write_bytes(b"this is not sqlite at all" * 10)
        with self.assertRaises(CaseStoreError):
            CaseStore(str(bad))

    def test_missing_case_id_rejected(self):
        store = self._open()
        with self.assertRaises(ValueError):
            store.save_case("", NOTICE, FOLIO, {})


if __name__ == "__main__":
    unittest.main()

