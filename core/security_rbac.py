"""
Role-Based Access Control (RBAC) and Principal Authentication for FolioShield.

Defines enterprise roles, permission matrices, token issuance, and enforcement
for human and automated actors.
"""

import hashlib
import hmac
import json
import time
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Dict, List, Optional, Set


class UserRole(str, Enum):
    """Standard enterprise user roles."""
    ADMIN = "admin"
    MANAGER = "manager"
    OPERATOR = "operator"
    AUDITOR = "auditor"
    VIEWER = "viewer"


class Permission(str, Enum):
    """Granular permissions across dispute lifecycle."""
    CASE_READ = "case:read"
    CASE_WRITE = "case:write"
    CASE_DELETE = "case:delete"
    EVIDENCE_UPLOAD = "evidence:upload"
    RECONCILE = "dispute:reconcile"
    REBUTTAL_DRAFT = "rebuttal:draft"
    REBUTTAL_APPROVE = "rebuttal:approve"
    SUBMISSION_EXECUTE = "submission:execute"
    OUTCOME_RECORD = "outcome:record"
    INTEGRATION_MANAGE = "integration:manage"
    AUDIT_VERIFY = "audit:verify"


ROLE_PERMISSIONS: Dict[UserRole, Set[Permission]] = {
    UserRole.ADMIN: {
        Permission.CASE_READ,
        Permission.CASE_WRITE,
        Permission.CASE_DELETE,
        Permission.EVIDENCE_UPLOAD,
        Permission.RECONCILE,
        Permission.REBUTTAL_DRAFT,
        Permission.REBUTTAL_APPROVE,
        Permission.SUBMISSION_EXECUTE,
        Permission.OUTCOME_RECORD,
        Permission.INTEGRATION_MANAGE,
        Permission.AUDIT_VERIFY,
    },
    UserRole.MANAGER: {
        Permission.CASE_READ,
        Permission.CASE_WRITE,
        Permission.EVIDENCE_UPLOAD,
        Permission.RECONCILE,
        Permission.REBUTTAL_DRAFT,
        Permission.REBUTTAL_APPROVE,
        Permission.SUBMISSION_EXECUTE,
        Permission.OUTCOME_RECORD,
        Permission.AUDIT_VERIFY,
    },
    UserRole.OPERATOR: {
        Permission.CASE_READ,
        Permission.CASE_WRITE,
        Permission.EVIDENCE_UPLOAD,
        Permission.RECONCILE,
        Permission.REBUTTAL_DRAFT,
        Permission.AUDIT_VERIFY,
    },
    UserRole.AUDITOR: {
        Permission.CASE_READ,
        Permission.AUDIT_VERIFY,
    },
    UserRole.VIEWER: {
        Permission.CASE_READ,
    },
}


@dataclass
class UserPrincipal:
    """Authenticated human or service identity."""
    user_id: str
    tenant_id: str
    role: UserRole
    email: Optional[str] = None
    name: Optional[str] = None
    property_ids: Optional[List[str]] = None

    def has_permission(self, permission: Permission) -> bool:
        """Checks whether the principal's role grants the requested permission."""
        perms = ROLE_PERMISSIONS.get(self.role, set())
        return permission in perms

    def require_permission(self, permission: Permission) -> None:
        """Raises PermissionError if principal lacks permission."""
        if not self.has_permission(permission):
            raise PermissionError(
                f"Principal '{self.user_id}' with role '{self.role.value}' "
                f"lacks required permission: '{permission.value}'"
            )

    def can_access_tenant(self, target_tenant_id: str) -> bool:
        """Verifies strict tenant isolation."""
        if not target_tenant_id:
            return False
        return self.tenant_id == target_tenant_id

    def require_tenant(self, target_tenant_id: str) -> None:
        """Raises PermissionError on cross-tenant access."""
        if not self.can_access_tenant(target_tenant_id):
            raise PermissionError(
                f"Access denied: principal belongs to tenant '{self.tenant_id}', "
                f"cannot access resource owned by tenant '{target_tenant_id}'."
            )

    def to_dict(self) -> Dict[str, object]:
        d = asdict(self)
        d["role"] = self.role.value
        return d


def _hmac_sign(data: str, key: str) -> str:
    return hmac.new(key.encode("utf-8"), data.encode("utf-8"), hashlib.sha256).hexdigest()


def _hmac_verify(data: str, signature: str, key: str) -> bool:
    expected = _hmac_sign(data, key)
    return hmac.compare_digest(expected, signature)


def create_principal_token(
    principal: UserPrincipal,
    signing_key: str,
    expires_in_seconds: int = 3600,
) -> str:
    """Issues a cryptographically signed HMAC bearer token for a UserPrincipal."""
    import base64
    payload = principal.to_dict()
    payload["exp"] = int(time.time()) + expires_in_seconds
    payload_json = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    payload_b64 = base64.urlsafe_b64encode(payload_json).decode("utf-8").rstrip("=")
    signature = _hmac_sign(payload_b64, signing_key)
    return f"{payload_b64}.{signature}"


def verify_principal_token(token: str, signing_key: str) -> UserPrincipal:
    """Verifies and decodes a bearer token into an authenticated UserPrincipal."""
    import base64
    if not token or "." not in token:
        raise ValueError("Invalid token format")

    parts = token.split(".", 1)
    payload_b64, signature = parts[0], parts[1]

    if not _hmac_verify(payload_b64, signature, signing_key):
        raise PermissionError("Token signature verification failed")

    pad = len(payload_b64) % 4
    if pad:
        payload_b64 += "=" * (4 - pad)

    try:
        payload_json = base64.urlsafe_b64decode(payload_b64)
        data = json.loads(payload_json.decode("utf-8"))
    except Exception as exc:
        raise ValueError(f"Malformed token payload: {exc}") from exc

    exp = data.get("exp", 0)
    if time.time() > exp:
        raise PermissionError("Token has expired")

    role_str = data.get("role", "viewer")
    try:
        role = UserRole(role_str)
    except ValueError:
        role = UserRole.VIEWER

    return UserPrincipal(
        user_id=data["user_id"],
        tenant_id=data["tenant_id"],
        role=role,
        email=data.get("email"),
        name=data.get("name"),
        property_ids=data.get("property_ids"),
    )
