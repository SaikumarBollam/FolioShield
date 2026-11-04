"""
Phase 6 (Bank Submission) Tests for FolioShield.

  * Exhibit store: content-addressed put/get round-trip (memory + disk).
  * Bundle builder: ZIP contains packet, letter-named exhibits, manifest,
    instructions; hashes recorded; deterministic exhibit map.
  * Pre-submission validator: approval staleness, [MISSING] markers,
    unretained exhibits, portal file-type/size rules, duplicate guard.
  * Portal profiles: Chase/Fiserv/Stripe present with decision windows.
  * Registry: submission gets expected decision date (30–45d window);
    overdue flag flips after the window; outcome recording + status.
  * SDK parity: build/register/outcome via FolioShield client.
"""

import io
import json
import os
import tempfile
import unittest
import zipfile
from datetime import date, timedelta

from core.client import FolioShield
from core.exhibit_store import ExhibitStore
from core.models import OutcomeRecord, SubmissionRecord
from core.portals import get_portal_profile, list_portals
from core.reconciler import Reconciler
from core.submission import SubmissionRegistry, build_submission_bundle, validate_bundle
from data.sample_scenarios import SCENARIOS

TODAY = date(2026, 11, 3)


def scenario_recon(key="amex_partial_c08"):
    s = SCENARIOS[key]
    recon = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
    return s, recon


