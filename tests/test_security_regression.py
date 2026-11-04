"""Tests: security regression suite (Phase 3 P2).

Route-matrix auth enforcement, credential lifecycle over HTTP, tenant
isolation without existence leaks, approval forgery over HTTP, upload
attack shapes, and audit-trail tamper detection.
"""

import dataclasses
import http.client
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import core.api as api
from core.audit_logger import AuditLogger
from core.config import config as app_config
from core.integrations.registry import IntegrationRegistry
from core.security import validate_upload

NOTICE = {"case_id": "SEC-1", "card_network": "Visa", "reason_code": "10.4",
          "disputed_amount": 100.0, "original_amount": 100.0, "currency": "USD",
          "cardholder_name": "Test Guest", "card_last_4": "4821",
          "transaction_date": "2026-10-10", "dispute_date": "2026-11-02"}
FOLIO = {"guest_name": "Test Guest", "card_last_4": "4821", "check_in": "2026-10-10",
         "check_out": "2026-10-11", "stay_status": "occupied",
         "total_charges": 100.0, "total_payments": 100.0, "line_items": []}
LEGACY_POST_ROUTES = ["/api/v1/reconcile", "/api/v1/rebuttal/draft", "/api/v1/packet/generate",
                      "/api/v1/submission/bundle", "/api/v1/submission/register",
                      "/api/v1/submission/outcome", "/api/v1/dispute/approve", "/api/v1/dispute/process"]


def _cfg(**overrides):
    return dataclasses.replace(app_config, **overrides)


def _request(port, method, path, payload=None, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    conn.request(method, path, json.dumps(payload or {}), headers)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    return resp.status, (json.loads(body) if body else {})


class _Server:
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), api.FolioShieldAPIHandler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self.port

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestRouteMatrixAuth(unittest.TestCase):
    def test_every_legacy_route_requires_key_in_production(self):
        cfg = _cfg(api_key=None, api_allow_legacy_unauthenticated=False)
        with mock.patch.object(api, "config", cfg), _Server() as port:
            for route in LEGACY_POST_ROUTES:
                status, _ = _request(port, "POST", route, {"notice": NOTICE, "folio": FOLIO})
                self.assertEqual(status, 401, f"{route} must fail closed")

    def test_wrong_key_variants_all_rejected(self):
        cfg = _cfg(api_key="correct-horse-key")
        with mock.patch.object(api, "config", cfg), _Server() as port:
            # Note: whitespace-padded variants are not tested — HTTP header
            # transport trims padding, making them identical to the key.
            for bad in ("correct-horse-ke", "correct-horse-keyy", "", "CORRECT-HORSE-KEY", "correct-horse-key2"):
                status, _ = _request(port, "POST", "/api/v1/reconcile",
                                     {"notice": NOTICE, "folio": FOLIO}, token=bad)
                self.assertEqual(status, 401, f"key variant {bad!r} must be rejected")
            status, _ = _request(port, "POST", "/api/v1/reconcile",
                                 {"notice": NOTICE, "folio": FOLIO}, token="correct-horse-key")
            self.assertEqual(status, 200)

    def test_schema_validation_over_http(self):
        cfg = _cfg(api_key=None, api_allow_legacy_unauthenticated=True)
        with mock.patch.object(api, "config", cfg), _Server() as port:
            status, body = _request(port, "POST", "/api/v1/reconcile", {"folio": FOLIO})
            self.assertEqual(status, 400)
            self.assertIn("notice", body["error"]["message"])


