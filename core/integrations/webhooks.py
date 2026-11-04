"""
Webhook manager for FolioShield integrations.

Features:
- Per-tenant subscriptions with event filters.
- HMAC-SHA256 signed payloads.
- Stable event IDs and idempotency keys.
- Delivery records with retry/backoff state.
- Duplicate suppression by (subscription, event_id).

Phase 2 (P1) changes:
- Subscription secrets are stored ENCRYPTED by the registry (Fernet);
  the raw secret is returned once at subscribe time and never persisted
  in plaintext.
- publish() makes the first delivery attempt inline; retries are
  recorded with next_attempt_at and resumed by resume_due_deliveries()
  (API interval thread, agent, or cron) instead of blocking the caller.
- A subscription whose secret cannot be decrypted produces an
  'undeliverable' delivery record — never an unsigned or wrongly-signed
  request.

Network delivery is performed through an injectable sender so tests and
agent deployments can validate behavior without external calls.
"""

from __future__ import annotations

import hashlib
import hmac
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .contracts import IntegrationEvent

Sender = Callable[[str, bytes, Dict[str, str]], int]

MAX_DELIVERY_ATTEMPTS = 5


def sign_payload(secret: str, payload: bytes, timestamp: Optional[str] = None) -> Dict[str, str]:
    ts = timestamp or str(int(time.time()))
    signed = f"{ts}.".encode("utf-8") + payload
    signature = hmac.new(secret.encode("utf-8"), signed, hashlib.sha256).hexdigest()
    return {"timestamp": ts, "signature": f"v1={signature}"}


