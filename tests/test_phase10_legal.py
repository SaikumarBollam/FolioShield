"""
Phase 10 (Court / Legal Track) Tests for FolioShield.

  * Damages math: debited + fees − recovered = net loss, components sourced.
  * Affidavit TEMPLATE: banner, exhibit hashes from manifest, notary jurat
    blanks, affiant fields — valid PDF, never presented as executed.
  * Witness declaration: chronology facts for linked events only.
  * Demand letter: net-loss amount, pay-by date, certified-mail block.
  * Fraud report: Who/What/When/Where/How-much + preservation checklist.
  * Court validator: provenance/extraction/witness/demand/damages rules.
  * Court bundle ZIP contents; legal registry persistence; SDK parity.
"""

import io
import tempfile
import unittest
import zipfile

import pypdf

from core.chronology import build_chronology
from core.client import FolioShield
from core.legal import (LegalRegistry, build_court_bundle, build_fraud_report, compute_damages,
                        generate_business_records_affidavit, generate_demand_letter,
                        generate_witness_declaration, validate_court_bundle)
from core.models import LegalFilingRecord, WitnessRecord
from core.reconciler import Reconciler
from data.sample_scenarios import SCENARIOS
from datetime import date

TODAY = date(2026, 11, 3)


def pdf_text(data: bytes) -> str:
    reader = pypdf.PdfReader(io.BytesIO(data))
    return "\n".join(p.extract_text() or "" for p in reader.pages)


