"""
Integration management and tenant isolation tests.
"""

import tempfile
import unittest

from core.integrations.registry import IntegrationRegistry
from core.case_store import CaseStore
from core.exhibit_store import ExhibitStore
from core.submission import SubmissionRegistry
from core.models import SubmissionRecord


class TestIntegrationManagement(unittest.TestCase):

    def test_monitoring_snapshot_is_tenant_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            registry.create_tenant("hotel-b", "Hotel B")
            registry.issue_credential("hotel-a", "A client", scopes=["cases:read"])
            registry.issue_credential("hotel-b", "B client", scopes=["cases:read"])
            snap_a = registry.monitoring_snapshot("hotel-a")
            snap_b = registry.monitoring_snapshot("hotel-b")
            self.assertEqual(snap_a["credentials"], 1)
            self.assertEqual(snap_b["credentials"], 1)
            self.assertEqual(snap_a["cases"], 0)
            self.assertEqual(snap_b["cases"], 0)
            registry.close()

    def test_agent_suspension_blocks_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            agent, _secret = registry.register_agent("hotel-a", "agent-1", "Front Office")
            self.assertEqual(agent["status"], "active")
            self.assertIsNotNone(registry.agent_heartbeat("hotel-a", "agent-1"))
            self.assertTrue(registry.set_agent_status("hotel-a", "agent-1", "suspended"))
            self.assertIsNone(registry.agent_heartbeat("hotel-a", "agent-1"))
            registry.close()

    def test_case_store_tenant_isolation(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp_db:
            db_path = tmp_db.name
        store = CaseStore(db_path=db_path)
        notice = {"case_id": "CASE-TENANT-A", "disputed_amount": 250.0}
        folio = {"guest_name": "Alice"}
        store.save_case("CASE-TENANT-A", notice, folio, tenant_id="hotel-a")

        # Hotel A can load the case
        case_a = store.load_case("CASE-TENANT-A", tenant_id="hotel-a")
        self.assertIsNotNone(case_a)
        self.assertEqual(case_a["case_id"], "CASE-TENANT-A")

        # Hotel B cannot load Hotel A's case
        case_b = store.load_case("CASE-TENANT-A", tenant_id="hotel-b")
        self.assertIsNone(case_b)

        # Hotel B cannot overwrite Hotel A's case
        with self.assertRaises(PermissionError):
            store.save_case("CASE-TENANT-A", notice, folio, tenant_id="hotel-b")

        # Hotel B cannot delete Hotel A's case
        deleted_by_b = store.delete_case("CASE-TENANT-A", tenant_id="hotel-b")
        self.assertFalse(deleted_by_b)
        self.assertIsNotNone(store.load_case("CASE-TENANT-A", tenant_id="hotel-a"))

        # Hotel A can delete its own case
        deleted_by_a = store.delete_case("CASE-TENANT-A", tenant_id="hotel-a")
        self.assertTrue(deleted_by_a)
        self.assertIsNone(store.load_case("CASE-TENANT-A", tenant_id="hotel-a"))
        store.close()

    def test_exhibit_store_tenant_isolation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = ExhibitStore(root=tmp_dir)
            sample_data = b"%PDF-1.4 sample exhibit for tenant a\n%%EOF"
            stored = store.put(sample_data, "doc.pdf", tenant_id="hotel-a")
            ref = str(stored["stored_ref"])

            # Hotel A can retrieve the file
            self.assertTrue(store.has(ref, "doc.pdf", tenant_id="hotel-a"))
            retrieved = store.get(ref, "doc.pdf", tenant_id="hotel-a")
            self.assertEqual(retrieved, sample_data)

    def test_submission_registry_tenant_isolation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            sub_reg = SubmissionRegistry(root=tmp_dir)
            record_a = SubmissionRecord(
                case_id="CASE-100",
                portal_id="vrol",
                submitted_by="Front Desk A",
                status="submitted",
                tenant_id="hotel-a"
            )
            sub_reg.register_submission(record_a)

            # Hotel A can load submission
            loaded_a = sub_reg.load("CASE-100", tenant_id="hotel-a")
            self.assertEqual(len(loaded_a["submissions"]), 1)
            self.assertEqual(loaded_a["submissions"][0]["submitted_by"], "Front Desk A")

            # Hotel B does not see Hotel A's submission in its tenant folder
            loaded_b = sub_reg.load("CASE-100", tenant_id="hotel-b")
            self.assertEqual(len(loaded_b["submissions"]), 0)


if __name__ == "__main__":
    unittest.main()