def verify_signature(secret: str, payload: bytes, timestamp: str, signature: str, tolerance_seconds: int = 300) -> bool:
    try:
        ts = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(int(time.time()) - ts) > tolerance_seconds:
        return False
    expected = sign_payload(secret, payload, timestamp)["signature"]
    return hmac.compare_digest(expected, signature or "")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class WebhookManager:
    """Subscription and delivery manager backed by IntegrationRegistry storage."""

    def __init__(self, registry: Any, sender: Optional[Sender] = None):
        self.registry = registry
        self.sender = sender or self._default_sender

    @staticmethod
    def _default_sender(url: str, payload: bytes, headers: Dict[str, str]) -> int:
        import requests

        response = requests.post(url, data=payload, headers=headers, timeout=10)
        return int(response.status_code)

    # ------------------------------------------------------------ subscriptions

    def subscribe(self, tenant_id: str, url: str, event_types: List[str], secret: Optional[str] = None,
                  description: str = "") -> Dict[str, Any]:
        if not url.startswith("https://") and not url.startswith("http://localhost"):
            raise ValueError("Webhook URL must use HTTPS (http://localhost is allowed for development tests)")
        raw_secret = secret or uuid.uuid4().hex
        subscription = {
            "subscription_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "url": url,
            "event_types": event_types,
            "secret": raw_secret,  # encrypted by registry.put_webhook before storage
            "description": description,
            "status": "active",
            "created_at": _now_iso(),
        }
        stored = self.registry.put_webhook(subscription)
        public = {k: v for k, v in stored.items() if k not in ("secret", "secret_encrypted")}
        return public | {"secret_shown_once": raw_secret}

    def list_subscriptions(self, tenant_id: str) -> List[Dict[str, Any]]:
        out = []
        for sub in self.registry.get_webhooks(tenant_id):
            item = deepcopy(sub)
            item.pop("secret", None)
            item.pop("secret_encrypted", None)
            out.append(item)
        return out

    def revoke_subscription(self, tenant_id: str, subscription_id: str) -> bool:
        sub = self.registry.get_webhook(subscription_id)
        if not sub or sub.get("tenant_id") != tenant_id:
            return False
        sub["status"] = "revoked"
        self.registry.put_webhook(sub)
        return True

    # ---------------------------------------------------------------- delivery

    def publish(self, event: IntegrationEvent, max_attempts: int = 1) -> List[Dict[str, Any]]:
        """First delivery attempt per matching subscription (inline).

        Further attempts are scheduled via next_attempt_at and executed
        by resume_due_deliveries(). max_attempts is retained for
        compatibility; values > 1 perform that many inline attempts.
        """
        payload = event.payload_bytes()
        deliveries: List[Dict[str, Any]] = []
        for sub in self.registry.get_webhooks(event.tenant_id):
            if sub.get("status") != "active":
                continue
            if sub.get("event_types") and event.event_type not in sub["event_types"] and "*" not in sub["event_types"]:
                continue
            delivery = self._deliver(sub, event, payload, inline_attempts=max(1, max_attempts))
            deliveries.append(delivery)
        return deliveries

    def resume_due_deliveries(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Attempts deliveries whose retry time has arrived.

        The original event payload is reconstructed from the stored
        delivery record (event payloads are deterministic JSON of the
        IntegrationEvent fields retained on the record).
        """
        resumed: List[Dict[str, Any]] = []
        for record in self.registry.due_deliveries(_now_iso())[:limit]:
            sub = self.registry.get_webhook(record["subscription_id"])
            if not sub or sub.get("status") != "active" or sub.get("tenant_id") != record.get("tenant_id"):
                record = self._finish_delivery(record, "failed", record.get("attempts") or 0,
                                               "Subscription no longer active")
                resumed.append(record)
                continue
            payload = record.get("payload_bytes_b64")
            if not payload:
                record = self._finish_delivery(record, "failed", record.get("attempts") or 0,
                                               "Original event payload is not retained; cannot resume")
                resumed.append(record)
                continue
            import base64

            resumed.append(self._attempt(sub, record, base64.b64decode(payload)))
        return resumed

    def _deliver(self, subscription: Dict[str, Any], event: IntegrationEvent, payload: bytes,
                 inline_attempts: int = 1) -> Dict[str, Any]:
        dedupe_key = f"{subscription['subscription_id']}:{event.event_id}"
        existing = self.registry.find_delivery_by_dedupe(dedupe_key)
        if existing:
            return existing
        import base64

        record = {
            "delivery_id": str(uuid.uuid4()),
            "delivery_key": f"{subscription['tenant_id']}:{uuid.uuid4()}",
            "dedupe_key": dedupe_key,
            "tenant_id": subscription["tenant_id"],
            "subscription_id": subscription["subscription_id"],
            "event_id": event.event_id,
            "event_type": event.event_type,
            "case_id": event.case_id,
            "status": "pending",
            "attempts": 0,
            "created_at": _now_iso(),
            "last_error": None,
            "next_attempt_at": None,
            # Retained so retries can be resumed without the publisher.
            "payload_bytes_b64": base64.b64encode(payload).decode("utf-8"),
        }
        record["delivery_key"] = f"{subscription['tenant_id']}:{record['delivery_id']}"
        self.registry.put_delivery(record["delivery_key"], record)
        for _ in range(inline_attempts):
            record = self._attempt(subscription, record, payload)
            if record["status"] != "retrying":
                break
        return record

    def _attempt(self, subscription: Dict[str, Any], record: Dict[str, Any], payload: bytes) -> Dict[str, Any]:
        secret = self.registry.webhook_secret(subscription)
        attempts = int(record.get("attempts") or 0) + 1
        if not secret:
            return self._finish_delivery(
                record, "undeliverable", attempts,
                "Webhook signing secret is unavailable (encryption key missing or subscription "
                "predates encrypted storage). Rotate the subscription to restore delivery.")
        headers_base = sign_payload(secret, payload)
        headers = {
            "Content-Type": "application/json",
            "X-FolioShield-Event": record["event_type"],
            "X-FolioShield-Event-Id": record["event_id"],
            "X-FolioShield-Delivery-Id": record["delivery_id"],
            "X-FolioShield-Timestamp": headers_base["timestamp"],
            "X-FolioShield-Signature": headers_base["signature"],
            "Idempotency-Key": record["event_id"],
        }
        try:
            status = self.sender(subscription["url"], payload, headers)
            if 200 <= int(status) < 300:
                return self._finish_delivery(record, "delivered", attempts, None)
            last_error = f"HTTP {status}"
        except Exception as exc:  # sender errors are delivery failures, not publisher crashes
            last_error = str(exc)[:300]
        if attempts >= MAX_DELIVERY_ATTEMPTS:
            return self._finish_delivery(record, "failed", attempts, last_error)
        delay = min(2 ** attempts, 300)
        return self._finish_delivery(record, "retrying", attempts, last_error, delay_seconds=delay)

    def _finish_delivery(self, record: Dict[str, Any], status: str, attempts: int,
                         error: Optional[str], delay_seconds: int = 0) -> Dict[str, Any]:
        updated = dict(record)
        updated["status"] = status
        updated["attempts"] = attempts
        updated["last_error"] = error
        updated["updated_at"] = _now_iso()
        updated["next_attempt_at"] = (
            (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat() if delay_seconds else None
        )
        self.registry.put_delivery(updated["delivery_key"], updated)
        return deepcopy(updated)

    def list_deliveries(self, tenant_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for delivery in self.registry.list_deliveries(tenant_id):
            if status and delivery.get("status") != status:
                continue
            item = deepcopy(delivery)
            item.pop("payload_bytes_b64", None)
            out.append(item)
        return out
