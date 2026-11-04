"""
Unit and integration tests for core.application.dispute_service.DisputeService.
"""

import tempfile
import unittest
from pathlib import Path

from core.application.dispute_service import DisputeService
from core.audit_logger import AuditLogger
from core.case_store import CaseStore
from core.exhibit_store import ExhibitStore
from core.models import NoticeData, FolioData, SubmissionRecord, OutcomeRecord


class TestDisputeService(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self._tmp.name)
        self.case_dir = str(self.tmp_path / "cases")
        self.exhibit_dir = str(self.tmp_path / "exhibits")
        self.log_dir = str(self.tmp_path / "logs")

        self.service = DisputeService(
            case_store=CaseStore(db_path=str(self.tmp_path / "cases.json")),
            exhibit_store=ExhibitStore(root=self.exhibit_dir),
            audit_logger=AuditLogger(log_dir=self.log_dir),
        )

    def tearDown(self):
        self.service.close()
        self._tmp.cleanup()

    def test_case_crud_with_tenant_isolation(self):
        # Save case under tenant A
        self.service.save_case(
            case_id="case-101",
            notice={"case_id": "case-101", "amount": 250.0},
            folio={"guest_name": "Alice", "total": 250.0},
            tenant_id="tenant-a",
        )

        # Load case under tenant A
        loaded_a = self.service.load_case("case-101", tenant_id="tenant-a")
        self.assertIsNotNone(loaded_a)
        assert loaded_a is not None
        self.assertEqual(loaded_a["folio"]["guest_name"], "Alice")

        # Load case under tenant B returns None
        loaded_b = self.service.load_case("case-101", tenant_id="tenant-b")
        self.assertIsNone(loaded_b)

        # Cross-tenant overwrite fails
        with self.assertRaises(PermissionError):
            self.service.save_case(
                case_id="case-101",
                notice={"case_id": "case-101"},
                folio={"guest_name": "Bob"},
                tenant_id="tenant-b",
            )

        # Delete case under tenant A
        self.assertTrue(self.service.delete_case("case-101", tenant_id="tenant-a"))
        self.assertIsNone(self.service.load_case("case-101", tenant_id="tenant-a"))

    def test_upload_evidence_and_retention(self):
        # Valid PDF evidence
        pdf_bytes = b"%PDF-1.4 sample evidence binary"
        stored = self.service.upload_evidence(
            filename="registration_card.pdf",
            data=pdf_bytes,
            doc_type="signed_registration_card",
            case_id="case-202",
            tenant_id="hotel-ny",
            actor="Auditor",
        )
        self.assertEqual(stored["size_bytes"], len(pdf_bytes))
        self.assertTrue(self.service.exhibit_store.has(stored["stored_ref"], "registration_card.pdf", tenant_id="hotel-ny"))

    def test_human_approval_enforces_reviewer_identity(self):
        notice = NoticeData(case_id="case-303", disputed_amount=400.0, reason_code="10.4")
        folio = FolioData(guest_name="Charlie Brown", room_number="402", total_charges=400.0)

        # Rejection of empty approved_by
        with self.assertRaises(ValueError):
            self.service.approve_rebuttal(
                notice=notice,
                folio=folio,
                rebuttal_text="Formal rebuttal...",
                approved_by="",
            )

        with self.assertRaises(ValueError):
            self.service.approve_rebuttal(
                notice=notice,
                folio=folio,
                rebuttal_text="Formal rebuttal...",
                approved_by="   ",
            )

        # Valid human approval
        approval = self.service.approve_rebuttal(
            notice=notice,
            folio=folio,
            rebuttal_text="Formal rebuttal statement.",
            approved_by="General Manager Jane Doe",
            reviewer_role="GM",
            tenant_id="hotel-ny",
        )
        self.assertEqual(approval["approved_by"], "General Manager Jane Doe")
        self.assertEqual(approval["reviewer_role"], "GM")
        self.assertIn("fingerprint", approval)
        self.assertIn("rebuttal_sha256", approval)

    def test_reconciliation_and_packet_generation(self):
        notice = NoticeData(case_id="case-404", disputed_amount=150.0, reason_code="10.4", arn="ARN1234567890")
        folio = FolioData(guest_name="Dana Scully", room_number="101", total_charges=150.0)

        recon = self.service.reconcile_dispute(notice, folio, tenant_id="tenant-1")
        self.assertIn("completeness_score", recon)

        rebuttal = self.service.draft_rebuttal(notice, folio, recon, tenant_id="tenant-1")
        self.assertIsInstance(rebuttal, str)
        self.assertTrue(len(rebuttal) > 0)

        # Generate packet PDF
        packet_bytes = self.service.generate_packet(
            notice=notice,
            folio=folio,
            reconciliation=recon,
            rebuttal_text=rebuttal,
            approved_by="Auditor Mulder",
            approval_fingerprint="fp-test-404",
            tenant_id="tenant-1",
        )
        self.assertTrue(packet_bytes.startswith(b"%PDF"))

    def test_record_submission_and_outcome(self):
        sub_rec = SubmissionRecord(case_id="case-505", portal_id="chase_portal", submitted_by="NightAuditor")
        saved_sub = self.service.record_submission(sub_rec, tenant_id="tenant-ny")
        self.assertEqual(saved_sub.portal_id, "chase_portal")

        out_rec = OutcomeRecord(case_id="case-505", decision="won", amount_recovered=500.0)
        saved_out = self.service.record_outcome(out_rec, tenant_id="tenant-ny")
        self.assertEqual(saved_out.decision, "won")
        self.assertEqual(saved_out.amount_recovered, 500.0)


if __name__ == "__main__":
    unittest.main()
