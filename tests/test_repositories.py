"""
Tests for Relational Repositories (SqlCaseRepository & SqliteLegacyCaseRepository).
"""

import tempfile
import unittest
from pathlib import Path

from core.case_store import CaseConflictError, CaseStore
from core.infrastructure.database.repositories.sql import SqlCaseRepository
from core.infrastructure.database.repositories.sqlite_legacy import SqliteLegacyCaseRepository
from core.infrastructure.database.session import DatabaseEngine

NOTICE = {
    "case_id": "CB-REPO-101",
    "card_network": "Visa",
    "reason_code": "10.4",
    "disputed_amount": 550.0,
}
FOLIO = {
    "guest_name": "Eleanor Vance",
    "folio_number": "F-550",
    "total_charges": 550.0,
}


class TestSqlCaseRepository(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = Path(self._tmp.name) / "test_repo.db"
        self.engine = DatabaseEngine(f"sqlite:///{db_path}")
        self.repo = SqlCaseRepository(engine=self.engine)

    def tearDown(self):
        self.engine.close()
        self._tmp.cleanup()

    def test_save_get_roundtrip_and_list(self):
        res = self.repo.save(
            case_id="CB-REPO-101",
            notice=NOTICE,
            folio=FOLIO,
            tenant_id="tenant-alpha",
        )
        self.assertEqual(res["case_id"], "CB-REPO-101")
        self.assertIsNotNone(res["updated_at"])

        # Get
        loaded = self.repo.get("CB-REPO-101", tenant_id="tenant-alpha")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["notice"]["disputed_amount"], 550.0)
        self.assertEqual(loaded["folio"]["guest_name"], "Eleanor Vance")

        # List
        cases = self.repo.list(tenant_id="tenant-alpha")
        self.assertEqual(len(cases), 1)
        self.assertEqual(cases[0]["case_id"], "CB-REPO-101")

        # Delete
        self.assertTrue(self.repo.delete("CB-REPO-101", tenant_id="tenant-alpha"))
        self.assertIsNone(self.repo.get("CB-REPO-101", tenant_id="tenant-alpha"))

    def test_tenant_isolation_guards(self):
        self.repo.save(
            case_id="CB-REPO-102",
            notice=NOTICE,
            folio=FOLIO,
            tenant_id="tenant-alpha",
        )

        # Cross-tenant get returns None (does not leak existence)
        self.assertIsNone(self.repo.get("CB-REPO-102", tenant_id="tenant-beta"))

        # Cross-tenant overwrite fails closed
        with self.assertRaises(PermissionError):
            self.repo.save(
                case_id="CB-REPO-102",
                notice=NOTICE,
                folio={"guest_name": "Hacker"},
                tenant_id="tenant-beta",
            )

        # Cross-tenant delete returns False
        self.assertFalse(self.repo.delete("CB-REPO-102", tenant_id="tenant-beta"))

    def test_optimistic_conflict_detection(self):
        saved = self.repo.save(
            case_id="CB-REPO-103",
            notice=NOTICE,
            folio=FOLIO,
            tenant_id="tenant-alpha",
        )
        ts1 = saved["updated_at"]

        # Valid update with expected timestamp
        self.repo.save(
            case_id="CB-REPO-103",
            notice=NOTICE,
            folio=FOLIO,
            tenant_id="tenant-alpha",
            expected_updated_at=ts1,
        )

        # Stale update with old ts1 raises CaseConflictError
        with self.assertRaises(CaseConflictError):
            self.repo.save(
                case_id="CB-REPO-103",
                notice=NOTICE,
                folio=FOLIO,
                tenant_id="tenant-alpha",
                expected_updated_at=ts1,
            )


class TestSqliteLegacyCaseRepository(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        db_path = str(Path(self._tmp.name) / "legacy.db")
        self.store = CaseStore(db_path=db_path)
        self.repo = SqliteLegacyCaseRepository(store=self.store)

    def tearDown(self):
        self.repo.close()
        self._tmp.cleanup()

    def test_legacy_adapter_parity(self):
        res = self.repo.save(
            case_id="CB-LEGACY-001",
            notice=NOTICE,
            folio=FOLIO,
            tenant_id="tenant-gamma",
        )
        self.assertEqual(res["case_id"], "CB-LEGACY-001")

        loaded = self.repo.get("CB-LEGACY-001", tenant_id="tenant-gamma")
        self.assertIsNotNone(loaded)
        assert loaded is not None
        self.assertEqual(loaded["notice"]["disputed_amount"], 550.0)

        cases = self.repo.list(tenant_id="tenant-gamma")
        self.assertEqual(len(cases), 1)

        self.assertTrue(self.repo.delete("CB-LEGACY-001", tenant_id="tenant-gamma"))


if __name__ == "__main__":
    unittest.main()
