"""
Packet format tests: executive stays exactly 3 pages; complete appends an
exhibit appendix and grows the page count.
"""

import io
import unittest
from datetime import date

import pypdf

from core.client import FolioShield
from core.llm_engine import LlamaEngine
from core.pdf_generator import EvidencePacketGenerator
from core.reconciler import Reconciler
from data.sample_scenarios import SCENARIOS

TODAY = date(2026, 11, 3)


def _packet(fmt: str, exhibit_files=None):
    s = SCENARIOS["visa_fraud_10_4"]
    recon = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
    draft = LlamaEngine(provider="mock").draft_rebuttal(s["notice"], s["folio"], recon)
    fs = FolioShield()
    pdf_bytes = fs.generate_pdf_packet_hashed(
        s["notice"], s["folio"], recon, draft,
        approved_by="Test Manager (Manager)", approved_at="2026-11-03T12:00:00+00:00",
        policy_text="Free cancellation until 48 hours before arrival.",
        approval_fingerprint="f" * 64, chain_head={"head_hash": "a" * 64, "event_count": 3, "hmac_protected": False},
        packet_format=fmt, exhibit_files=exhibit_files)
    reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    return pdf_bytes, reader, text, recon


class TestPacketFormats(unittest.TestCase):

    def test_executive_remains_exactly_three_pages(self):
        _pdf, reader, text, _recon = _packet("executive")
        self.assertEqual(len(reader.pages), 3)
        self.assertNotIn("EXHIBIT APPENDIX", text)

    def test_complete_adds_appendix_pages(self):
        exhibit_files = {"A": b"folio-bytes", "C": b"timestamp,room,event\n2026-10-10 15:22,412,first_entry\n"}
        _pdf, reader, text, _recon = _packet("complete", exhibit_files=exhibit_files)
        self.assertGreater(len(reader.pages), 3)
        self.assertIn("EXHIBIT APPENDIX", text)
        self.assertIn("EXHIBIT A", text)
        self.assertIn("EXHIBIT C", text)

    def test_default_format_is_executive(self):
        s = SCENARIOS["visa_fraud_10_4"]
        recon = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
        draft = LlamaEngine(provider="mock").draft_rebuttal(s["notice"], s["folio"], recon)
        pdf_bytes = EvidencePacketGenerator.generate_packet(
            s["notice"], s["folio"], recon, draft,
            approved_by="Test Manager", approved_at="2026-11-03 12:00 UTC",
            policy_text="Non-refundable.")
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 3)


if __name__ == "__main__":
    unittest.main()