class TestPhase6Submission(unittest.TestCase):

    def test_01_exhibit_store_roundtrip(self):
        store = ExhibitStore()
        meta = store.put(b"%PDF-fake-reg-card", "reg_card.pdf")
        self.assertEqual(store.get(meta["stored_ref"], "reg_card.pdf"), b"%PDF-fake-reg-card")
        self.assertEqual(meta["mime"], "application/pdf")
        self.assertTrue(store.has(meta["stored_ref"]))

        with tempfile.TemporaryDirectory() as tmp:
            disk_store = ExhibitStore(root=tmp)
            meta2 = disk_store.put(b"a,b,c", "keycard.csv")
            fresh = ExhibitStore(root=tmp)  # new instance, memory empty
            self.assertEqual(fresh.get(meta2["stored_ref"], "keycard.csv"), b"a,b,c")

    def test_02_bundle_contents_and_hashes(self):
        s, recon = scenario_recon()
        packet = b"%PDF-packet-bytes"
        exhibits = {"A": b"folio", "D": b"pos-slips"}
        manifest = {"manifest_version": "1", "case_id": s["notice"]["case_id"], "chain_head": {"head_hash": "x" * 64, "event_count": 3}}
        zip_bytes, info = build_submission_bundle(s["notice"], s["folio"], recon, packet, exhibits, manifest, portal_id="chase")
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            self.assertIn("00_packet.pdf", names)
            self.assertIn("manifest.json", names)
            self.assertIn("SUBMISSION_INSTRUCTIONS.txt", names)
            exhibit_names = [n for n in names if n.startswith("Exhibit_")]
            self.assertEqual(len(exhibit_names), 2)
            self.assertTrue(any(n.startswith("Exhibit_D_") for n in exhibit_names))
            bundle_manifest = json.loads(zf.read("manifest.json"))
            self.assertEqual(bundle_manifest["portal"]["id"], "chase")
            self.assertEqual(len(bundle_manifest["exhibit_map"]), 2)
            instructions = zf.read("SUBMISSION_INSTRUCTIONS.txt").decode()
            self.assertIn("Chase", instructions)
        self.assertEqual(len(info["bundle_sha256"]), 64)
        self.assertTrue(info["filename"].endswith("_Submission.zip"))

    def test_03_validator_rules(self):
        s, recon = scenario_recon()
        approval = {"fingerprint": "fp-1"}
        good = validate_bundle(s["notice"], recon, "clean draft", b"%PDF", {"A": b"x", "B": b"x", "C": b"x", "D": b"x"},
                               portal_id="generic", approval=approval, current_fingerprint="fp-1")
        failed_rules = [c["rule"] for c in good["checks"] if not c["ok"]]
        self.assertNotIn("approval_current", failed_rules)
        self.assertNotIn("no_unresolved_missing", failed_rules)

        stale = validate_bundle(s["notice"], recon, "clean", b"%PDF", {}, portal_id="generic",
                                approval=approval, current_fingerprint="fp-2")
        self.assertIn("approval_current", [c["rule"] for c in stale["checks"] if not c["ok"]])

        missing_markers = validate_bundle(s["notice"], recon, "text [MISSING: x]", b"%PDF", {}, portal_id="generic")
        self.assertIn("no_unresolved_missing", [c["rule"] for c in missing_markers["checks"] if not c["ok"]])

        unretained = validate_bundle(s["notice"], recon, "clean", b"%PDF", {}, portal_id="generic")
        self.assertIn("exhibits_retained", [c["rule"] for c in unretained["checks"] if not c["ok"]])

        dup = validate_bundle(s["notice"], recon, "clean", b"%PDF", {}, portal_id="generic",
                              prior_submissions=[{"status": "submitted", "submitted_at": "2026-11-01", "confirmation_reference": "C-1"}])
        self.assertIn("not_already_submitted", [c["rule"] for c in dup["checks"] if not c["ok"]])
        self.assertFalse(dup["ok"])

    def test_04_portal_profiles(self):
        ids = {p["id"] for p in list_portals()}
        for expected in ("chase", "fiserv", "stripe", "generic"):
            self.assertIn(expected, ids)
        chase = get_portal_profile("chase")
        self.assertEqual(chase["decision_window_days"], (30, 45))
        self.assertIn("pdf", chase["accepted_types"])
        self.assertEqual(get_portal_profile("nonsense")["id"], "generic")

    def test_05_registry_decision_window_and_overdue(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = SubmissionRegistry(root=tmp)
            record = SubmissionRecord(case_id="CASE-9", portal_id="chase", submitted_by="Tester",
                                      submitted_at="2026-10-01T10:00:00+00:00", status="submitted",
                                      confirmation_reference="CH-123")
            saved = registry.register_submission(record)
            self.assertEqual(saved.expected_decision_by, "2026-11-15")  # +45 days

            status = registry.decision_status("CASE-9", today=date(2026, 11, 10))
            self.assertFalse(status["decision_overdue"])
            self.assertEqual(status["decision_days_left"], 5)

            status = registry.decision_status("CASE-9", today=date(2026, 11, 20))
            self.assertTrue(status["decision_overdue"])

            registry.record_outcome(OutcomeRecord(case_id="CASE-9", decision="won",
                                                  decided_at="2026-11-12T09:00:00+00:00",
                                                  amount_recovered=245.0, next_stage="closed"))
            status = registry.decision_status("CASE-9", today=date(2026, 11, 20))
            self.assertEqual(status["status"], "won")
            self.assertFalse(status["decision_overdue"])

    def test_06_sdk_parity(self):
        s, recon = scenario_recon()
        fs = FolioShield()
        zip_bytes, info = fs.build_submission_bundle(
            s["notice"], s["folio"], recon, b"%PDF-packet", {"A": b"folio"}, portal_id="stripe")
        self.assertTrue(zip_bytes.startswith(b"PK"))
        with tempfile.TemporaryDirectory() as tmp:
            import core.submission as submission_module
            original = submission_module.SubmissionRegistry
            submission_module.SubmissionRegistry = lambda: original(root=tmp)
            try:
                saved = fs.register_submission(SubmissionRecord(
                    case_id="SDK-CASE-1", portal_id="stripe", submitted_by="SDK",
                    submitted_at="2026-11-01T00:00:00+00:00", status="submitted",
                    bundle_sha256=info["bundle_sha256"]))
                self.assertIsNotNone(saved.expected_decision_by)
                fs.record_outcome(OutcomeRecord(case_id="SDK-CASE-1", decision="partially_won",
                                                decided_at="2026-11-20T00:00:00+00:00",
                                                amount_recovered=100.0, next_stage="closed"))
                status = original(root=tmp).decision_status("SDK-CASE-1", today=date(2026, 11, 21))
                self.assertEqual(status["status"], "partially_won")
            finally:
                submission_module.SubmissionRegistry = original


if __name__ == "__main__":
    unittest.main()
