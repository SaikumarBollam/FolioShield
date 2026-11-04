"""
Tests for Alembic database migrations.
"""

import tempfile
import unittest
from pathlib import Path
from alembic import command
from alembic.config import Config


class TestDatabaseMigrations(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.db_path = Path(self._tmp.name) / "migration_test.db"
        self.alembic_cfg = Config("alembic.ini")
        self.alembic_cfg.set_main_option("sqlalchemy.url", f"sqlite:///{self.db_path}")

    def tearDown(self):
        self._tmp.cleanup()

    def test_upgrade_and_downgrade_roundtrip(self):
        # Run upgrade to head
        command.upgrade(self.alembic_cfg, "head")
        self.assertTrue(self.db_path.exists())

        # Run downgrade to base
        command.downgrade(self.alembic_cfg, "base")


if __name__ == "__main__":
    unittest.main()
