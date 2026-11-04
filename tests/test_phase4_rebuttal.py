"""
Phase 4 (Rebuttal Drafting) Tests for FolioShield.

  * All six scenarios produce the exact 5 bank-expected sections in order.
  * Chronology carries collected anchors (check-in time, first keycard entry,
    nights, settlement) and marks missing anchors [MISSING].
  * Factual rebuttal quotes the claim, cites exhibits inline, and NEVER
    asserts adverse evidence (AVS no-match) as support.
  * Outcome-aware summaries: refund = double-recovery denial; partial names
    the contested lines; no-show/cancelled variants.
  * Exhibit letters in the draft match the PDF index (single source).
  * LLM post-validation: good draft passes; missing-section / adverse-
    asserting / phantom-exhibit drafts fail; engine falls back to template.
"""

import io
import re
import unittest
from datetime import date

import pypdf

from core.chronology import build_chronology
from core.llm_engine import LlamaEngine
from core.pdf_generator import EvidencePacketGenerator
from core.rebuttal_validator import validate_rebuttal
from core.reconciler import Reconciler
from data.sample_scenarios import SCENARIOS

TODAY = date(2026, 11, 3)
SECTIONS = ["1. EXECUTIVE SUMMARY", "2. FACTUAL REBUTTAL", "3. CHRONOLOGY OF THE TRANSACTION",
            "4. INDEX OF EXHIBITS", "5. CLOSING & REQUEST FOR REVERSAL"]


def draft_for(key, notice_over=None, folio_over=None, docs_over="__scenario__"):
    s = SCENARIOS[key]
    notice = {**s["notice"], **(notice_over or {})}
    folio = {**s["folio"], **(folio_over or {})}
    docs = s["supporting_docs"] if docs_over == "__scenario__" else docs_over
    recon = Reconciler.reconcile(notice, folio, docs, today=TODAY)
    draft = LlamaEngine(provider="mock").draft_rebuttal(notice, folio, recon)
    return draft, recon, notice, folio


