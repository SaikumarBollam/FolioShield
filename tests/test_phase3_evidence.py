"""
Phase 3 (Evidence Mapping) Tests for FolioShield.

The audit's decisive probes as regression tests:
  * Amex C08: POS slip presence/absence/wrong-amount changes the outcome;
    per-item exact-amount + reference binding; uncovered items named.
  * Visa 10.4: ID alone does NOT satisfy physical presence; AVS no-match is
    adverse; booking recipient is validated.
  * MC 4853: service log with unresolved complaints is adverse, not satisfied.
  * Visa 13.1: no-show branch excludes occupancy specs; occupied excludes
    no-show policy spec.
  * Criticality: missing dispositive blocks submittability; unknown codes
    are labelled generic; validators unit-tested; semantic exhibits; PDF.
"""

import io
import unittest
from datetime import date

import pypdf

from core.evidence_validators import VALIDATORS
from core.llm_engine import LlamaEngine
from core.pdf_generator import EvidencePacketGenerator
from core.reconciler import Reconciler
from core.rules import get_requirement_specs
from data.sample_scenarios import SCENARIOS

TODAY = date(2026, 11, 3)


def spec_status(r, spec_id):
    return next((e for e in r["evidence_checklist"] if e.get("spec_id") == spec_id), None)


def file_item(doc_type, **details):
    return {"present": True, "filename": f"{doc_type}.pdf", "sha256": "a" * 64,
            "verified_by": "Tester", "details": details}


