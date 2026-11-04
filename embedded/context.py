"""
Signed embedded context tokens.

Token format: base64url(header).base64url(payload).base64url(HMAC-SHA256)

Required claims:
- iss: FolioShield embedded issuer configured by the deployment
- aud: host application audience
- tenant_id, user_id
- exp, iat

Optional minimized context:
- property_id, case_id, folio_reference, transaction_reference
- roles, scopes, view, branding_id

The secret must come from server-side environment/configuration. Never
embed the signing secret in browser code.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode((value + padding).encode("utf-8"))


def _sign(secret: str, signing_input: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    return _b64encode(digest)


@dataclass
class EmbeddedContext:
    tenant_id: str
    user_id: str
    property_id: Optional[str] = None
    case_id: Optional[str] = None
    folio_reference: Optional[str] = None
    transaction_reference: Optional[str] = None
    roles: List[str] = field(default_factory=list)
    scopes: List[str] = field(default_factory=list)
    view: str = "dashboard"
    branding_id: Optional[str] = None
    theme: Dict[str, Any] = field(default_factory=dict)  # host theme (validated by embedded.theme.HostTheme)
    session_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    expires_at: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EmbeddedContext":
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


def create_context_token(context: EmbeddedContext, secret: str, issuer: str = "folioshield-embedded",
                         audience: str = "hotel-host", ttl_seconds: int = 600) -> str:
    if not secret:
        raise ValueError("Embedded signing secret is not configured")
    now = int(time.time())
    payload = context.to_dict()
    payload.update({"iss": issuer, "aud": audience, "iat": now, "exp": now + ttl_seconds})
    header = {"alg": "HS256", "typ": "FolioShieldEmbeddedContext"}
    signing_input = f"{_b64encode(json.dumps(header, separators=(',', ':')).encode())}.{_b64encode(json.dumps(payload, separators=(',', ':'), default=str).encode())}"
    return f"{signing_input}.{_sign(secret, signing_input)}"


def validate_context_token(token: str, secret: str, issuer: str = "folioshield-embedded",
                           audience: str = "hotel-host", allowed_origins: Optional[List[str]] = None,
                           origin: Optional[str] = None) -> EmbeddedContext:
    if not secret:
        raise PermissionError("Embedded signing secret is not configured")
    if allowed_origins is not None:
        if not origin or origin not in allowed_origins:
            raise PermissionError("Embedded origin is not allowlisted")
    parts = (token or "").split(".")
    if len(parts) != 3:
        raise PermissionError("Invalid embedded context token")
    signing_input = f"{parts[0]}.{parts[1]}"
    expected = _sign(secret, signing_input)
    if not hmac.compare_digest(expected, parts[2]):
        raise PermissionError("Invalid embedded context signature")
    try:
        header = json.loads(_b64decode(parts[0]))
        payload = json.loads(_b64decode(parts[1]))
    except Exception as exc:
        raise PermissionError("Invalid embedded context payload") from exc
    if header.get("alg") != "HS256":
        raise PermissionError("Unsupported embedded token algorithm")
    now = int(time.time())
    if int(payload.get("exp") or 0) <= now:
        raise PermissionError("Embedded context has expired")
    if payload.get("iss") != issuer or payload.get("aud") != audience:
        raise PermissionError("Embedded context issuer/audience mismatch")
    if not payload.get("tenant_id") or not payload.get("user_id"):
        raise PermissionError("Embedded context is missing tenant/user identity")
    payload["expires_at"] = int(payload.get("exp") or 0)
    return EmbeddedContext.from_dict(payload)
