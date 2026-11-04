"""Tests: Phase 2 P1 data reliability.

Covers: registry JSON->SQLite migration, corrupt legacy file handling,
cross-instance (multi-process simulation) write safety, encrypted webhook
secrets + resumable deliveries, JSONL torn-line reporting, strengthened
upload validation, and agent stale-running recovery.
"""

import json
import tempfile
import threading
import unittest
from pathlib import Path

from core._jsonl import append_jsonl, read_jsonl
from core.integrations.contracts import IntegrationEvent
from core.integrations.registry import IntegrationRegistry, IntegrationRegistryError
from core.integrations.webhooks import WebhookManager, verify_signature
from core.security import sanitize_filename, validate_upload


class TestRegistryMigration(unittest.TestCase):
    def test_legacy_json_migrated_and_renamed(self):
        with tempfile.TemporaryDirectory() as tmp:
            legacy = {
                "tenants": {"hotel-a": {"tenant_id": "hotel-a", "name": "Hotel A", "status": "active", "property_ids": []}},
                "credentials": {}, "agents": {}, "webhooks": {}, "cases": {}, "jobs": {}, "deliveries": {},
            }
            (Path(tmp) / "registry.json").write_text(json.dumps(legacy), encoding="utf-8")
            registry = IntegrationRegistry(root=tmp)
            self.assertEqual(registry.get_tenant("hotel-a")["name"], "Hotel A")
            self.assertFalse((Path(tmp) / "registry.json").exists())
            self.assertTrue(list(Path(tmp).glob("registry.json.migrated-*")))
            registry.close()

    def test_corrupt_legacy_json_fails_loud_and_preserves_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "registry.json").write_text("{not json", encoding="utf-8")
            with self.assertRaises(IntegrationRegistryError):
                IntegrationRegistry(root=tmp)
            self.assertTrue((Path(tmp) / "registry.json").exists())

    def test_two_instances_do_not_lose_writes(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = IntegrationRegistry(root=tmp)
            b = IntegrationRegistry(root=tmp)
            a.create_tenant("hotel-a", "Hotel A")
            b.create_tenant("hotel-b", "Hotel B")
            # Interleaved writes from both instances survive.
            _pub, secret_a = a.issue_credential("hotel-a", "client", scopes=["cases:read"])
            b.issue_credential("hotel-b", "client", scopes=["cases:read"])
            self.assertIsNotNone(a.authenticate(secret_a))
            self.assertEqual(b.get_tenant("hotel-a")["name"], "Hotel A")
            self.assertEqual(a.get_tenant("hotel-b")["name"], "Hotel B")
            a.close()
            b.close()

    def test_concurrent_case_upserts(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            _pub, secret = registry.issue_credential("hotel-a", "client", scopes=["cases:write", "cases:read"])
            ctx = registry.authenticate(secret).to_context()

            from core.integrations.contracts import IntegrationCaseRef
            errors = []

            def worker(n):
                try:
                    ref = IntegrationCaseRef(tenant_id="hotel-a", case_id=f"CASE-{n}")
                    registry.upsert_case(ctx, ref, {"notice": {}, "folio": {}, "documents": [], "status": "received"})
                except Exception as exc:  # pragma: no cover
                    errors.append(exc)

            threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(registry.list_cases("hotel-a")), 12)
            registry.close()


class TestWebhookSecretsAndResume(unittest.TestCase):
    def test_secret_encrypted_at_rest_and_signature_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            captured = {}

            def sender(url, payload, headers):
                captured.update(headers)
                return 200

            manager = WebhookManager(registry, sender=sender)
            sub = manager.subscribe("hotel-a", "https://example.test/hook", ["dispute.received"], secret="whsec_test_123456")
            self.assertEqual(sub["secret_shown_once"], "whsec_test_123456")
            self.assertNotIn("secret", {k: v for k, v in sub.items() if k != "secret_shown_once"})

            # The database file must not contain the plaintext secret.
            db_bytes = (Path(tmp) / "registry.db").read_bytes()
            self.assertNotIn(b"whsec_test_123456", db_bytes)

            event = IntegrationEvent(event_type="dispute.received", tenant_id="hotel-a", case_id="C-1")
            deliveries = manager.publish(event)
            self.assertEqual(deliveries[0]["status"], "delivered")
            self.assertTrue(verify_signature("whsec_test_123456", event.payload_bytes(),
                                             captured["X-FolioShield-Timestamp"], captured["X-FolioShield-Signature"]))
            registry.close()

    def test_failed_delivery_resumes(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            attempts = {"n": 0}

            def flaky(url, payload, headers):
                attempts["n"] += 1
                return 500 if attempts["n"] == 1 else 200

            manager = WebhookManager(registry, sender=flaky)
            manager.subscribe("hotel-a", "https://example.test/hook", ["*"], secret="resume-secret-1")
            event = IntegrationEvent(event_type="dispute.received", tenant_id="hotel-a", case_id="C-2")
            first = manager.publish(event)[0]
            self.assertEqual(first["status"], "retrying")
            # Make the retry due immediately, then resume.
            record = registry.get_delivery(first["delivery_key"])
            record["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
            registry.put_delivery(record["delivery_key"], record)
            resumed = manager.resume_due_deliveries()
            self.assertEqual(len(resumed), 1)
            self.assertEqual(resumed[0]["status"], "delivered")
            self.assertEqual(resumed[0]["attempts"], 2)
            registry.close()


class TestJsonlHardening(unittest.TestCase):
    def test_torn_line_reported_not_dropped_silently(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "case.jsonl")
            append_jsonl(path, {"kind": "submission", "record": {"n": 1}})
            with open(path, "a", encoding="utf-8") as f:
                f.write('{"kind": "submission", "record": {"n": 2')  # torn tail
            records, corrupt = read_jsonl(path)
            self.assertEqual(len(records), 1)
            self.assertEqual(corrupt, [2])

    def test_concurrent_appends_produce_whole_lines(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "audit.jsonl")

            def worker(n):
                for i in range(25):
                    append_jsonl(path, {"worker": n, "i": i})

            threads = [threading.Thread(target=worker, args=(n,)) for n in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            records, corrupt = read_jsonl(path)
            self.assertEqual(len(records), 100)
            self.assertEqual(corrupt, [])


class TestUploadValidationStrengthened(unittest.TestCase):
    def test_disallowed_extensions_rejected(self):
        for name in ("payload.exe", "page.html", "icon.svg", "archive.zip", "noext"):
            with self.assertRaises(ValueError, msg=name):
                validate_upload(b"data", name)

    def test_binary_disguised_as_text_rejected(self):
        with self.assertRaises(ValueError):
            validate_upload(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32, "folio.csv")
        with self.assertRaises(ValueError):
            validate_upload(b"MZ\x90\x00" + b"\x00" * 16, "notes.txt")

    def test_legitimate_files_still_pass(self):
        validate_upload(b"%PDF-1.4 content", "notice.pdf")
        validate_upload(b"\x89PNG\r\n\x1a\nrest", "scan.png")
        validate_upload("a,b\n1,2\n".encode(), "folio.csv")
        validate_upload(b"From: a@b.com\nSubject: Confirmation\n\nBody", "mail.eml")
        validate_upload("plain text log".encode(), "log.txt")

    def test_sanitize_filename(self):
        self.assertEqual(sanitize_filename("../../etc/passwd"), "passwd")
        self.assertEqual(sanitize_filename('a<b>:"c".pdf'), "a_b___c_.pdf")
        self.assertEqual(sanitize_filename(""), "document")
        self.assertEqual(sanitize_filename("normal file.pdf"), "normal file.pdf")


class TestAgentRecovery(unittest.TestCase):
    def test_stale_running_job_recovered(self):
        from agent.queue import AgentQueue

        with tempfile.TemporaryDirectory() as tmp:
            queue = AgentQueue(str(Path(tmp) / "q.sqlite3"))
            job = queue.enqueue("upload_document", {"case_id": "C-1"})
            queue.mark_running(job["job_id"])
            # Fresh (non-stale) running job is left alone.
            self.assertEqual(queue.recover_stale_running(lease_seconds=600), 0)
            # Simulate a crash long ago by backdating updated_at.
            queue._conn.execute("UPDATE jobs SET updated_at='2000-01-01T00:00:00+00:00' WHERE job_id=?", (job["job_id"],))
            queue._conn.commit()
            self.assertEqual(queue.recover_stale_running(lease_seconds=600), 1)
            self.assertEqual(queue.get(job["job_id"])["status"], "queued")
            queue.close()


if __name__ == "__main__":
    unittest.main()