class TestPhase3EvidenceMapping(unittest.TestCase):

    # ------------------------------------------------------------- Amex C08
    def test_01_c08_pos_slip_is_decisive(self):
        s = SCENARIOS["amex_partial_c08"]
        bare = Reconciler.reconcile(s["notice"], s["folio"], {}, today=TODAY)
        self.assertEqual(spec_status(bare, "pos_slips_per_item")["validation"], "missing")
        self.assertIn("pos_slips_per_item", [e["spec_id"] for e in bare["evidence_checklist"]])
        self.assertFalse(bare["evidence_readiness"]["submittable"])

        full = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
        entry = spec_status(full, "pos_slips_per_item")
        self.assertEqual(entry["validation"], "satisfied")
        self.assertGreater(full["completeness_score"], bare["completeness_score"])

    def test_02_c08_wrong_amount_slip_does_not_satisfy(self):
        s = SCENARIOS["amex_partial_c08"]
        docs = {"pos_signed_slips": file_item("pos_signed_slips", slips=[{"reference": "POS-9999", "amount": 40.0}])}
        r = Reconciler.reconcile(s["notice"], s["folio"], docs, today=TODAY)
        entry = spec_status(r, "pos_slips_per_item")
        self.assertEqual(entry["validation"], "weak")
        self.assertIn("none matches", entry["validation_detail"])

    def test_03_c08_partial_slip_coverage_names_uncovered(self):
        s = SCENARIOS["amex_partial_c08"]
        docs = {"pos_signed_slips": file_item("pos_signed_slips", slips=[{"reference": "POS-4102", "amount": 185.0}])}
        r = Reconciler.reconcile(s["notice"], s["folio"], docs, today=TODAY)
        entry = spec_status(r, "pos_slips_per_item")
        self.assertEqual(entry["validation"], "weak")
        self.assertIn("1 of 2", entry["validation_detail"])
        self.assertIn("Valet", entry["validation_detail"])

    # ------------------------------------------------------------ Visa 10.4
    def test_04_visa104_id_alone_is_not_physical_presence(self):
        s = SCENARIOS["visa_fraud_10_4"]
        r = Reconciler.reconcile(s["notice"], s["folio"], {"id_verification_log": True}, today=TODAY)
        self.assertEqual(spec_status(r, "keycard")["validation"], "missing")
        self.assertFalse(r["evidence_readiness"]["submittable"])

    def test_05_visa104_avs_no_match_is_adverse(self):
        s = SCENARIOS["visa_fraud_10_4"]
        folio = {**s["folio"], "avs_result": "N - no match"}
        r = Reconciler.reconcile(s["notice"], folio, s["supporting_docs"], today=TODAY)
        self.assertEqual(spec_status(r, "avs_cvv")["validation"], "adverse")
        self.assertIn("ADVERSE_EVIDENCE", [d["type"] for d in r["discrepancies"]])

    def test_06_visa104_full_chain_submittable(self):
        s = SCENARIOS["visa_fraud_10_4"]
        r = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
        self.assertTrue(r["evidence_readiness"]["submittable"], r["evidence_readiness"])
        self.assertEqual(spec_status(r, "avs_cvv")["validation"], "satisfied")
        self.assertEqual(spec_status(r, "booking_confirmation")["validation"], "satisfied")

    # ------------------------------------------------------------- MC 4853
    def test_07_mc4853_unresolved_complaints_are_adverse(self):
        s = SCENARIOS["mc_cancellation_4853"]
        docs = {"guest_service_log": file_item("guest_service_log", unresolved_complaints=2)}
        r = Reconciler.reconcile(s["notice"], s["folio"], docs, today=TODAY)
        self.assertEqual(spec_status(r, "service_log")["validation"], "adverse")

        clean = {"guest_service_log": file_item("guest_service_log", unresolved_complaints=0),
                 "cancellation_policy_acceptance": file_item("cancellation_policy_acceptance",
                                                             accepted_at="2026-09-20 09:14 UTC", policy_text="Non-refundable.")}
        r2 = Reconciler.reconcile(s["notice"], s["folio"], clean, today=TODAY)
        self.assertEqual(spec_status(r2, "service_log")["validation"], "satisfied")
        self.assertEqual(spec_status(r2, "policy")["validation"], "satisfied")

    # ------------------------------------------------------------- Visa 13.1
    def test_08_visa131_branching_by_stay_status(self):
        s = SCENARIOS["visa_fraud_10_4"]
        notice = {**s["notice"], "reason_code": "13.1"}
        occupied = Reconciler.reconcile(notice, s["folio"], s["supporting_docs"], today=TODAY)
        occ_ids = [e["spec_id"] for e in occupied["evidence_checklist"]]
        self.assertIn("keycard", occ_ids)
        self.assertNotIn("policy_noshow", occ_ids)

        noshow_folio = {**s["folio"], "stay_status": "no_show"}
        noshow = Reconciler.reconcile(notice, noshow_folio, s["supporting_docs"], today=TODAY)
        ns_ids = [e["spec_id"] for e in noshow["evidence_checklist"]]
        self.assertIn("policy_noshow", ns_ids)
        self.assertNotIn("keycard", ns_ids)

    # ------------------------------------------------------- mapping quality
    def test_09_unknown_code_generic_mapping_labelled(self):
        s = SCENARIOS["visa_fraud_10_4"]
        notice = {**s["notice"], "reason_code": "ZZ9"}
        r = Reconciler.reconcile(notice, s["folio"], {}, today=TODAY)
        self.assertFalse(r["mapping_curated"])
        self.assertIn("GENERIC_EVIDENCE_MAPPING", [d["type"] for d in r["discrepancies"]])

    def test_10_all_registry_codes_have_curated_specs(self):
        from core.rules import DISPUTE_REASON_CODES
        for key, rule in DISPUTE_REASON_CODES.items():
            specs, curated = get_requirement_specs(rule["network"], rule["code"])
            self.assertTrue(curated, f"{key} has no curated spec")
            self.assertTrue(specs, f"{key} has empty specs")

    def test_11_validators_directly(self):
        base = {"notice": {}, "folio": {}, "evidence": {}, "item": None, "disputed_items": [], "proofs": [], "recon": {}}
        status, _ = VALIDATORS["avs_cvv_match"]({**base, "folio": {"avs_result": "Y - full match"}})
        self.assertEqual(status, "satisfied")
        status, _ = VALIDATORS["avs_cvv_match"]({**base, "folio": {"avs_result": "N - no match"}})
        self.assertEqual(status, "adverse")
        status, _ = VALIDATORS["three_ds_authenticated"]({**base, "folio": {"three_ds_status": "not_authenticated"}})
        self.assertEqual(status, "adverse")
        status, _ = VALIDATORS["no_unresolved_complaints"](
            {**base, "item": {"present": True, "details": {"unresolved_complaints": 0}}})
        self.assertEqual(status, "satisfied")

    def test_12_semantic_exhibits_and_pdf(self):
        s = SCENARIOS["amex_partial_c08"]
        r = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
        labels = " | ".join(e["label"] for e in r["exhibits"])
        self.assertIn("POS-4102", labels)
        rebuttal = LlamaEngine(provider="mock").draft_rebuttal(s["notice"], s["folio"], r)
        pdf_bytes = EvidencePacketGenerator.generate_packet(
            s["notice"], s["folio"], r, rebuttal,
            approved_by="Test Manager", approved_at="2026-11-03 12:00 UTC",
            policy_text="Advance purchase non-refundable.",
        )
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 3)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Exhibit", full_text)

    def test_13_refund_receipt_validator(self):
        s = SCENARIOS["visa_refund_issued_13_6"]
        r = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
        self.assertEqual(spec_status(r, "refund_receipt")["validation"], "satisfied")
        bare = Reconciler.reconcile(s["notice"], s["folio"], {}, today=TODAY)
        self.assertEqual(spec_status(bare, "refund_receipt")["validation"], "missing")
        self.assertFalse(bare["evidence_readiness"]["submittable"])


if __name__ == "__main__":
    unittest.main()
