"""
Phase 2 (Reconciliation) Tests for FolioShield.

Every adversarial probe from the Phase 2 audit is a regression test:
  * Folio footing (Σ items vs header totals; derived totals; nights × rate)
  * Amount proof (rounding variance, made-whole, net-of-refund, original)
  * Identity normalization (masked last-4, comma/initial/hyphen names)
  * Date semantics (settlement grace, prepay, unparseable flags, business days)
  * Settlement states (settled / refunded / overpaid / open), duplicate keys
  * Partial scope verification (marked sums verified; greedy = suggested)
  * Currency mismatch, wrong-folio confidence, auth-vs-settlement variance
  * PDF proof table + UI-facing proof summary
"""

import io
import unittest
from datetime import date

import pypdf

from core.llm_engine import LlamaEngine
from core.pdf_generator import EvidencePacketGenerator
from core.reconciler import Reconciler
from data.sample_scenarios import SCENARIOS

TODAY = date(2026, 11, 3)

BASE_NOTICE = {
    "case_id": "V-1", "card_network": "Visa", "reason_code": "13.1",
    "disputed_amount": 100.00, "original_amount": 100.00,
    "cardholder_name": "Jonathan C. Davis", "card_last_4": "4821",
    "transaction_date": "2026-10-10", "response_deadline": "2026-11-20",
    "arn": "24492156291002918274019", "claim_statement": "not mine",
    "merchant_id": "MID-1", "currency": "USD",
}
BASE_FOLIO = {
    "hotel_name": "H", "folio_number": "F-1", "guest_name": "Jonathan C. Davis",
    "check_in": "2026-10-10", "check_out": "2026-10-13",
    "total_charges": 100.00, "total_payments": 100.00, "card_last_4": "4821",
    "auth_code": "A1", "merchant_id": "MID-1", "stay_status": "occupied",
    "line_items": [
        {"date": "2026-10-10", "description": "Room", "amount": 100.00, "type": "Charge", "category": "Room"},
        {"date": "2026-10-13", "description": "Visa Payment", "amount": 100.00, "type": "Credit", "category": "Payment"},
    ],
}


def recon(notice_over=None, folio_over=None, docs=None):
    n = {**BASE_NOTICE, **(notice_over or {})}
    f = {**BASE_FOLIO, **(folio_over or {})}
    return Reconciler.reconcile(n, f, docs or {}, today=TODAY)


def types(r):
    return [d["type"] for d in r["discrepancies"]]


def proof_status(r, name):
    return next((p["status"] for p in r["proofs"] if p["proof"] == name), None)


