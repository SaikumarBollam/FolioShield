"""
Embedded integration support for FolioShield.

Embedded mode uses short-lived, HMAC-signed context tokens validated
server-side. Browser/host JavaScript may transport a token, but tenant,
property, user, roles, and permissions are trusted only after signature,
expiry, issuer, audience, and origin checks pass.

This module does not claim production OIDC/SSO. A real identity provider
integration requires vendor/IdP validation with issuer/JWKS configuration.
"""

from .context import EmbeddedContext, create_context_token, validate_context_token
from .configuration import EmbeddedConfiguration
from .theme import HostTheme

__all__ = ["EmbeddedContext", "EmbeddedConfiguration", "HostTheme", "create_context_token", "validate_context_token"]