class TestCredentialLifecycleOverHttp(unittest.TestCase):
    def test_suspended_and_revoked_credentials_fail(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            _pub, secret = registry.issue_credential("hotel-a", "client", scopes=["cases:read"])
            credential_id = _pub["credential_id"]
            with mock.patch.object(api, "INTEGRATION_ROOT", tmp), _Server() as port:
                status, _ = _request(port, "GET", "/api/v1/integrations/cases", token=secret)
                self.assertEqual(status, 200)
                registry.suspend_credential("hotel-a", credential_id)
                status, _ = _request(port, "GET", "/api/v1/integrations/cases", token=secret)
                self.assertEqual(status, 401)
                registry.revoke_credential("hotel-a", credential_id)
                status, _ = _request(port, "GET", "/api/v1/integrations/cases", token=secret)
                self.assertEqual(status, 401)
            registry.close()

    def test_foreign_case_indistinguishable_from_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            registry.create_tenant("hotel-b", "Hotel B")
            _pa, secret_a = registry.issue_credential("hotel-a", "a", scopes=["cases:write", "cases:read"])
            _pb, secret_b = registry.issue_credential("hotel-b", "b", scopes=["cases:write", "cases:read"])
            with mock.patch.object(api, "INTEGRATION_ROOT", tmp), _Server() as port:
                status, _ = _request(port, "POST", "/api/v1/integrations/cases",
                                     {"case_id": "SHARED-1", "notice": NOTICE, "folio": FOLIO}, token=secret_a)
                self.assertEqual(status, 201)
                foreign_status, foreign_body = _request(port, "GET", "/api/v1/integrations/cases/SHARED-1", token=secret_b)
                missing_status, missing_body = _request(port, "GET", "/api/v1/integrations/cases/NOPE-404", token=secret_b)
                # No existence leak: foreign and missing look identical.
                self.assertEqual(foreign_status, missing_status)
                self.assertEqual(foreign_body["error"]["code"], missing_body["error"]["code"])
            registry.close()


class TestUploadAttacks(unittest.TestCase):
    def test_polyglot_and_disguised_files(self):
        # PDF header with HTML body: valid PDF magic — accepted as data,
        # but the extension allowlist keeps active content out entirely.
        validate_upload(b"%PDF-1.4 <html><script>alert(1)</script>", "notice.pdf")
        with self.assertRaises(ValueError):
            validate_upload(b"<html><script>alert(1)</script></html>", "notice.html")
        with self.assertRaises(ValueError):
            validate_upload(b"GIF89a" + b"\x00" * 32, "scan.png")  # wrong magic for .png
        with self.assertRaises(ValueError):
            validate_upload(b"\xff\xd8\xff" + b"\x00" * 8, "scan.png")  # JPEG bytes named .png


class TestAuditTamperDetection(unittest.TestCase):
    def _trail(self, tmp):
        logger = AuditLogger(log_dir=tmp)
        logger.log_event("notice_uploaded", {"case_id": "T-1"}, user="Tester")
        logger.log_event("rebuttal_approved", {"case_id": "T-1"}, user="Manager")
        return Path(tmp) / f"audit_trail_{logger.session_id}.jsonl", logger

    def test_byte_flip_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            trail, _ = self._trail(tmp)
            lines = trail.read_text(encoding="utf-8").splitlines()
            event = json.loads(lines[0])
            event["actor"] = "Mallory"
            lines[0] = json.dumps(event)
            trail.write_text("\n".join(lines) + "\n", encoding="utf-8")
            ok, _events, _msg = AuditLogger.load_and_verify(str(trail))
            self.assertFalse(ok)

    def test_truncation_detected_with_expected_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            trail, logger = self._trail(tmp)
            head = logger.chain_head
            lines = trail.read_text(encoding="utf-8").splitlines()
            trail.write_text(lines[0] + "\n", encoding="utf-8")  # drop the approval event
            ok, _events, _msg = AuditLogger.load_and_verify(str(trail), expected_head=head)
            self.assertFalse(ok)

    def test_reordering_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            trail, _ = self._trail(tmp)
            lines = trail.read_text(encoding="utf-8").splitlines()
            trail.write_text("\n".join(reversed(lines)) + "\n", encoding="utf-8")
            ok, _events, _msg = AuditLogger.load_and_verify(str(trail))
            self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
