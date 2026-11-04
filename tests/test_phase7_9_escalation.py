"""
Phases 7–9 (If You Lose) Tests for FolioShield.

  * Stage machine: legal/illegal transitions, per-stage deadlines, overdue.
  * Round snapshots + gap analysis ranked by criticality (adverse first).
  * Round diff: new exhibits, resolved/still-open gaps; continued lettering.
  * Loss recording with taxonomy labels.
  * Arbitration EV: fee schedule, break-even, recommendations, disclaimer.
  * Supplemental rebuttal: references prior submission, new exhibits only,
    issuer wording answered; SDK parity for status/loss/assessment.
"""

import tempfile
import unittest
from datetime import date

from core.client import FolioShield
from core.escalation import (EscalationRegistry, arbitration_assessment, can_transition,
                             gap_analysis, next_exhibit_letter, round_diff, snapshot_round,
                             stage_deadline)
from core.llm_engine import LlamaEngine
from core.reconciler import Reconciler
from data.sample_scenarios import SCENARIOS

TODAY = date(2026, 11, 3)


def recon_for(key="visa_fraud_10_4", docs="__scenario__"):
    s = SCENARIOS[key]
    d = s["supporting_docs"] if docs == "__scenario__" else docs
    return s, Reconciler.reconcile(s["notice"], s["folio"], d, today=TODAY)


class TestPhase789Escalation(unittest.TestCase):

    def test_01_stage_machine_transitions_and_deadlines(self):
        self.assertTrue(can_transition("lost", "pre_arbitration"))
        self.assertTrue(can_transition("lost", "arbitration"))
        self.assertFalse(can_transition("won", "pre_arbitration"))
        self.assertFalse(can_transition("closed", "submitted"))
        self.assertEqual(stage_deadline("Mastercard", "pre_arbitration", date(2026, 11, 1)), "2026-12-16")
        self.assertEqual(stage_deadline("Visa", "arbitration", date(2026, 11, 1)), "2026-12-01")

        with tempfile.TemporaryDirectory() as tmp:
            registry = EscalationRegistry(root=tmp)
            registry.transition("C-1", "submitted", network="Visa", entered_on=date(2026, 11, 1))
            registry.transition("C-1", "lost", network="Visa", entered_on=date(2026, 12, 20))
            with self.assertRaises(ValueError):
                registry.transition("C-1", "won", network="Visa")  # lost -/-> won directly
            record = registry.transition("C-1", "pre_arbitration", network="Visa", entered_on=date(2026, 12, 21))
            self.assertEqual(record["deadline"], "2027-01-20")
            status = registry.status("C-1", today=date(2027, 1, 25))
            self.assertEqual(status["stage"], "pre_arbitration")
            self.assertTrue(status["stage_overdue"])

    def test_02_gap_analysis_ranking(self):
        _, recon = recon_for("visa_fraud_10_4", docs={})  # nothing collected
        snap = snapshot_round(1, recon, {"submitted_at": "2026-11-01", "portal_id": "chase"})
        gaps = gap_analysis(snap)
        self.assertTrue(gaps)
        # Dispositive gaps come first
        self.assertEqual(gaps[0]["criticality"], "dispositive")
        spec_ids = [g["spec_id"] for g in gaps]
        self.assertIn("keycard", spec_ids)
        self.assertIn("registration", spec_ids)

    def test_03_round_diff_and_continued_letters(self):
        s, recon1 = recon_for("visa_fraud_10_4", docs={})
        snap = snapshot_round(1, recon1, {"submitted_at": "2026-11-01"})
        _, recon2 = recon_for("visa_fraud_10_4")  # full evidence in round 2
        diff = round_diff(snap, recon2)
        self.assertTrue(diff["new_exhibits"])
        self.assertTrue(diff["resolved_gaps"])
        self.assertEqual(next_exhibit_letter(["A", "B", "C"]), "D")
        self.assertEqual(next_exhibit_letter([]), "A")

    def test_04_loss_recording(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = EscalationRegistry(root=tmp)
            record = registry.record_loss("C-2", "insufficient_occupancy", issuer_text="No proof guest occupied the room.")
            self.assertEqual(record["loss_reason_label"], "Insufficient evidence of occupancy / physical presence")
            self.assertEqual(registry.load("C-2")["losses"][0]["loss_reason"], "insufficient_occupancy")

    def test_05_arbitration_economics(self):
        strong = arbitration_assessment("Visa", 5000.0, 90)
        self.assertEqual(strong["total_fees_at_risk"], 500.0)
        self.assertEqual(strong["recommendation"], "arbitrate")
        self.assertGreater(strong["ev_estimate"], 0)

        weak_small = arbitration_assessment("Visa", 200.0, 30)
        self.assertEqual(weak_small["recommendation"], "accept_loss")
        self.assertLess(weak_small["ev_estimate"], 0)
        self.assertIn("not a measured win probability", weak_small["disclaimer"])

        mid = arbitration_assessment("Mastercard", 2000.0, 50)
        self.assertIn(mid["recommendation"], ("consider", "arbitrate", "accept_loss"))
        self.assertEqual(mid["total_fees_at_risk"], 600.0)

    def test_06_supplemental_rebuttal(self):
        s, recon1 = recon_for("visa_fraud_10_4", docs={})
        snap = snapshot_round(1, recon1, {"submitted_at": "2026-11-01T10:00:00+00:00",
                                          "portal_id": "chase", "confirmation_reference": "CH-9",
                                          "bundle_sha256": "b" * 64})
        _, recon2 = recon_for("visa_fraud_10_4")
        draft = LlamaEngine(provider="mock").draft_supplemental_rebuttal(
            s["notice"], s["folio"], recon2, snap,
            loss={"loss_reason_label": "Insufficient evidence of occupancy / physical presence",
                  "issuer_text": "No proof guest occupied the room."})
        self.assertIn("SUPPLEMENTAL REPRESENTMENT", draft)
        self.assertIn("CH-9", draft)
        self.assertIn("No proof guest occupied the room.", draft)
        self.assertIn("INDEX OF NEW / STRENGTHENED EXHIBITS", draft)

    def test_07_sdk_parity(self):
        fs = FolioShield()
        assessment = fs.arbitration_assessment("Visa", 5000.0, 90)
        self.assertEqual(assessment["recommendation"], "arbitrate")
        status = fs.escalation_status("NO-SUCH-CASE")
        self.assertEqual(status["stage"], "chargeback")


if __name__ == "__main__":
    unittest.main()
