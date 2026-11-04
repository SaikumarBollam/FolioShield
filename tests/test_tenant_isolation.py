"""
Integration management and tenant isolation tests.
"""

import tempfile
import unittest

from core.integrations.registry import IntegrationRegistry


class TestIntegrationManagement(unittest.TestCase):

    def test_monitoring_snapshot_is_tenant_scoped(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            registry.create_tenant("hotel-b", "Hotel B")
            registry.issue_credential("hotel-a", "A client", scopes=["cases:read"])
            registry.issue_credential("hotel-b", "B client", scopes=["cases:read"])
            snap_a = registry.monitoring_snapshot("hotel-a")
            snap_b = registry.monitoring_snapshot("hotel-b")
            self.assertEqual(snap_a["credentials"], 1)
            self.assertEqual(snap_b["credentials"], 1)
            self.assertEqual(snap_a["cases"], 0)
            self.assertEqual(snap_b["cases"], 0)

    def test_agent_suspension_blocks_heartbeat(self):
        with tempfile.TemporaryDirectory() as tmp:
            registry = IntegrationRegistry(root=tmp)
            registry.create_tenant("hotel-a", "Hotel A")
            agent, _secret = registry.register_agent("hotel-a", "agent-1", "Front Office")
            self.assertEqual(agent["status"], "active")
            self.assertIsNotNone(registry.agent_heartbeat("hotel-a", "agent-1"))
            self.assertTrue(registry.set_agent_status("hotel-a", "agent-1", "suspended"))
            self.assertIsNone(registry.agent_heartbeat("hotel-a", "agent-1"))


if __name__ == "__main__":
    unittest.main()
