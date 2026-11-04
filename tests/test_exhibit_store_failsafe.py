"""Tests: fail-safe exhibit storage (atomic writes, verified reads, quarantine)."""

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from core.exhibit_store import ExhibitStore, ExhibitStoreError


class TestFailSafeExhibitStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = str(Path(self._tmp.name) / "exhibits")
        self.store = ExhibitStore(root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_round_trip_and_verify_all(self):
        stored = self.store.put(b"%PDF-evidence-bytes", "reg.pdf")
        self.assertEqual(self.store.get(stored["stored_ref"], "reg.pdf"), b"%PDF-evidence-bytes")
        report = self.store.verify_all()
        self.assertEqual(report["checked"], 1)
        self.assertEqual(report["ok"], 1)
        self.assertEqual(report["corrupt"], [])

    def test_corrupt_file_is_quarantined_and_reported_missing(self):
        stored = self.store.put(b"original-bytes", "reg.pdf")
        ref = stored["stored_ref"]
        path = Path(self.root) / ref[:2] / f"{ref}.pdf"
        path.write_bytes(b"tampered-bytes!")
        fresh = ExhibitStore(root=self.root)  # bypass the in-memory cache
        self.assertIsNone(fresh.get(ref, "reg.pdf"))
        self.assertFalse(fresh.has(ref, "reg.pdf"))
        quarantine = Path(self.root) / "quarantine"
        self.assertTrue(quarantine.exists())
        self.assertTrue(any(p.name.startswith(ref) for p in quarantine.iterdir()))
        report = fresh.verify_all()
        self.assertEqual(report["checked"], 0)  # quarantined file no longer counted

    def test_verify_all_detects_corruption(self):
        stored = self.store.put(b"good-bytes", "a.pdf")
        ref = stored["stored_ref"]
        (Path(self.root) / ref[:2] / f"{ref}.pdf").write_bytes(b"bad!")
        report = ExhibitStore(root=self.root).verify_all()
        self.assertEqual(report["corrupt"], [ref])

    def test_interrupted_write_leaves_no_corrupt_exhibit(self):
        # Simulate a crash between temp write and replace: an orphaned
        # temp file must not be served as the exhibit.
        data = b"complete-evidence"
        ref = hashlib.sha256(data).hexdigest()
        shard = Path(self.root) / ref[:2]
        shard.mkdir(parents=True, exist_ok=True)
        (shard / f"{ref}.tmp-deadbeef1234").write_bytes(data[:5])  # partial temp
        self.assertIsNone(self.store.get(ref, "x.pdf"))
        stored = self.store.put(data, "x.pdf")  # real write still succeeds
        self.assertEqual(self.store.get(stored["stored_ref"], "x.pdf"), data)

    def test_write_failure_raises_typed_error(self):
        with mock.patch("os.replace", side_effect=OSError("disk full")):
            with self.assertRaises(ExhibitStoreError):
                self.store.put(b"bytes", "reg.pdf")
        # No partial file left at the content address.
        ref = hashlib.sha256(b"bytes").hexdigest()
        self.assertFalse((Path(self.root) / ref[:2] / f"{ref}.pdf").exists())

    def test_memory_only_store_still_works(self):
        mem = ExhibitStore()
        stored = mem.put(b"abc", "a.txt")
        self.assertEqual(mem.get(stored["stored_ref"], "a.txt"), b"abc")
        self.assertEqual(mem.verify_all()["ok"], 1)


if __name__ == "__main__":
    unittest.main()
