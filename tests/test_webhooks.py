"""
Webhook tests for FolioShield enterprise integrations.
"""

import tempfile
import unittest

from core.integrations.contracts import IntegrationEvent
from core.integrations.registry import IntegrationRegistry
from core.integrations.webhooks import WebhookManager, sign_payload, verify_signature


class TestWebhooks(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.registry = IntegrationRegistry(root=self.tmp.name)
        self.registry.create_tenant("hotel-a", "Hotel A")
        self.sent = []

        def sender(url, payload, headers):
            self.sent.append({"url": url, "payload": payload, "headers": headers})
            return 200

        self.manager = WebhookManager(self.registry, sender=sender)

    def tearDown(self):
        self.tmp.cleanup()

    def test_signed_delivery_and_duplicate_suppression(self):
        subscription = self.manager.subscribe("hotel-a", "https://example.test/hook", ["rebuttal.drafted"], secret="whsec_test")
        self.assertIn("secret_shown_once", subscription)
        event = IntegrationEvent(event_type="rebuttal.drafted", tenant_id="hotel-a", case_id="CASE-1")
        deliveries = self.manager.publish(event)
        self.assertEqual(len(deliveries), 1)
        self.assertEqual(deliveries[0]["status"], "delivered")
        self.assertEqual(len(self.sent), 1)
        headers = self.sent[0]["headers"]
        self.assertTrue(verify_signature("whsec_test", self.sent[0]["payload"], headers["X-FolioShield-Timestamp"], headers["X-FolioShield-Signature"]))

        # Same event published again is suppressed by dedupe key.
        deliveries2 = self.manager.publish(event)
        self.assertEqual(len(deliveries2), 1)
        self.assertEqual(len(self.sent), 1)

    def test_event_filter_and_revocation(self):
        self.manager.subscribe("hotel-a", "https://example.test/hook", ["packet.generated"], secret="whsec_test")
        event = IntegrationEvent(event_type="rebuttal.drafted", tenant_id="hotel-a", case_id="CASE-1")
        self.assertEqual(self.manager.publish(event), [])
        subs = self.manager.list_subscriptions("hotel-a")
        self.assertTrue(self.manager.revoke_subscription("hotel-a", subs[0]["subscription_id"]))
        event2 = IntegrationEvent(event_type="packet.generated", tenant_id="hotel-a", case_id="CASE-1")
        self.assertEqual(self.manager.publish(event2), [])

    def test_signature_rejects_tampering(self):
        payload = b'{"ok":true}'
        signed = sign_payload("secret", payload, "9999999999")
        self.assertFalse(verify_signature("secret", b'{"ok":false}', signed["timestamp"], signed["signature"]))


if __name__ == "__main__":
    unittest.main()
