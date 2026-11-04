"""
Embedded integration tests (Phase 4).

Signed context is validated server-side. Tampered, expired, wrong-audience,
and non-allowlisted-origin contexts must fail closed.
"""

import time
import unittest

from embedded.configuration import EmbeddedConfiguration
from embedded.context import EmbeddedContext, create_context_token, validate_context_token


class TestEmbeddedIntegration(unittest.TestCase):

    def setUp(self):
        self.secret = "test-signing-secret-not-for-production"
        self.context = EmbeddedContext(
            tenant_id="hotel-a", user_id="user-123", property_id="prop-a",
            case_id="CASE-1", roles=["dispute_manager"], scopes=["cases:read"], view="rebuttal_review")

    def test_valid_signed_context(self):
        token = create_context_token(self.context, self.secret, ttl_seconds=600)
        validated = validate_context_token(token, self.secret, allowed_origins=["https://host.example"], origin="https://host.example")
        self.assertEqual(validated.tenant_id, "hotel-a")
        self.assertEqual(validated.user_id, "user-123")
        self.assertEqual(validated.case_id, "CASE-1")

    def test_tampered_context_rejected(self):
        token = create_context_token(self.context, self.secret)
        parts = token.split(".")
        tampered = f"{parts[0]}.{parts[1][::-1]}.{parts[2]}"
        with self.assertRaises(PermissionError):
            validate_context_token(tampered, self.secret)

    def test_expired_context_rejected(self):
        token = create_context_token(self.context, self.secret, ttl_seconds=-10)
        with self.assertRaises(PermissionError):
            validate_context_token(token, self.secret)

    def test_wrong_audience_and_origin_rejected(self):
        token = create_context_token(self.context, self.secret, audience="hotel-host")
        with self.assertRaises(PermissionError):
            validate_context_token(token, self.secret, audience="other-host")
        with self.assertRaises(PermissionError):
            validate_context_token(token, self.secret, allowed_origins=["https://allowed.example"], origin="https://evil.example")

    def test_configuration_views_and_csp(self):
        config = EmbeddedConfiguration(enabled=True, allowed_origins=["https://host.example"])
        self.assertEqual(config.validate_view("rebuttal_review"), "rebuttal_review")
        self.assertEqual(config.validate_view("not-a-view"), "dashboard")
        self.assertIn("frame-ancestors https://host.example", config.content_security_policy())
        self.assertIn("object-src 'none'", config.content_security_policy())


if __name__ == "__main__":
    unittest.main()