class TestPhase2Reconciliation(unittest.TestCase):

    # ------------------------------------------------------------- footing
    def test_01_footing_proven_when_items_match_headers(self):
        r = recon()
        self.assertEqual(proof_status(r, "folio_footing"), "proven")
        self.assertEqual(r["folio_footing"]["totals_source"], "header+items")

    def test_02_footing_error_when_header_disagrees_with_items(self):
        r = recon(folio_over={"total_charges": 150.0, "total_payments": 150.0})
        self.assertIn("FOLIO_FOOTING_ERROR", types(r))
        self.assertEqual(proof_status(r, "folio_footing"), "failed")
        # Effective totals still come from the header for downstream proofs
        self.assertEqual(r["folio_charges"], 150.0)

    def test_03_totals_derived_from_items_when_headers_missing(self):
        r = recon(folio_over={"total_charges": 0.0, "total_payments": 0.0})
        self.assertEqual(r["folio_charges"], 100.0)
        self.assertTrue(r["is_exact_match"])
        self.assertEqual(r["folio_footing"]["totals_source"], "derived_from_items")

    def test_04_rate_recomputation(self):
        folio = {"rate_per_night": 320.0, "total_charges": 1006.40, "total_payments": 1006.40,
                 "line_items": [
                     {"date": "2026-10-10", "description": "Room", "amount": 320.0, "type": "Charge", "category": "Room"},
                     {"date": "2026-10-11", "description": "Room", "amount": 320.0, "type": "Charge", "category": "Room"},
                     {"date": "2026-10-12", "description": "Room", "amount": 320.0, "type": "Charge", "category": "Room"},
                     {"date": "2026-10-12", "description": "Tax", "amount": 46.40, "type": "Charge", "category": "Tax"},
                     {"date": "2026-10-13", "description": "Visa Payment", "amount": 1006.40, "type": "Credit", "category": "Payment"},
                 ]}
        r = recon({"disputed_amount": 1006.40}, folio)
        self.assertEqual(proof_status(r, "rate_recomputation"), "proven")
        self.assertEqual(r["folio_footing"]["nights"], 3)

        bad = recon({"disputed_amount": 1006.40}, {**folio, "rate_per_night": 300.0})
        self.assertIn("RATE_MISMATCH", types(bad))

    # -------------------------------------------------------------- amount
    def test_05_rounding_variance_not_mismatch(self):
        r = recon(folio_over={"total_charges": 99.99, "total_payments": 99.99,
                              "line_items": [
                                  {"date": "2026-10-10", "description": "Room", "amount": 99.99, "type": "Charge", "category": "Room"},
                                  {"date": "2026-10-13", "description": "Visa Payment", "amount": 99.99, "type": "Credit", "category": "Payment"},
                              ]})
        self.assertIn("ROUNDING_VARIANCE", types(r))
        self.assertNotIn("AMOUNT_MISMATCH", types(r))
        self.assertTrue(r["is_exact_match"])

    def test_06_made_whole_when_disputed_equals_refund(self):
        r = recon({"reason_code": "13.6"}, {"refund_amount": 100.0, "refund_date": "2026-10-15"})
        self.assertTrue(any("made whole" in h for h in r["audit_highlights"]))
        self.assertEqual(proof_status(r, "amount"), "proven")

    def test_07_disputed_matches_net_of_refund(self):
        r = recon({"disputed_amount": 60.0}, {"refund_amount": 40.0, "refund_date": "2026-10-15"})
        self.assertEqual(proof_status(r, "amount"), "proven")
        self.assertTrue(any("net of the" in h for h in r["audit_highlights"]))

    def test_08_currency_mismatch_flagged(self):
        # Folio currency defaults to the notice currency; an explicit folio
        # currency that differs must be flagged.
        r = recon({"currency": "EUR"}, {"currency": "USD"})
        self.assertIn("CURRENCY_MISMATCH", types(r))
        self.assertFalse(r["currency_match"])
        same = recon({"currency": "EUR"}, {"currency": "EUR"})
        self.assertNotIn("CURRENCY_MISMATCH", types(same))
        self.assertTrue(same["currency_match"])

    # ------------------------------------------------------------ identity
    def test_09_masked_last4_normalized(self):
        r = recon({"card_last_4": "****4821"})
        self.assertNotIn("CARD_MISMATCH", types(r))
        self.assertEqual(proof_status(r, "card_last4"), "proven")
        r2 = recon({"card_last_4": "4821"}, {"card_last_4": "**** **** **** 4821"})
        self.assertEqual(proof_status(r2, "card_last4"), "proven")

    def test_10_name_token_matching(self):
        for guest in ("Davis, Jonathan C.", "Jonathan Davis", "J. Davis", "Jonathan Davis-Smith"):
            r = recon(folio_over={"guest_name": guest})
            self.assertNotIn("NAME_MISMATCH", types(r), guest)
            self.assertEqual(proof_status(r, "guest_name"), "proven", guest)
        r = recon(folio_over={"guest_name": "Someone Else"})
        self.assertIn("NAME_MISMATCH", types(r))

    def test_11_wrong_folio_confidence(self):
        r = recon({"card_last_4": "9999"}, {"guest_name": "Someone Else", "card_last_4": "1111"})
        self.assertIn("WRONG_FOLIO_SUSPECTED", types(r))
        self.assertLess(r["identity_confidence"], 40)

    # --------------------------------------------------------------- dates
    def test_12_settlement_grace_window(self):
        r = recon({"transaction_date": "2026-10-14"})  # day after checkout
        self.assertNotIn("DATE_OUTSIDE_STAY", types(r))
        self.assertEqual(r["transaction_date_class"], "settlement")
        r2 = recon({"transaction_date": "2026-10-20"})  # beyond grace
        self.assertIn("DATE_OUTSIDE_STAY", types(r2))

    def test_13_prepay_and_unparseable_dates(self):
        r = recon({"transaction_date": "2026-09-28"}, {"booking_date": "2026-09-28"})
        self.assertEqual(r["transaction_date_class"], "booking_prepay")
        r2 = recon({"transaction_date": "10/10/26 PM"})  # truly unparseable
        self.assertIn("DATE_UNPARSEABLE", types(r2))
        self.assertEqual(proof_status(r2, "transaction_date"), "unverifiable")
        r3 = recon({"response_deadline": "next Friday"})
        self.assertEqual(proof_status(r3, "deadline"), "unverifiable")

    def test_14_business_days_to_deadline(self):
        # 2026-11-03 is a Tuesday; deadline Mon 2026-11-09 -> 4 business days
        r = recon({"response_deadline": "2026-11-09"})
        self.assertEqual(r["days_to_deadline"], 6)
        self.assertEqual(r["business_days_to_deadline"], 4)

    # ---------------------------------------------------------- settlement
    def test_15_settlement_states(self):
        self.assertEqual(recon()["settlement_state"], "SETTLED")
        over = recon(folio_over={"total_payments": 120.0, "line_items": [
            {"date": "2026-10-10", "description": "Room", "amount": 100.0, "type": "Charge", "category": "Room"},
            {"date": "2026-10-13", "description": "Visa Payment", "amount": 120.0, "type": "Credit", "category": "Payment"},
        ]})
        self.assertEqual(over["settlement_state"], "OVERPAID")
        self.assertIn("OVERPAYMENT", types(over))

    def test_16_settled_then_refunded(self):
        scenario = SCENARIOS["visa_refund_issued_13_6"]
        r = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"], today=TODAY)
        self.assertEqual(r["settlement_state"], "SETTLED_THEN_REFUNDED")
        self.assertNotIn("POSSIBLE_DUPLICATE_PAYMENT", types(r))
        self.assertNotIn("OPEN_BALANCE", types(r))

    def test_17_duplicate_detection_by_reference_not_amount(self):
        # Split tender: same amount, different references -> NOT a duplicate
        split = recon(folio_over={"line_items": [
            {"date": "2026-10-10", "description": "Room", "amount": 100.0, "type": "Charge", "category": "Room"},
            {"date": "2026-10-13", "description": "Visa Payment", "amount": 50.0, "type": "Credit", "category": "Payment", "reference": "AUTH-V1"},
            {"date": "2026-10-13", "description": "Cash Payment", "amount": 50.0, "type": "Credit", "category": "Payment", "reference": "CASH-1"},
        ]})
        self.assertNotIn("POSSIBLE_DUPLICATE_PAYMENT", types(split))
        # True duplicate: same auth reference twice
        dup = recon(folio_over={"line_items": [
            {"date": "2026-10-10", "description": "Room", "amount": 100.0, "type": "Charge", "category": "Room"},
            {"date": "2026-10-13", "description": "Visa Payment (Auth: AP1)", "amount": 100.0, "type": "Credit", "category": "Payment", "reference": "AP1"},
            {"date": "2026-10-13", "description": "Visa Payment (Auth: AP1)", "amount": 100.0, "type": "Credit", "category": "Payment", "reference": "AP1"},
        ]})
        self.assertIn("POSSIBLE_DUPLICATE_PAYMENT", types(dup))

    def test_18_auth_vs_settlement_variance(self):
        ok = recon(folio_over={"auth_amount": 100.0})
        self.assertEqual(proof_status(ok, "auth_vs_settlement"), "proven")
        bad = recon(folio_over={"auth_amount": 40.0})
        self.assertIn("AUTH_SETTLEMENT_VARIANCE", types(bad))

    # --------------------------------------------------------------- scope
    def test_19_marked_scope_verified_and_mismatch_flagged(self):
        scenario = SCENARIOS["amex_partial_c08"]
        r = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"], today=TODAY)
        self.assertTrue(r["scope_verified"])
        self.assertEqual(proof_status(r, "disputed_scope"), "proven")

        wrong = {**scenario["notice"], "disputed_amount": 200.0}
        r2 = Reconciler.reconcile(wrong, scenario["folio"], scenario["supporting_docs"], today=TODAY)
        self.assertIn("DISPUTED_SCOPE_MISMATCH", types(r2))

    def test_20_greedy_scope_is_suggested_not_verified(self):
        r = recon({"disputed_amount": 50.0}, {"total_charges": 150.0, "total_payments": 150.0, "line_items": [
            {"date": "2026-10-10", "description": "Room", "amount": 100.0, "type": "Charge", "category": "Room"},
            {"date": "2026-10-11", "description": "Dining", "amount": 50.0, "type": "Charge", "category": "Dining"},
            {"date": "2026-10-13", "description": "Visa Payment", "amount": 150.0, "type": "Credit", "category": "Payment"},
        ]})
        self.assertTrue(r["scope_suggested"])
        self.assertFalse(r["scope_verified"])
        self.assertEqual(proof_status(r, "disputed_scope"), "unverifiable")

    # ------------------------------------------------------------ surfacing
    def test_21_proofs_present_for_all_scenarios(self):
        for key, scenario in SCENARIOS.items():
            r = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"], today=TODAY)
            names = {p["proof"] for p in r["proofs"]}
            for expected in ("folio_footing", "amount", "settlement", "card_last4", "guest_name", "deadline"):
                self.assertIn(expected, names, f"{key} missing {expected}")
            self.assertTrue(r["proof_summary"])

    def test_22_pdf_contains_proof_table_and_stays_3_pages(self):
        scenario = SCENARIOS["visa_fraud_10_4"]
        r = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"], today=TODAY)
        rebuttal = LlamaEngine(provider="mock").draft_rebuttal(scenario["notice"], scenario["folio"], r)
        self.assertIn("folio_footing", rebuttal)  # Phase 2 proof cited in the rebuttal
        self.assertIn("Σ charges", rebuttal)
        pdf_bytes = EvidencePacketGenerator.generate_packet(
            scenario["notice"], scenario["folio"], r, rebuttal,
            approved_by="Test Manager", approved_at="2026-11-03 12:00 UTC",
            policy_text="Free cancellation until 48 hours before arrival.",
        )
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 3)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("Mathematical Proof Summary", full_text)
        self.assertIn("Folio Footing", full_text)


if __name__ == "__main__":
    unittest.main()