class TestPhase10LegalTrack(unittest.TestCase):

    def setUp(self):
        self.s = SCENARIOS["visa_fraud_10_4"]
        self.recon = Reconciler.reconcile(self.s["notice"], self.s["folio"], self.s["supporting_docs"], today=TODAY)

    def test_01_damages_math(self):
        damages = compute_damages(self.s["notice"], self.s["folio"],
                                  outcomes=[{"amount_recovered": 0.0}],
                                  arbitration=[{"action": "lost", "fee_paid_or_liable": 500.0}],
                                  chargeback_fee=25.0)
        self.assertEqual(damages["amount_disputed_debited"], 1280.50)
        self.assertEqual(damages["arbitration_fees"], 500.0)
        self.assertEqual(damages["net_loss"], round(1280.50 + 25.0 + 500.0, 2))

        won_back = compute_damages(self.s["notice"], self.s["folio"],
                                   outcomes=[{"amount_recovered": 1280.50}])
        self.assertEqual(won_back["net_loss"], 0.0)

    def test_02_affidavit_template(self):
        manifest = {"files": [{"filename": "reg_card.pdf", "sha256": "a" * 64, "action": "evidence_file_collected"}],
                    "chain_head": {"head_hash": "b" * 64, "event_count": 5}}
        pdf = generate_business_records_affidavit(self.s["notice"], self.s["folio"], manifest,
                                                  affiant={"name": "Jamie Rivera", "title": "Front Office Manager"})
        text = pdf_text(pdf)
        self.assertIn("TEMPLATE", text)
        self.assertIn("BUSINESS RECORDS AFFIDAVIT", text)
        self.assertIn("Jamie Rivera", text)
        self.assertIn("NOTARY JURAT", text)
        self.assertIn("a" * 24, text.replace("\n", ""))  # exhibit hash rendered (truncated display)
        self.assertIn("penalty of perjury", text)

    def test_03_witness_declaration_facts(self):
        chrono = build_chronology(self.s["notice"], self.s["folio"],
                                  {i["doc_type"]: i for i in self.recon["evidence_items"]}, self.recon)
        witness = WitnessRecord(name="Sam Chen", role="Front Desk Agent",
                                linked_events=["check_in", "key_issued"])
        pdf = generate_witness_declaration(witness, self.s["notice"], self.s["folio"], chrono["events"])
        text = pdf_text(pdf)
        self.assertIn("Sam Chen", text)
        self.assertIn("checked in", text)
        self.assertIn("TEMPLATE", text)

    def test_04_demand_letter(self):
        damages = compute_damages(self.s["notice"], self.s["folio"])
        pdf = generate_demand_letter(self.s["notice"], self.s["folio"], damages, "December 15, 2026")
        text = pdf_text(pdf)
        self.assertIn("CERTIFIED MAIL", text)
        self.assertIn("December 15, 2026", text)
        self.assertIn("$1,280.50", text)

    def test_05_fraud_report_five_ws(self):
        chrono = build_chronology(self.s["notice"], self.s["folio"],
                                  {i["doc_type"]: i for i in self.recon["evidence_items"]}, self.recon)
        damages = compute_damages(self.s["notice"], self.s["folio"])
        report = build_fraud_report(self.s["notice"], self.s["folio"], damages, chrono["events"],
                                    suspect={"description": "ID name mismatch"})
        for key in ("who", "what", "when", "where", "how_much"):
            self.assertIn(key, report)
        self.assertEqual(report["who"]["registered_guest"], "Jonathan C. Davis")
        self.assertEqual(report["how_much"]["net_loss"], 1280.50)
        self.assertTrue(any("CCTV" in item for item in report["preservation_checklist"]))

    def test_06_court_validator(self):
        damages = compute_damages(self.s["notice"], self.s["folio"])
        bare = validate_court_bundle([], [], [], damages)
        failed = {c["rule"] for c in bare["checks"] if not c["ok"]}
        self.assertIn("reg_card_provenance", failed)
        self.assertIn("witness_assigned", failed)
        self.assertIn("demand_sent", failed)

        items = [
            {"doc_type": "signed_registration_card", "present": True, "original_type": "wet_original"},
            {"doc_type": "keycard_lock_audit", "present": True, "extracted_by": "Sam Chen",
             "extraction_method": "Onity export, room+date filter"},
        ]
        filings = [{"kind": "demand_letter", "status": "sent", "sent_at": "2026-11-20"}]
        good = validate_court_bundle(items, [{"name": "Sam Chen"}], filings, damages)
        self.assertTrue(good["ok"], good["checks"])

    def test_07_court_bundle_and_registry(self):
        manifest = {"files": [], "chain_head": {"head_hash": "c" * 64, "event_count": 2}}
        damages = compute_damages(self.s["notice"], self.s["folio"])
        affidavit = generate_business_records_affidavit(self.s["notice"], self.s["folio"], manifest)
        zip_bytes, info = build_court_bundle(
            self.s["notice"], self.s["folio"], b"%PDF-packet", {"A": b"folio-bytes"},
            {"Business_Records_Affidavit_TEMPLATE.pdf": affidavit}, manifest, damages)
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = zf.namelist()
            self.assertIn("00_bank_packet.pdf", names)
            self.assertIn("damages_statement.json", names)
            self.assertIn("custody_manifest.json", names)
            self.assertIn("FILING_CHECKLIST.txt", names)
            self.assertTrue(any("Affidavit" in n for n in names))

        with tempfile.TemporaryDirectory() as tmp:
            registry = LegalRegistry(root=tmp)
            registry.add_witness("C-1", WitnessRecord(name="Sam Chen"))
            registry.record_filing("C-1", LegalFilingRecord(case_id="C-1", kind="police_report",
                                                           status="filed", report_or_case_number="PD-2026-991"))
            data = registry.load("C-1")
            self.assertEqual(data["witnesses"][0]["name"], "Sam Chen")
            self.assertEqual(data["filings"][0]["report_or_case_number"], "PD-2026-991")

    def test_08_sdk_parity(self):
        fs = FolioShield()
        damages = fs.compute_damages(self.s["notice"], self.s["folio"], chargeback_fee=15.0)
        self.assertEqual(damages["net_loss"], round(1280.50 + 15.0, 2))
        pdf = fs.generate_affidavit(self.s["notice"], self.s["folio"], {"files": [], "chain_head": {}},
                                    affiant={"name": "Jamie Rivera", "title": "Manager"})
        self.assertTrue(pdf.startswith(b"%PDF"))


if __name__ == "__main__":
    unittest.main()
