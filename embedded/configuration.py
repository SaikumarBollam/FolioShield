"""
Embedded configuration: views, branding, origins, and message protocol.

No secrets belong in this configuration object. Signing secrets and API
credentials stay server-side.
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List

EMBEDDED_VIEWS = (
    "dashboard",
    "dispute_status",
    "document_upload",
    "evidence_completeness",
    "reconciliation_results",
    "rebuttal_review",
    "packet_download",
    "integration_health",
)

# Secure host <-> iframe message types. Messages must be origin-checked and
# must never contain API secrets, raw PANs, or full guest PII.
POSTMESSAGE_SCHEMA: Dict[str, Dict[str, Any]] = {
    "folioshield.ready": {"direction": "iframe->host", "fields": ["view", "session_id"]},
    "folioshield.navigate": {"direction": "host->iframe", "fields": ["view", "case_id"]},
    "folioshield.caseSelected": {"direction": "iframe->host", "fields": ["case_id"]},
    "folioshield.statusChanged": {"direction": "iframe->host", "fields": ["case_id", "status"]},
    "folioshield.resize": {"direction": "iframe->host", "fields": ["height"]},
}


@dataclass
class EmbeddedConfiguration:
    enabled: bool = False
    signing_secret_env: str = "FOLIOSHIELD_EMBEDDED_SECRET"
    issuer: str = "folioshield-embedded"
    audience: str = "hotel-host"
    allowed_origins: List[str] = field(default_factory=list)
    default_view: str = "dashboard"
    branding: Dict[str, str] = field(default_factory=dict)
    token_ttl_seconds: int = 600

    @property
    def signing_secret(self) -> str:
        return os.getenv(self.signing_secret_env, "")

    def validate_view(self, view: str) -> str:
        return view if view in EMBEDDED_VIEWS else self.default_view

    def frame_ancestors(self) -> str:
        origins = self.allowed_origins or ["'none'"]
        return "frame-ancestors " + " ".join(origins)

    def content_security_policy(self) -> str:
        return "; ".join([
            "default-src 'self'",
            "object-src 'none'",
            "base-uri 'self'",
            self.frame_ancestors(),
        ])

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["frame_ancestors"] = self.frame_ancestors()
        data["content_security_policy"] = self.content_security_policy()
        return data

    @classmethod
    def from_env(cls) -> "EmbeddedConfiguration":
        origins = [o.strip() for o in os.getenv("FOLIOSHIELD_EMBEDDED_ALLOWED_ORIGINS", "").split(",") if o.strip()]
        branding = {}
        # Server-side default host theme (used when the signed context
        # carries no theme). Hosts may override per-session via the token.
        for env_key, theme_key in (
            ("FOLIOSHIELD_THEME_PRIMARY_COLOR", "primary_color"),
            ("FOLIOSHIELD_THEME_ACCENT_COLOR", "accent_color"),
            ("FOLIOSHIELD_THEME_BACKGROUND_COLOR", "background_color"),
            ("FOLIOSHIELD_THEME_TEXT_COLOR", "text_color"),
            ("FOLIOSHIELD_THEME_FONT_FAMILY", "font_family"),
            ("FOLIOSHIELD_THEME_BRAND_NAME", "brand_name"),
            ("FOLIOSHIELD_THEME_LOGO_URL", "logo_url"),
        ):
            value = os.getenv(env_key, "").strip()
            if value:
                branding[theme_key] = value
        return cls(
            enabled=os.getenv("FOLIOSHIELD_EMBEDDED_ENABLED", "false").lower() in ("1", "true", "yes"),
            allowed_origins=origins,
            default_view=os.getenv("FOLIOSHIELD_EMBEDDED_DEFAULT_VIEW", "dashboard"),
            branding=branding,
        )

    def resolve_theme(self, context_theme: Optional[Dict[str, str]] = None):
        """Theme precedence: signed host context > server env defaults > FolioShield default."""
        from .theme import HostTheme

        merged: Dict[str, str] = {}
        merged.update(self.branding or {})
        if context_theme:
            merged.update({k: v for k, v in context_theme.items() if v})
        return HostTheme.from_dict(merged)
