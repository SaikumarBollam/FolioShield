"""
Phase 1 (Collection) Tests for FolioShield.

Validates the collection completion work:
  * Cardholder claim statement / dispute stage / descriptor extraction
  * ARN 23-digit validation + collection gaps
  * Folio address, rate, category, reference, AVS/3DS/entry-mode extraction
  * File-backed EvidenceItem scoring (collected > attested > missing)
  * Legacy checkbox-key compatibility
  * OTA third-party payer, refund-already-issued, no-show, CE 3.0 detection
  * Per-line-item disputed scoping for partial disputes
  * OCR fallback hook for scanned notices
  * Expanded reason-code knowledge base
  * PDF packet carries ARN/MID/claim + evidence provenance (still 3 pages)
"""

import io
import unittest

import pypdf

from core.extractor import DocumentExtractor
from core.llm_engine import LlamaEngine
from core.models import EvidenceItem, FolioData, NoticeData, normalize_supporting_docs
from core.pdf_generator import EvidencePacketGenerator
from core.reconciler import Reconciler
from core.rules import SUPPORTING_DOC_TYPES, lookup_reason_code
from data.sample_scenarios import SCENARIOS


NOTICE_TEXT = """VISA CHARGEBACK DISPUTE NOTIFICATION
Processor: Chase Paymentech
Acquirer Reference Number: 24492156291002918274019
Case Number: V-DISP-89214-X
Merchant ID: MID-884120937
Descriptor: GRAND HORIZON RESORT MIAMI
Dispute Date: 10/24/2026
Response Due Date: 11/07/2026
Cardholder Name: Jonathan C. Davis
Account Number: ************4821
Dispute Reason Code: 10.4
Dispute Reason: Other Fraud - Card-Absent Environment
Transaction Date: 10/10/2026
Disputed Amount: $1,280.50 USD
Cardholder Statement: 'I did not authorize or participate in this lodging transaction.'
"""

FOLIO_TEXT = """GRAND HORIZON RESORT & SUITES
Address: 100 Ocean Avenue, Miami Beach, FL 33139
Guest Name: Jonathan C. Davis
Folio Number: FOL-2026-9812
Confirmation Number: GH-884120
Room Number: 412
Arrival Date: 10/10/2026
Departure Date: 10/13/2026
Rate per Night: $320.00
Rate Plan: Best Available Rate
Booking Source: Hotel Website
AVS Result: Y - full match
CVV Result: Match
Entry Mode: Chip
Auth Code: AP98231
10/10/2026 Room Accommodation - Deluxe King 320.00
10/10/2026 Occupancy Tax 46.40
10/11/2026 Ocean Grill Dining POS-9812 87.70
10/13/2026 Visa Payment 1280.50
Total Charges: $454.10
"""


