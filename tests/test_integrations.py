"""
Enterprise API integration tests (Phase 2).

Covers tenant credentials, authentication, revocation, tenant isolation,
integration service processing through the existing engine, and SDK HTTP
client behavior with a fake session (no network calls).
"""

import tempfile
import unittest

from core.client import FolioShieldHTTPClient
from core.integrations.contracts import IntegrationCaseRef, TenantContext
from core.integrations.registry import IntegrationRegistry
from core.integrations.service import IntegrationService
from data.sample_scenarios import SCENARIOS


class FakeResponse:
    def __init__(self, status_code=200, data=None):
        self.status_code = status_code
        self._data = data or {"status": "success", "data": {}}

    def json(self):
        return self._data


class FakeSession:
    def __init__(self):
        self.calls = []
        self.responses = [FakeResponse(503, {"error": {"message": "busy"}}), FakeResponse(200, {"status": "success", "data": {"ok": True}})]

    def request(self, method, url, json=None, headers=None, timeout=None):
        self.calls.append({"method": method, "url": url, "json": json, "headers": headers})
        return self.responses.pop(0)


class TestEnterpriseIntegrations(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = IntegrationRegistry(root=self.tmp.name)
        self.registry.create_tenant("hotel-a", "Hotel A", property_ids=["prop-a"])
        self.registry.create_tenant("hotel-b", "Hotel B", property_ids=["prop-b"])
        self.public_a, self.secret_a = self.registry.issue_credential(
            "hotel-a", "API client A", scopes=["cases:write", "cases:read", "cases:process", "documents:write", "audit:read", "packets:generate"],
            property_ids=["prop-a"])
        self.public_b, self.secret_b = self.registry.issue_credential(
            "hotel-b", "API client B", scopes=["cases:write", "cases:read", "cases:process", "documents:write"],
            property_ids=["prop-b"])

    def tearDown(self):
        self.registry.close()
        self.tmp.cleanup()

    def test_credential_authentication_and_revocation(self):
        principal = self.registry.authenticate(self.secret_a)
        self.assertIsNotNone(principal)
        self.assertEqual(principal.tenant_id, "hotel-a")
        self.assertNotIn("secret_hash", self.public_a)

        self.assertTrue(self.registry.revoke_credential("hotel-a", self.public_a["credential_id"]))
        self.assertIsNone(self.registry.authenticate(self.secret_a))

    def test_wrong_tenant_cannot_revoke_or_access_case(self):
        self.assertFalse(self.registry.revoke_credential("hotel-b", self.public_a["credential_id"]))
        ctx_a = TenantContext(tenant_id="hotel-a", actor_id="a", scopes=["cases:write", "cases:read"])
        service = IntegrationService(registry=self.registry)
        service.create_case(ctx_a, IntegrationCaseRef(tenant_id="hotel-a", case_id="CASE-1", external_case_id="EXT-1"))
        self.assertIsNotNone(self.registry.get_case("hotel-a", "CASE-1"))
        self.assertIsNone(self.registry.get_case("hotel-b", "CASE-1"))

    def test_service_reuses_existing_engine_and_does_not_approve(self):
        scenario = SCENARIOS["visa_fraud_10_4"]
        ctx = TenantContext(tenant_id="hotel-a", actor_id="api-test", scopes=["cases:write", "cases:read", "cases:process"])
        service = IntegrationService(registry=self.registry)
        service.create_case(ctx, IntegrationCaseRef(tenant_id="hotel-a", case_id=scenario["notice"]["case_id"]),
                            notice=scenario["notice"], folio=scenario["folio"])
        result = service.process_case(ctx, scenario["notice"]["case_id"])
        self.assertEqual(result["status"], "rebuttal_drafted")
        self.assertIsNone(result["approval"])
        self.assertTrue(result["human_approval_required"])
        self.assertIn("EXECUTIVE SUMMARY", result["rebuttal_text"])

    def test_scope_enforcement(self):
        ctx = TenantContext(tenant_id="hotel-a", actor_id="limited", scopes=["cases:read"])
        service = IntegrationService(registry=self.registry)
        with self.assertRaises(PermissionError):
            service.create_case(ctx, IntegrationCaseRef(tenant_id="hotel-a", case_id="CASE-2"))

    def test_http_client_retries_and_sends_auth(self):
        session = FakeSession()
        client = FolioShieldHTTPClient("https://example.test", "fs_test.secret", session=session, max_retries=3)
        result = client.monitoring()
        self.assertEqual(result["data"], {"ok": True})
        self.assertEqual(len(session.calls), 2)
        self.assertTrue(session.calls[0]["headers"]["Authorization"].startswith("Bearer "))
        self.assertIn("X-Request-Id", session.calls[0]["headers"])

    def test_upload_document_retains_bytes_in_exhibit_store(self):
        ctx = TenantContext(tenant_id="hotel-a", actor_id="uploader", scopes=["cases:write", "documents:write"])
        service = IntegrationService(registry=self.registry)
        service.create_case(ctx, IntegrationCaseRef(tenant_id="hotel-a", case_id="CASE-EXHIBIT-1"))
        fake_pdf = b"%PDF-1.4 test folio evidence content\n%%EOF\n"
        upload_res = service.upload_document(
            ctx,
            case_id="CASE-EXHIBIT-1",
            document_type="supporting_evidence",
            filename="registration_card.pdf",
            media_type="application/pdf",
            data=fake_pdf,
            evidence_doc_type="signed_registration_card",
        )
        stored_ref = upload_res["document"]["stored_ref"]
        self.assertIsNotNone(stored_ref)
        retained = service.exhibit_store.get(stored_ref, filename="registration_card.pdf")
        self.assertEqual(retained, fake_pdf)


if __name__ == "__main__":
    unittest.main()
