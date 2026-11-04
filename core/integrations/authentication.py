"""
Authentication and credential lifecycle helpers.

Design rules:
- Raw API secrets are shown once at issuance and never stored.
- Stored credentials are salted PBKDF2-HMAC-SHA256 hashes.
- Every credential belongs to exactly one tenant.
- Revoked/expired credentials fail closed.
- This module does not implement OIDC; identity-provider validation is a
  separate, vendor-validated step.
"""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_PBKDF2_ITERATIONS = 210_000


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _parse_iso(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hash_secret(secret: str, salt: Optional[bytes] = None) -> Dict[str, str]:
    salt = salt or os.urandom(16)
    digest = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, _PBKDF2_ITERATIONS)
    return {"salt": salt.hex(), "hash": digest.hex(), "iterations": str(_PBKDF2_ITERATIONS)}


def verify_secret(secret: str, stored: Dict[str, Any]) -> bool:
    try:
        salt = bytes.fromhex(str(stored.get("salt") or ""))
        expected = str(stored.get("hash") or "")
        iterations = int(stored.get("iterations") or _PBKDF2_ITERATIONS)
    except (TypeError, ValueError):
        return False
    if not salt or not expected:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", secret.encode("utf-8"), salt, iterations).hex()
    return hmac.compare_digest(actual, expected)


def generate_api_key(prefix: str = "fs") -> tuple[str, str]:
    """Return (credential_id, raw_secret). Raw secret must be shown once only."""
    credential_id = f"{prefix}_{secrets.token_hex(8)}"
    raw_secret = f"{credential_id}.{secrets.token_urlsafe(32)}"
    return credential_id, raw_secret


@dataclass
class CredentialRecord:
    credential_id: str
    tenant_id: str
    label: str
    secret_hash: Dict[str, str]
    scopes: List[str] = field(default_factory=list)
    actor_type: str = "api_client"
    actor_id: Optional[str] = None
    property_ids: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    status: str = "active"  # active / suspended / revoked
    created_at: str = field(default_factory=lambda: _utc_now().isoformat())
    expires_at: Optional[str] = None
    last_used_at: Optional[str] = None
    revoked_at: Optional[str] = None

    def is_usable(self, now: Optional[datetime] = None) -> bool:
        if self.status != "active":
            return False
        expires = _parse_iso(self.expires_at)
        return not (expires and (now or _utc_now()) >= expires)

    def public_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data.pop("secret_hash", None)
        return data

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CredentialRecord":
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class AuthenticatedPrincipal:
    tenant_id: str
    actor_id: str
    actor_type: str
    credential_id: str
    scopes: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    property_ids: List[str] = field(default_factory=list)

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "*" in self.scopes

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise PermissionError(f"Missing required scope: {scope}")

    def to_context(self, request_id: Optional[str] = None) -> Any:
        import uuid

        from .contracts import TenantContext

        return TenantContext(
            tenant_id=self.tenant_id,
            actor_id=self.actor_id,
            actor_type=self.actor_type,
            property_ids=list(self.property_ids),
            roles=list(self.roles),
            scopes=list(self.scopes),
            request_id=request_id or str(uuid.uuid4()),
            credential_id=self.credential_id,
        )


def parse_bearer_token(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None
    parts = header_value.strip().split(None, 1)
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None
    return parts[1].strip() or None


def credential_id_from_secret(raw_secret: str) -> Optional[str]:
    if not raw_secret or "." not in raw_secret:
        return None
    return raw_secret.split(".", 1)[0] or None