class TestPhase1Collection(unittest.TestCase):

    def test_01_notice_claim_and_identity_extraction(self):
        """Claim statement, stage, processor, descriptor, MID and ARN are collected."""
        parsed = DocumentExtractor.parse_dispute_notice(NOTICE_TEXT)
        self.assertEqual(parsed["claim_statement"], "I did not authorize or participate in this lodging transaction.")
        self.assertEqual(parsed["dispute_stage"], "chargeback")
        self.assertEqual(parsed["processor"], "Chase Paymentech")
        self.assertEqual(parsed["statement_descriptor"], "GRAND HORIZON RESORT MIAMI")
        self.assertEqual(parsed["merchant_id"], "MID-884120937")
        self.assertEqual(parsed["arn"], "24492156291002918274019")
        self.assertEqual(len(parsed["arn"]), 23)

    def test_02_folio_collection_extraction(self):
        """Address, rate, confirmation, AVS/CVV, entry mode, categories, references."""
        parsed = DocumentExtractor.parse_folio_pdf(FOLIO_TEXT)
        self.assertEqual(parsed["hotel_address"], "100 Ocean Avenue, Miami Beach, FL 33139")
        self.assertEqual(parsed["rate_per_night"], 320.00)
        self.assertEqual(parsed["confirmation_number"], "GH-884120")
        self.assertEqual(parsed["folio_number"], "FOL-2026-9812")
        self.assertTrue(parsed["avs_result"].startswith("Y"))
        self.assertEqual(parsed["cvv_result"], "Match")
        self.assertEqual(parsed["entry_mode"], "chip")
        self.assertEqual(parsed["booking_channel"], "direct_web")
        categories = {i["description"]: i["category"] for i in parsed["line_items"]}
        self.assertEqual(categories["Room Accommodation - Deluxe King"], "Room")
        self.assertEqual(categories["Ocean Grill Dining POS-9812"], "Dining")

    def test_03_csv_reference_and_category_preserved(self):
        """CSV voucher/reference column survives parsing (was silently dropped)."""
        csv_bytes = (
            b"Date,Description,Charge,Credit,Reference\n"
            b"10/11/2026,Ocean Grill Dining (Signed Slip),87.7,0.0,POS-9812\n"
            b"10/13/2026,Visa Payment Auth AP98231,0.0,87.7,AUTH-AP98231\n"
        )
        parsed = DocumentExtractor.parse_folio_csv(csv_bytes)
        dining = parsed["line_items"][0]
        self.assertEqual(dining["reference"], "POS-9812")
        self.assertEqual(dining["category"], "Dining")
        self.assertEqual(parsed["balance"], 0.0)

    def test_04_collection_gaps_flag_missing_identity(self):
        """Missing Case ID / ARN / claim / MID surface as collection gaps."""
        recon = Reconciler.reconcile({"disputed_amount": 100.0}, {"total_charges": 100.0, "total_payments": 100.0})
        fields = {g["field"] for g in recon["collection_gaps"]}
        self.assertIn("case_id", fields)
        self.assertIn("arn", fields)
        self.assertIn("claim_statement", fields)
        self.assertIn("merchant_id", fields)
        severities = {g["field"]: g["severity"] for g in recon["collection_gaps"]}
        self.assertEqual(severities["case_id"], "critical")
        self.assertEqual(severities["arn"], "critical")

    def test_05_nonstandard_arn_flagged(self):
        """A short ARN is collected but flagged as non-standard."""
        notice = {"case_id": "C-1", "arn": "12345", "disputed_amount": 10.0}
        folio = {"total_charges": 10.0, "total_payments": 10.0, "folio_number": "F-1", "guest_name": "G", "check_in": "2026-10-10"}
        recon = Reconciler.reconcile(notice, folio)
        arn_gaps = [g for g in recon["collection_gaps"] if g["field"] == "arn"]
        self.assertEqual(len(arn_gaps), 1)
        self.assertEqual(arn_gaps[0]["severity"], "warning")

    def test_06_file_backed_evidence_scores_higher(self):
        """Collected files (full weight) beat attestations (0.6x) beat missing (0)."""
        scenario = SCENARIOS["visa_fraud_10_4"]
        attested = {key: True for key in SUPPORTING_DOC_TYPES}
        collected = {
            key: EvidenceItem(doc_type=key, present=True, filename=f"{key}.pdf", sha256="a" * 64).to_dict()
            for key in SUPPORTING_DOC_TYPES
        }
        score_attested = Reconciler.reconcile(scenario["notice"], scenario["folio"], attested)["completeness_score"]
        score_collected = Reconciler.reconcile(scenario["notice"], scenario["folio"], collected)["completeness_score"]
        score_none = Reconciler.reconcile(scenario["notice"], scenario["folio"], {})["completeness_score"]
        self.assertGreater(score_collected, score_attested)
        self.assertGreater(score_attested, score_none)
        # Phase 3: validators require probative details (entry windows, slip
        # refs), so bare files without details land at 'weak' for some specs —
        # collected-with-details (scenario docs) is the 100%-style benchmark.
        scenario_score = Reconciler.reconcile(
            scenario["notice"], scenario["folio"], scenario["supporting_docs"])["completeness_score"]
        self.assertGreaterEqual(scenario_score, score_collected)

    def test_07_legacy_checkbox_keys_still_work(self):
        """Legacy bundled keys (emv_chip_or_avs_auth etc.) map to modern doc types."""
        scenario = SCENARIOS["visa_fraud_10_4"]
        legacy = {
            "signed_registration_card": True,
            "emv_chip_or_avs_auth": True,
            "cancellation_policy_acknowledged": True,
            "keycard_or_wifi_audit": True,
            "id_verification_copy": True,
            "booking_confirmation": True,
            "guest_service_log": True,
        }
        recon = Reconciler.reconcile(scenario["notice"], scenario["folio"], legacy)
        self.assertTrue(recon["supporting_docs"]["emv_terminal_receipt"])
        self.assertTrue(recon["supporting_docs"]["avs_cvv_result"])
        self.assertTrue(recon["supporting_docs"]["cancellation_policy_acceptance"])
        self.assertTrue(recon["supporting_docs"]["keycard_lock_audit"])
        self.assertTrue(recon["supporting_docs"]["id_verification_log"])
        # Phase 3 criticality-weighted scoring: legacy attestations satisfy
        # presence, but validators mark detail-less items weak — score lands
        # in the moderate band rather than the old flat 68.
        self.assertGreaterEqual(recon["completeness_score"], 40)
        self.assertLess(recon["completeness_score"], 85)

    def test_08_ota_third_party_payer_not_name_mismatch(self):
        """OTA VCC: cardholder != guest is informational, not a mismatch warning."""
        scenario = SCENARIOS["ota_virtual_card_10_4"]
        recon = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"])
        types = [d["type"] for d in recon["discrepancies"]]
        self.assertIn("THIRD_PARTY_PAYER", types)
        self.assertNotIn("NAME_MISMATCH", types)
        self.assertTrue(recon["is_third_party_payer"])

    def test_09_refund_already_issued(self):
        """Refund on folio is highlighted; missing receipt is flagged."""
        scenario = SCENARIOS["visa_refund_issued_13_6"]
        recon = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"])
        self.assertTrue(any("Refund of $412.00 already issued" in h for h in recon["audit_highlights"]))
        self.assertNotIn("REFUND_RECEIPT_MISSING", [d["type"] for d in recon["discrepancies"]])

        no_receipt = Reconciler.reconcile(scenario["notice"], scenario["folio"], {})
        self.assertIn("REFUND_RECEIPT_MISSING", [d["type"] for d in no_receipt["discrepancies"]])

    def test_10_partial_dispute_line_item_scope(self):
        """Staff-marked disputed items define the partial-dispute scope."""
        scenario = SCENARIOS["amex_partial_c08"]
        recon = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"])
        self.assertTrue(recon["is_partial"])
        disputed_total = sum(i["amount"] for i in recon["disputed_line_items"])
        self.assertEqual(disputed_total, 245.00)

    def test_11_ce30_readiness_flag(self):
        """Visa 10.4 with email + confirmation reports CE 3.0 data readiness."""
        scenario = SCENARIOS["visa_fraud_10_4"]
        recon = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"])
        self.assertTrue(recon["ce30_ready"])

        bare = Reconciler.reconcile(scenario["notice"], {"total_charges": 10.0}, {})
        self.assertFalse(bare["ce30_ready"])

    def test_12_expanded_reason_codes(self):
        """Newly covered hotel reason codes resolve in the knowledge base."""
        for network, code in [("Visa", "13.7"), ("Visa", "12.6"), ("Mastercard", "4859"),
                              ("Mastercard", "4871"), ("American Express", "C18"),
                              ("American Express", "P08"), ("Discover", "RG")]:
            self.assertIsNotNone(lookup_reason_code(network, code), f"{network} {code}")
        self.assertEqual(len(SUPPORTING_DOC_TYPES), 20)  # 14 bank-track + 6 Phase-10 legal-track

    def test_13_ocr_fallback_hook(self):
        """Scanned-PDF path uses the OCR provider text when supplied."""
        text = DocumentExtractor.extract_text_with_ocr_fallback(
            b"%PDF-1.4 scanned-image-only",
            ocr_text_provider=lambda _b: NOTICE_TEXT,
        )
        parsed = DocumentExtractor.parse_dispute_notice(text)
        self.assertEqual(parsed["case_id"], "V-DISP-89214-X")
        self.assertIsNotNone(parsed["claim_statement"])

    def test_14_rebuttal_answers_actual_claim(self):
        """Offline rebuttal quotes the claim and carries ARN/MID."""
        scenario = SCENARIOS["visa_fraud_10_4"]
        recon = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"])
        rebuttal = LlamaEngine(provider="mock").draft_rebuttal(scenario["notice"], scenario["folio"], recon)
        self.assertIn("I did not authorize or participate", rebuttal)
        self.assertIn("24492156291002918274019", rebuttal)
        self.assertIn("MID-884120937", rebuttal)

    def test_15_pdf_packet_identity_and_provenance(self):
        """Packet stays 3 pages and renders ARN/MID/claim + file provenance."""
        scenario = SCENARIOS["visa_fraud_10_4"]
        recon = Reconciler.reconcile(scenario["notice"], scenario["folio"], scenario["supporting_docs"])
        rebuttal = LlamaEngine(provider="mock").draft_rebuttal(scenario["notice"], scenario["folio"], recon)
        pdf_bytes = EvidencePacketGenerator.generate_packet(
            scenario["notice"], scenario["folio"], recon, rebuttal,
            approved_by="Test Manager", approved_at="2026-11-03 12:00 UTC",
            policy_text="Free cancellation until 48 hours before arrival.",
        )
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 3)
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
        self.assertIn("24492156291002918274019", full_text)
        self.assertIn("MID-884120937", full_text)
        self.assertIn("onity_lock_audit_room412.csv", full_text)

    def test_16_models_roundtrip_new_fields(self):
        """NoticeData/FolioData/EvidenceItem round-trip the Phase 1 fields."""
        notice = NoticeData.from_dict(SCENARIOS["ota_virtual_card_10_4"]["notice"])
        self.assertEqual(notice.claim_statement, "Virtual card was charged outside the agreed booking terms.")
        folio = FolioData.from_dict(SCENARIOS["ota_virtual_card_10_4"]["folio"])
        self.assertEqual(folio.booking_channel, "ota")
        self.assertEqual(folio.payer_relationship, "OTA virtual card")
        normalized = normalize_supporting_docs({"pos_signed_slips": True})
        self.assertTrue(normalized["pos_signed_slips"]["present"])
        self.assertIsNone(normalized["pos_signed_slips"]["filename"])


if __name__ == "__main__":
    unittest.main()
