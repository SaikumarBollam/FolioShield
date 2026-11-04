"""
API authentication tests for enterprise integration routes.

These tests exercise handler helpers without opening a network port. Full
HTTP behavior remains covered by the existing API dispatch test for legacy
endpoints.
"""

import tempfile
import unittest

from core.integrations.registry import IntegrationRegistry


class TestAPIAuthentication(unittest.TestCase):

    def test_registry_backed_bearer_authentication(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            _public, secret = registry.issue_credential("hotel-a", "client", scopes=["cases:read"])
            principal = registry.authenticate(secret)
            self.assertIsNotNone(principal)
            context = principal.to_context(request_id="req-1")
            self.assertEqual(context.tenant_id, "hotel-a")
            self.assertEqual(context.request_id, "req-1")
            self.assertTrue(context.has_scope("cases:read"))
            self.assertFalse(context.has_scope("cases:write"))
            registry.close()

    def test_tenant_suspension_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            _public, secret = registry.issue_credential("hotel-a", "client", scopes=["cases:read"])
            self.assertTrue(registry.set_tenant_status("hotel-a", "suspended"))
            self.assertIsNone(registry.authenticate(secret))
            registry.close()


if __name__ == "__main__":
    unittest.main()
