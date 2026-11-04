"""
Tests for Role-Based Access Control (RBAC), UserPrincipal, and Token Lifecycle.
"""

import unittest

from core.security_rbac import (
    Permission,
    UserPrincipal,
    UserRole,
    create_principal_token,
    verify_principal_token,
)


class TestRbacSecurity(unittest.TestCase):
    def setUp(self):
        self.signing_key = "test-signing-secret-key-32byteslong!!"

    def test_role_permission_matrix(self):
        # Operator can draft but cannot approve or submit
        operator = UserPrincipal(user_id="op-1", tenant_id="hotel-1", role=UserRole.OPERATOR)
        self.assertTrue(operator.has_permission(Permission.RECONCILE))
        self.assertTrue(operator.has_permission(Permission.REBUTTAL_DRAFT))
        self.assertFalse(operator.has_permission(Permission.REBUTTAL_APPROVE))
        self.assertFalse(operator.has_permission(Permission.SUBMISSION_EXECUTE))

        with self.assertRaises(PermissionError):
            operator.require_permission(Permission.REBUTTAL_APPROVE)

        # Manager can approve and submit
        manager = UserPrincipal(user_id="mgr-1", tenant_id="hotel-1", role=UserRole.MANAGER)
        self.assertTrue(manager.has_permission(Permission.REBUTTAL_APPROVE))
        self.assertTrue(manager.has_permission(Permission.SUBMISSION_EXECUTE))
        manager.require_permission(Permission.REBUTTAL_APPROVE)

        # Auditor can read and verify audit trails, but cannot write or approve
        auditor = UserPrincipal(user_id="aud-1", tenant_id="hotel-1", role=UserRole.AUDITOR)
        self.assertTrue(auditor.has_permission(Permission.CASE_READ))
        self.assertTrue(auditor.has_permission(Permission.AUDIT_VERIFY))
        self.assertFalse(auditor.has_permission(Permission.CASE_WRITE))
        self.assertFalse(auditor.has_permission(Permission.REBUTTAL_APPROVE))

        # Viewer has only read permission
        viewer = UserPrincipal(user_id="view-1", tenant_id="hotel-1", role=UserRole.VIEWER)
        self.assertTrue(viewer.has_permission(Permission.CASE_READ))
        self.assertFalse(viewer.has_permission(Permission.RECONCILE))
        self.assertFalse(viewer.has_permission(Permission.CASE_WRITE))

    def test_tenant_isolation_enforcement(self):
        user = UserPrincipal(user_id="u1", tenant_id="hotel-alpha", role=UserRole.MANAGER)
        self.assertTrue(user.can_access_tenant("hotel-alpha"))
        self.assertFalse(user.can_access_tenant("hotel-beta"))

        # require_tenant
        user.require_tenant("hotel-alpha")
        with self.assertRaises(PermissionError):
            user.require_tenant("hotel-beta")

    def test_token_creation_and_verification(self):
        user = UserPrincipal(
            user_id="usr-42",
            tenant_id="tenant-chicago",
            role=UserRole.MANAGER,
            email="manager@chicago.hotel",
            name="Alice Manager",
        )
        token = create_principal_token(user, self.signing_key, expires_in_seconds=300)
        self.assertIsInstance(token, str)
        self.assertIn(".", token)

        # Valid verification
        verified = verify_principal_token(token, self.signing_key)
        self.assertEqual(verified.user_id, "usr-42")
        self.assertEqual(verified.tenant_id, "tenant-chicago")
        self.assertEqual(verified.role, UserRole.MANAGER)
        self.assertEqual(verified.email, "manager@chicago.hotel")
        self.assertEqual(verified.name, "Alice Manager")

        # Tampered signature fails
        parts = token.split(".", 1)
        bad_token = f"{parts[0]}.bad_signature_here"
        with self.assertRaises(PermissionError):
            verify_principal_token(bad_token, self.signing_key)

        # Wrong signing key fails
        with self.assertRaises(PermissionError):
            verify_principal_token(token, "completely-different-signing-key")

        # Expired token fails
        exp_token = create_principal_token(user, self.signing_key, expires_in_seconds=-10)
        with self.assertRaises(PermissionError) as ctx:
            verify_principal_token(exp_token, self.signing_key)
        self.assertIn("expired", str(ctx.exception).lower())


if __name__ == "__main__":
    unittest.main()
