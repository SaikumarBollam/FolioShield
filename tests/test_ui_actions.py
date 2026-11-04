"""Tests: UI evidence callbacks (Phase 3 extraction) with fake session state."""

import io
import unittest
import zipfile

from core.exhibit_store import ExhibitStore
from ui import evidence_actions as actions
from ui import state as ui_state


class _FakeUpload:
    def __init__(self, name, data):
        self.name = name
        self._data = data

    def getvalue(self):
        return self._data


class _FakeVisionEngine:
    def __init__(self, configured=True):
        self._configured = configured
        self.calls = []

    def is_api_configured(self):
        return self._configured

    def analyze_visual_evidence(self, image_bytes, document_type="Registration Card"):
        self.calls.append((len(image_bytes), document_type))
        return {"analyzed": True, "signature_detected": True, "document_type": document_type,
                "guest_name_extracted": "Test Guest", "date_extracted": "2026-10-10",
                "notes": "ok", "confidence_score": 0.9}


def _state():
    return {
        "evidence_items": {}, "processed_uploads": {}, "reviewer_name": "Duty Manager",
        "rebuttal_editor": "draft", "approval": {"by": "x"}, "generated_pdf": b"%PDF",
        "draft_engine": "engine", "pdf_fingerprint": "fp",
    }


def _zip(files):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


class TestEvidenceActions(unittest.TestCase):
    def setUp(self):
        self.state = _state()
        self.store = ExhibitStore()
        self.logs = []
        self.persisted = []
        self.kwargs = dict(
            exhibit_store=self.store,
            actor_fn=lambda: ui_state.actor_from(self.state),
            log_fn=lambda a, d: self.logs.append((a, d)),
            persist_fn=lambda: self.persisted.append(True),
        )

    def test_collect_sets_item_hash_and_flags(self):
        self.state["evfile_signed_registration_card"] = _FakeUpload("reg_card.pdf", b"%PDF-card")
        actions.collect_evidence_file(self.state, "signed_registration_card", "Signed Registration Card", **self.kwargs)
        item = self.state["evidence_items"]["signed_registration_card"]
        self.assertTrue(item["present"])
        self.assertEqual(item["filename"], "reg_card.pdf")
        self.assertEqual(len(item["sha256"]), 64)
        self.assertTrue(self.state["doc_signed_registration_card"])
        self.assertTrue(self.store.has(item["stored_ref"], "reg_card.pdf"))
        self.assertEqual(self.logs[0][0], "evidence_file_collected")
        self.assertTrue(self.persisted)
        # Collecting resets derived outputs (draft/approval invalidated).
        self.assertEqual(self.state["rebuttal_editor"], "")
        self.assertIsNone(self.state["approval"])

    def test_collect_same_file_twice_is_noop(self):
        upload = _FakeUpload("reg_card.pdf", b"%PDF-card")
        self.state["evfile_signed_registration_card"] = upload
        actions.collect_evidence_file(self.state, "signed_registration_card", "Card", **self.kwargs)
        self.state["evfile_signed_registration_card"] = upload
        actions.collect_evidence_file(self.state, "signed_registration_card", "Card", **self.kwargs)
        self.assertEqual(len([l for l in self.logs if l[0] == "evidence_file_collected"]), 1)

    def test_collect_invalid_file_reports_error(self):
        self.state["evfile_signed_registration_card"] = _FakeUpload("evil.exe", b"MZ\x90\x00")
        actions.collect_evidence_file(self.state, "signed_registration_card", "Card", **self.kwargs)
        self.assertIn("evidence_upload_error", self.state)
        self.assertNotIn("signed_registration_card", self.state["evidence_items"])

    def test_remove_clears_item(self):
        self.state["evfile_wifi_usage_log"] = _FakeUpload("wifi_usage_log.csv", b"a,b\n1,2\n")
        actions.collect_evidence_file(self.state, "wifi_usage_log", "WiFi", **self.kwargs)
        actions.remove_evidence_file(self.state, "wifi_usage_log", "WiFi",
                                     log_fn=self.kwargs["log_fn"], persist_fn=self.kwargs["persist_fn"])
        item = self.state["evidence_items"]["wifi_usage_log"]
        self.assertFalse(item["present"])
        self.assertFalse(self.state["doc_wifi_usage_log"])

    def test_zip_import_routes_files(self):
        archive = _zip({"01_signed_registration_card.png": b"\x89PNG\r\n\x1a\n" + b"x" * 20,
                        "12_wifi_usage_log.csv": b"a,b\n1,2\n",
                        "mystery.txt": b"hello"})
        self.state["evidence_zip_uploader"] = _FakeUpload("evidence.zip", archive)
        actions.import_evidence_zip(self.state, **self.kwargs)
        report = self.state["evidence_zip_report"]
        self.assertEqual({i["doc_type"] for i in report["imported"]},
                         {"signed_registration_card", "wifi_usage_log"})
        self.assertEqual(report["unmatched"], ["mystery.txt"])
        self.assertTrue(self.state["evidence_items"]["wifi_usage_log"]["present"])

    def test_vision_check_binds_hash_and_persists(self):
        self.state["evfile_signed_registration_card"] = _FakeUpload("reg_card.png", b"\x89PNG\r\n\x1a\nimg")
        actions.collect_evidence_file(self.state, "signed_registration_card", "Card", **self.kwargs)
        engine = _FakeVisionEngine(configured=True)
        actions.run_vision_check(self.state, "signed_registration_card", "Card",
                                 exhibit_store=self.store, vision_engine=engine,
                                 actor_fn=self.kwargs["actor_fn"], log_fn=self.kwargs["log_fn"],
                                 persist_fn=self.kwargs["persist_fn"])
        item = self.state["evidence_items"]["signed_registration_card"]
        check = item["vision_check"]
        self.assertTrue(check["analyzed"])
        self.assertEqual(check["sha256"], item["sha256"])
        self.assertEqual(engine.calls[0][1], "Registration Card")

    def test_vision_check_without_provider_records_precise_error(self):
        self.state["evfile_signed_registration_card"] = _FakeUpload("reg_card.png", b"\x89PNG\r\n\x1a\nimg")
        actions.collect_evidence_file(self.state, "signed_registration_card", "Card", **self.kwargs)
        engine = _FakeVisionEngine(configured=False)
        actions.run_vision_check(self.state, "signed_registration_card", "Card",
                                 exhibit_store=self.store, vision_engine=engine,
                                 actor_fn=self.kwargs["actor_fn"], log_fn=self.kwargs["log_fn"],
                                 persist_fn=self.kwargs["persist_fn"])
        self.assertIn("No vision provider is configured", self.state["vision_check_error"])
        self.assertFalse(self.state["evidence_items"]["signed_registration_card"].get("vision_check"))


if __name__ == "__main__":
    unittest.main()
