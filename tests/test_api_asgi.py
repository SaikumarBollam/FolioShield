"""
Tests for production ASGI REST API (FastAPI) implementation.
"""

import dataclasses
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import pytest

pytest.importorskip("fastapi")
pytest.importorskip("starlette")
from starlette.testclient import TestClient

from core.api_asgi import create_app
from core.config import config
from core.integrations.registry import IntegrationRegistry


def _cfg(**overrides):
    return dataclasses.replace(config, **overrides)


class TestAsgiApi(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.client = TestClient(self.app)

    def test_health_endpoints_public_and_return_request_id(self):
        resp1 = self.client.get("/health")
        self.assertEqual(resp1.status_code, 200)
        data1 = resp1.json()
        self.assertEqual(data1["status"], "healthy")
        self.assertIn("request_id", data1)
        self.assertIn("X-Request-Id", resp1.headers)

        resp2 = self.client.get("/api/v1/health")
        self.assertEqual(resp2.status_code, 200)
        data2 = resp2.json()
        self.assertEqual(data2["status"], "healthy")

    def test_liveness_and_readiness_checks(self):
        live_resp = self.client.get("/health/liveness")
        self.assertEqual(live_resp.status_code, 200)
        self.assertEqual(live_resp.json()["status"], "alive")

        ready_resp = self.client.get("/health/readiness")
        self.assertEqual(ready_resp.status_code, 200)
        ready_data = ready_resp.json()
        self.assertEqual(ready_data["status"], "ready")
        self.assertIn("database", ready_data)
        self.assertIn("storage", ready_data)

    def test_unauthenticated_request_rejected_in_production(self):
        payload = {
            "notice": {
                "case_id": "CB-TEST-001",
                "card_network": "Visa",
                "reason_code": "10.4",
                "disputed_amount": 100.0,
            },
            "folio": {
                "guest_name": "John Doe",
                "total_charges": 100.0,
            },
        }
        resp = self.client.post("/api/v1/reconcile", json=payload)
        self.assertEqual(resp.status_code, 401)
        self.assertEqual(resp.json()["detail"]["code"], "unauthorized")

    def test_authenticated_endpoints_with_valid_key(self):
        payload = {
            "notice": {
                "case_id": "CB-TEST-002",
                "card_network": "Visa",
                "reason_code": "10.4",
                "disputed_amount": 200.0,
            },
            "folio": {
                "guest_name": "Jane Smith",
                "total_charges": 200.0,
            },
        }
        with mock.patch("core.api_asgi.config", _cfg(api_key="secret-test-key")):
            headers = {"Authorization": "Bearer secret-test-key"}

            # Reconcile
            resp = self.client.post("/api/v1/reconcile", json=payload, headers=headers)
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "success")
            self.assertIn("completeness_score", data["data"])

            # Draft
            draft_resp = self.client.post("/api/v1/rebuttal/draft", json=payload, headers=headers)
            self.assertEqual(draft_resp.status_code, 200)
            draft_data = draft_resp.json()
            self.assertEqual(draft_data["status"], "success")
            rebuttal_text = draft_data["data"]["rebuttal_text"]
            self.assertTrue(len(rebuttal_text) > 0)

            # Approve without reviewer fails
            fail_approve = self.client.post("/api/v1/rebuttal/approve", json={
                "notice": payload["notice"],
                "folio": payload["folio"],
                "rebuttal_text": rebuttal_text,
                "approved_by": "",
            }, headers=headers)
            self.assertEqual(fail_approve.status_code, 400)

            # Approve with reviewer succeeds
            succ_approve = self.client.post("/api/v1/rebuttal/approve", json={
                "notice": payload["notice"],
                "folio": payload["folio"],
                "rebuttal_text": rebuttal_text,
                "approved_by": "Night Auditor Mike",
            }, headers=headers)
            self.assertEqual(succ_approve.status_code, 200)
            app_data = succ_approve.json()
            self.assertEqual(app_data["status"], "success")
            self.assertEqual(app_data["data"]["approved_by"], "Night Auditor Mike")
            self.assertIn("fingerprint", app_data["data"])

            # Process dispute end-to-end
            proc_resp = self.client.post("/api/v1/dispute/process", json={
                "notice": payload["notice"],
                "folio": payload["folio"],
                "reviewer_name": "Auditor Bob",
            }, headers=headers)
            self.assertEqual(proc_resp.status_code, 200)
            proc_data = proc_resp.json()
            self.assertEqual(proc_data["status"], "success")
            self.assertIn("rebuttal_text", proc_data["data"])

    def test_wrong_key_rejected(self):
        with mock.patch("core.api_asgi.config", _cfg(api_key="secret-test-key")):
            headers = {"Authorization": "Bearer wrong-key"}
            resp = self.client.post("/api/v1/reconcile", json={}, headers=headers)
            self.assertEqual(resp.status_code, 403)
            self.assertEqual(resp.json()["detail"]["code"], "forbidden")

    def test_integration_endpoints_with_tenant_credentials(self):
        tmp_dir = tempfile.TemporaryDirectory()
        try:
            reg_root = str(Path(tmp_dir.name) / "reg")
            registry = IntegrationRegistry(root=reg_root)
            registry.create_tenant("hotel-asgi-1", "Hotel ASGI", property_ids=["prop-1"])
            _cred_info, secret = registry.issue_credential("hotel-asgi-1", "admin-key", scopes=["cases:read", "cases:write"])

            with mock.patch("core.api_asgi.config", _cfg(integration_root=reg_root)):
                headers = {"Authorization": f"Bearer {secret}"}

                # List cases
                list_resp = self.client.get("/api/v1/integrations/cases", headers=headers)
                self.assertEqual(list_resp.status_code, 200)
                self.assertEqual(list_resp.json()["status"], "success")

                # Create case
                case_payload = {
                    "case_id": "CB-INT-101",
                    "notice": {"disputed_amount": 350.0},
                    "folio": {"guest_name": "Sam Porter"},
                }
                create_resp = self.client.post("/api/v1/integrations/cases", json=case_payload, headers=headers)
                self.assertEqual(create_resp.status_code, 201)
                self.assertEqual(create_resp.json()["status"], "success")

                # Get case
                get_resp = self.client.get("/api/v1/integrations/cases/CB-INT-101", headers=headers)
                self.assertEqual(get_resp.status_code, 200)
                self.assertEqual(get_resp.json()["data"]["case_id"], "CB-INT-101")
        finally:
            registry.close()
            import gc
            gc.collect()
            try:
                tmp_dir.cleanup()
            except OSError:
                pass


if __name__ == "__main__":
    unittest.main()
