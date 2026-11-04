"""Tests: exhibits count as file-backed only when bytes are retained."""

import tempfile
import unittest
from pathlib import Path

from core.exhibit_store import ExhibitStore
from core.reconciler import Reconciler, _is_file_backed

NOTICE = {
    "card_network": "Visa", "reason_code": "10.4", "disputed_amount": 842.10,
    "original_amount": 842.10, "currency": "USD", "cardholder_name": "Jonathan Davis",
    "card_last_4": "4821", "transaction_date": "2026-10-10", "dispute_date": "2026-11-02",
}
FOLIO = {
    "guest_name": "Jonathan Davis", "card_last_4": "4821", "check_in": "2026-10-10",
    "check_out": "2026-10-13", "stay_status": "occupied", "total_charges": 842.10,
    "total_payments": 842.10, "line_items": [], "guest_email": "jonathan.davis@example.com",
}
CARD_DETAILS = {"signature_type": "wet"}


def _recon(item):
    return Reconciler.reconcile(NOTICE, FOLIO, {"signed_registration_card": item})


class TestFileBackedTruth(unittest.TestCase):
    def test_metadata_only_is_not_file_backed_when_annotated(self):
        item = {"present": True, "filename": "reg.pdf", "sha256": "a" * 64,
                "bytes_retained": False, "details": dict(CARD_DETAILS)}
        self.assertFalse(_is_file_backed(item))

    def test_retained_bytes_are_file_backed(self):
        item = {"present": True, "filename": "reg.pdf", "sha256": "a" * 64,
                "bytes_retained": True, "details": dict(CARD_DETAILS)}
        self.assertTrue(_is_file_backed(item))

    def test_unannotated_legacy_behavior_preserved(self):
        item = {"present": True, "filename": "reg.pdf", "sha256": "a" * 64}
        self.assertTrue(_is_file_backed(item))

    def test_reconciler_marks_metadata_only_exhibit(self):
        recon = _recon({"present": True, "filename": "reg.pdf", "sha256": "a" * 64,
                        "bytes_retained": False, "details": dict(CARD_DETAILS)})
        card_rows = [r for r in recon["evidence_checklist"] if "registration card" in r["item"].lower()]
        self.assertTrue(card_rows)
        self.assertIn("metadata only", card_rows[0]["status"])
        exhibits = [e for e in recon["exhibits"] if e["doc_type"] == "signed_registration_card"]
        if exhibits:
            self.assertFalse(exhibits[0]["file_backed"])

    def test_reconciler_marks_retained_exhibit(self):
        recon = _recon({"present": True, "filename": "reg.pdf", "sha256": "a" * 64,
                        "bytes_retained": True, "details": dict(CARD_DETAILS)})
        exhibits = [e for e in recon["exhibits"] if e["doc_type"] == "signed_registration_card"]
        self.assertTrue(exhibits)
        self.assertTrue(exhibits[0]["file_backed"])


class TestPersistentStore(unittest.TestCase):
    def test_bytes_survive_new_store_instance(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = str(Path(tmp) / "exhibits")
            first = ExhibitStore(root=root)
            stored = first.put(b"%PDF-fake-but-stored", "reg.pdf")
            second = ExhibitStore(root=root)  # fresh instance, empty memory
            self.assertTrue(second.has(stored["stored_ref"], "reg.pdf"))
            self.assertEqual(second.get(stored["stored_ref"], "reg.pdf"), b"%PDF-fake-but-stored")


if __name__ == "__main__":
    unittest.main()
