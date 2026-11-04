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

    def test_host_theme_validation_and_fallback(self):
        from embedded.theme import DEFAULT_THEME, HostTheme

        default = HostTheme.from_dict(None)
        self.assertEqual(default.primary_color, DEFAULT_THEME["primary_color"])
        self.assertEqual(default.brand_name, "FolioShield")

        themed = HostTheme.from_dict({
            "primary_color": "#7C3AED", "accent_color": "#06B6D4",
            "brand_name": "Azure Palms Hotels", "logo_url": "https://cdn.example.com/logo.png",
            "font_family": "Georgia, serif", "border_radius": "10px",
        })
        self.assertEqual(themed.primary_color, "#7C3AED")
        self.assertEqual(themed.brand_name, "Azure Palms Hotels")
        self.assertIn("--fs-primary: #7C3AED", themed.css())

        # Invalid / dangerous values fall back to defaults, never into CSS.
        hostile = HostTheme.from_dict({
            "primary_color": "red; } body { display:none",
            "font_family": "x; } <script>alert(1)</script>",
            "logo_url": "javascript:alert(1)",
            "brand_name": "A" * 200,
        })
        self.assertEqual(hostile.primary_color, DEFAULT_THEME["primary_color"])
        self.assertEqual(hostile.font_family, DEFAULT_THEME["font_family"])
        self.assertEqual(hostile.logo_url, "")
        self.assertNotIn("<script>", hostile.css())
        self.assertNotIn("javascript:", hostile.css())

    def test_theme_precedence_context_over_env_over_default(self):
        config = EmbeddedConfiguration(enabled=True, branding={"primary_color": "#111111", "brand_name": "Env Brand"})
        env_theme = config.resolve_theme()
        self.assertEqual(env_theme.primary_color, "#111111")
        ctx_theme = config.resolve_theme({"primary_color": "#222222"})
        self.assertEqual(ctx_theme.primary_color, "#222222")
        self.assertEqual(ctx_theme.brand_name, "Env Brand")  # env fills gaps

    def test_theme_travels_inside_signed_context(self):
        ctx = EmbeddedContext(tenant_id="hotel-a", user_id="u-1",
                              theme={"primary_color": "#0F766E", "brand_name": "Host Brand"})
        token = create_context_token(ctx, self.secret)
        validated = validate_context_token(token, self.secret)
        self.assertEqual(validated.theme["primary_color"], "#0F766E")
        self.assertEqual(validated.theme["brand_name"], "Host Brand")


if __name__ == "__main__":
    unittest.main()