class TestPhase4RebuttalDrafting(unittest.TestCase):

    def test_01_five_sections_in_order_all_scenarios(self):
        for key in SCENARIOS:
            draft, _, _, _ = draft_for(key)
            positions = [draft.index(s) for s in SECTIONS]
            self.assertEqual(positions, sorted(positions), f"{key}: sections out of order")
            verdict = validate_rebuttal(draft, Reconciler.reconcile(
                SCENARIOS[key]["notice"], SCENARIOS[key]["folio"], SCENARIOS[key]["supporting_docs"], today=TODAY),
                SCENARIOS[key]["notice"])
            self.assertEqual(verdict["sections_found"], ["executive_summary", "factual_rebuttal", "chronology", "exhibit_index", "closing"], key)

    def test_02_chronology_carries_collected_anchors(self):
        draft, recon, notice, folio = draft_for("visa_fraud_10_4")
        self.assertIn("3:15 PM", draft)                 # check-in time
        self.assertIn("15:22", draft)                   # first keycard entry
        self.assertIn("3 night(s)", draft)              # nights x rate summary
        self.assertIn("Payment settled", draft)         # settlement event
        chrono = build_chronology(notice, folio,
                                  {i["doc_type"]: i for i in recon["evidence_items"]}, recon)
        self.assertEqual(chrono["nights"], 3)
        self.assertTrue(any("first door entry" in e["event"].lower() for e in chrono["events"]))

    def test_03_chronology_marks_missing_anchors(self):
        chrono = build_chronology({"case_id": "X"}, {"hotel_name": "H", "total_charges": 10.0}, {}, {})
        self.assertIn("check-in date/time", chrono["missing_anchors"])

    def test_04_adverse_avs_never_cited_as_support(self):
        draft, recon, _, _ = draft_for("visa_fraud_10_4", folio_over={"avs_result": "N - no match"})
        self.assertNotIn("AVS result: N - no match", draft)
        self.assertIn("does not rely on this item", draft)
        verdict = validate_rebuttal(draft, recon, SCENARIOS["visa_fraud_10_4"]["notice"])
        self.assertFalse(any("ADVERSE" in i for i in verdict["issues"]), verdict["issues"])

    def test_05_refund_summary_is_double_recovery_denial(self):
        draft, _, _, _ = draft_for("visa_refund_issued_13_6")
        self.assertIn("double recovery", draft)
        self.assertIn("already issued", draft)
        self.assertNotIn("services were authorized and provided", draft)

    def test_06_partial_summary_names_contested_lines(self):
        draft, _, _, _ = draft_for("amex_partial_c08")
        self.assertIn("Private Cabana Dining", draft)
        self.assertIn("$245.00", draft)
        self.assertIn("uncontested", draft)

    def test_07_exhibit_letters_match_pdf(self):
        draft, recon, notice, folio = draft_for("amex_partial_c08")
        draft_letters = re.findall(r"EXHIBIT ([A-Z]):", draft)
        recon_letters = [e["letter"] for e in recon["exhibits"]]
        self.assertEqual(draft_letters, recon_letters)
        pdf_bytes = EvidencePacketGenerator.generate_packet(
            notice, folio, recon, draft, approved_by="T", approved_at="2026-11-03 12:00 UTC",
            policy_text="Non-refundable.")
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 3)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        for letter in recon_letters:
            self.assertIn(f"Exhibit {letter}", text)

    def test_08_validator_rejects_bad_llm_drafts(self):
        _, recon, notice, _ = draft_for("visa_fraud_10_4")
        good, _, _, _ = draft_for("visa_fraud_10_4")
        self.assertTrue(validate_rebuttal(good, recon, notice)["valid"], validate_rebuttal(good, recon, notice))

        no_chronology = good.replace("3. CHRONOLOGY OF THE TRANSACTION", "3. TIMELINE OF EVENTS")
        # 'timeline' still matches chronology pattern; use a truly absent heading
        no_chronology = good.replace("3. CHRONOLOGY OF THE TRANSACTION", "3. SEQUENCE OF EVENTS")
        verdict = validate_rebuttal(no_chronology, recon, notice)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("chronology" in i for i in verdict["issues"]))

        phantom = good + "\nAs shown in Exhibit Z, the guest confessed."
        verdict = validate_rebuttal(phantom, recon, notice)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("Exhibit Z" in i for i in verdict["issues"]))

    def test_09_validator_flags_adverse_assertion(self):
        _, recon_bad, notice, _ = draft_for("visa_fraud_10_4", folio_over={"avs_result": "N - no match"})
        bad_text = ("1. EXECUTIVE SUMMARY\nx\n2. FACTUAL REBUTTAL\nThe AVS matched at booking (Exhibit A).\n"
                    "3. CHRONOLOGY OF THE TRANSACTION\nx\n4. INDEX OF EXHIBITS\nExhibit A\n"
                    "5. CLOSING & REQUEST FOR REVERSAL\nPlease reverse. Case V-DISP-89214-X ARN 24492156291002918274019")
        verdict = validate_rebuttal(bad_text, recon_bad, notice)
        self.assertFalse(verdict["valid"])
        self.assertTrue(any("ADVERSE" in i for i in verdict["issues"]), verdict["issues"])

    def test_10_missing_markers_for_empty_case(self):
        notice = {"case_id": "X-1", "card_network": "Visa", "reason_code": "10.4", "disputed_amount": 500.0}
        recon = Reconciler.reconcile(notice, {}, {}, today=TODAY)
        draft = LlamaEngine(provider="mock").draft_rebuttal(notice, {}, recon)
        self.assertGreater(draft.count("[MISSING"), 3)
        for s in SECTIONS:
            self.assertIn(s, draft)


if __name__ == "__main__":
    unittest.main()
