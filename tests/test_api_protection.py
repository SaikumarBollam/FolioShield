"""Tests: Phase 1 P0 API protection (auth gate, health, rate limit, approval)."""

import dataclasses
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

import core.api as api
from core.config import config as app_config


def _cfg(**overrides):
    """A Settings copy with test overrides (Settings is frozen)."""
    return dataclasses.replace(app_config, **overrides)

NOTICE = {"case_id": "CB-1", "card_network": "Visa", "reason_code": "10.4",
          "disputed_amount": 100.0, "original_amount": 100.0, "currency": "USD",
          "cardholder_name": "Test Guest", "card_last_4": "4821",
          "transaction_date": "2026-10-10", "dispute_date": "2026-11-02"}
FOLIO = {"guest_name": "Test Guest", "card_last_4": "4821", "check_in": "2026-10-10",
         "check_out": "2026-10-11", "stay_status": "occupied",
         "total_charges": 100.0, "total_payments": 100.0, "line_items": []}


def _request(port, method, path, payload=None, token=None):
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    conn.request(method, path, json.dumps(payload or {}), headers)
    resp = conn.getresponse()
    body = resp.read().decode("utf-8")
    conn.close()
    return resp.status, json.loads(body) if body else {}


class _Server:
    def __enter__(self):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), api.FolioShieldAPIHandler)
        self.port = self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        return self.port

    def __exit__(self, *exc):
        self.httpd.shutdown()
        self.httpd.server_close()


class TestApiProtection(unittest.TestCase):
    def test_health_is_public_and_minimal_without_credentials(self):
        with mock.patch.object(api, "config", _cfg(api_key="secret-key-123")), _Server() as port:
            status, body = _request(port, "GET", "/api/v1/health")
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "healthy")
            self.assertNotIn("environment", body)
            self.assertNotIn("provider", body)
            status, body = _request(port, "GET", "/api/v1/health", token="secret-key-123")
            self.assertEqual(status, 200)
            self.assertIn("environment", body)

    def test_legacy_endpoint_requires_key_when_configured(self):
        with mock.patch.object(api, "config", _cfg(api_key="secret-key-123")), _Server() as port:
            status, _ = _request(port, "POST", "/api/v1/reconcile", {"notice": NOTICE, "folio": FOLIO})
            self.assertEqual(status, 401)
            status, _ = _request(port, "POST", "/api/v1/reconcile", {"notice": NOTICE, "folio": FOLIO}, token="wrong")
            self.assertEqual(status, 401)
            status, body = _request(port, "POST", "/api/v1/reconcile", {"notice": NOTICE, "folio": FOLIO}, token="secret-key-123")
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "success")

    def test_production_without_key_fails_closed(self):
        with mock.patch.object(api, "config", _cfg(api_key=None, api_allow_legacy_unauthenticated=False)), _Server() as port:
            status, body = _request(port, "POST", "/api/v1/reconcile", {"notice": NOTICE, "folio": FOLIO})
            self.assertEqual(status, 401)
            self.assertIn("FOLIOSHIELD_API_KEY", body["error"]["message"])

    def test_rate_limit_trips(self):
        limiter = api._RateLimiter(per_minute=3)
        with mock.patch.object(api, "_RATE_LIMITER", limiter), _Server() as port:
            _request(port, "GET", "/api/v1/health")  # health is exempt from limiting
            with mock.patch.object(api, "config", _cfg(api_key=None, api_allow_legacy_unauthenticated=True)):
                codes = [_request(port, "POST", "/api/v1/reconcile", {"notice": NOTICE, "folio": FOLIO})[0] for _ in range(5)]
            self.assertIn(429, codes)

    def test_packet_without_approval_is_draft_and_forged_approval_rejected(self):
        with mock.patch.object(api, "config", _cfg(api_key=None, api_allow_legacy_unauthenticated=True)), _Server() as port:
            status, body = _request(port, "POST", "/api/v1/packet/generate",
                                    {"notice": NOTICE, "folio": FOLIO, "rebuttal_text": "Draft text.",
                                     "approved_by": "Forged Name"})
            self.assertEqual(status, 200)
            self.assertEqual(body["approval_status"], "draft_pending_human_approval")
            self.assertTrue(body["human_approval_required"])

            status, body = _request(port, "POST", "/api/v1/packet/generate",
                                    {"notice": NOTICE, "folio": FOLIO, "rebuttal_text": "Draft text.",
                                     "approval": {"approved_by": "Forged Name", "fingerprint": "f" * 64}})
            self.assertEqual(status, 409)
            self.assertEqual(body["error"]["code"], "approval_stale")

    def test_approve_then_packet_approved(self):
        with mock.patch.object(api, "config", _cfg(api_key=None, api_allow_legacy_unauthenticated=True)), _Server() as port:
            status, body = _request(port, "POST", "/api/v1/dispute/process",
                                    {"notice": NOTICE, "folio": FOLIO})
            self.assertEqual(status, 200)
            data = body["data"]
            self.assertIsNone(data["approval"])
            self.assertTrue(data["human_approval_required"])

            status, body = _request(port, "POST", "/api/v1/dispute/approve",
                                    {"notice": NOTICE, "folio": FOLIO,
                                     "rebuttal_text": data["rebuttal_text"], "approved_by": "Duty Manager"})
            self.assertEqual(status, 200)
            approval = body["data"]
            self.assertEqual(approval["fingerprint"], data["approval_fingerprint"])

            status, body = _request(port, "POST", "/api/v1/packet/generate",
                                    {"notice": NOTICE, "folio": FOLIO,
                                     "rebuttal_text": data["rebuttal_text"], "approval": approval})
            self.assertEqual(status, 200)
            self.assertEqual(body["approval_status"], "approved")
            self.assertFalse(body["human_approval_required"])


if __name__ == "__main__":
    unittest.main()

