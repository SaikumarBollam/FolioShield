"""Tests for ZIP bulk evidence import planning and filename matching."""

import io
import json
import unittest
import zipfile

from core.zip_import import match_doc_type, plan_zip_import


def _zip(files: dict) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class TestMatchDocType(unittest.TestCase):
    def test_registry_key_in_filename(self):
        self.assertEqual(match_doc_type("12_wifi_usage_log.csv"), "wifi_usage_log")
        self.assertEqual(match_doc_type("exports/signed_registration_card.pdf"), "signed_registration_card")

    def test_keyword_match(self):
        self.assertEqual(match_doc_type("keycard_export.csv"), "keycard_lock_audit")
        self.assertEqual(match_doc_type("3ds_result.txt"), "three_ds_authentication")
        self.assertEqual(match_doc_type("cctv_lobby.png"), "cctv_footage")

    def test_unknown_returns_none(self):
        self.assertIsNone(match_doc_type("random_notes.txt"))
        self.assertIsNone(match_doc_type(""))


class TestPlanZipImport(unittest.TestCase):
    def test_matches_and_reports(self):
        plan = plan_zip_import(_zip({
            "01_signed_registration_card.png": b"\x89PNG\r\n\x1a\n" + b"x" * 50,
            "wifi.csv": b"timestamp,room\n2026-10-10,1204\n",
            "mystery.txt": b"hello",
            "notes.docx": b"nope",
        }))
        self.assertTrue(plan["ok"])
        self.assertIn("signed_registration_card", plan["matched"])
        self.assertIn("wifi_usage_log", plan["matched"])
        self.assertEqual(plan["unmatched"], ["mystery.txt"])
        self.assertEqual(len(plan["skipped"]), 1)  # .docx rejected

    def test_manifest_wins(self):
        plan = plan_zip_import(_zip({
            "manifest.json": json.dumps({"wifi_usage_log": "export1.csv"}).encode(),
            "export1.csv": b"a,b\n1,2\n",
        }))
        self.assertEqual(plan["matched"]["wifi_usage_log"]["via"], "manifest")
        self.assertEqual(plan["matched"]["wifi_usage_log"]["filename"], "export1.csv")

    def test_duplicate_slot_keeps_first(self):
        plan = plan_zip_import(_zip({
            "wifi_usage_log.csv": b"a\n",
            "wifi_backup.csv": b"b\n",
        }))
        self.assertEqual(plan["matched"]["wifi_usage_log"]["filename"], "wifi_usage_log.csv")
        self.assertEqual(len(plan["skipped"]), 1)

    def test_invalid_zip(self):
        plan = plan_zip_import(b"not a zip")
        self.assertFalse(plan["ok"])
        self.assertIn("not a valid ZIP", plan["error"])

    def test_oversized_file_skipped(self):
        plan = plan_zip_import(_zip({"wifi_usage_log.csv": b"x" * 2048}), max_file_bytes=1024)
        self.assertEqual(plan["matched"], {})
        self.assertEqual(len(plan["skipped"]), 1)

    def test_unsafe_path_skipped(self):
        plan = plan_zip_import(_zip({"../wifi_usage_log.csv": b"a\n"}))
        self.assertEqual(plan["matched"], {})
        self.assertEqual(len(plan["skipped"]), 1)


if __name__ == "__main__":
    unittest.main()
