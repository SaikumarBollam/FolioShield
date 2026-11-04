"""
Webhook manager for FolioShield integrations.

Features:
- Per-tenant subscriptions with event filters.
- HMAC-SHA256 signed payloads.
- Stable event IDs and idempotency keys.
- Delivery records with retry/backoff state.
- Duplicate suppression by (subscription, event_id).

Network delivery is performed through an injectable sender so tests and
agent deployments can validate behavior without external calls.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional

from .contracts import IntegrationEvent

Sender = Callable[[str, bytes, Dict[str, str]], int]


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
        subscription = {
            "subscription_id": str(uuid.uuid4()),
            "tenant_id": tenant_id,
            "url": url,
            "event_types": event_types,
            "secret": secret or uuid.uuid4().hex,
            "description": description,
            "status": "active",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        with self.registry._lock:  # registry owns v1 persistence
            self.registry._data["webhooks"][subscription["subscription_id"]] = subscription
            self.registry._save()
        return {k: v for k, v in subscription.items() if k != "secret"} | {"secret_shown_once": subscription["secret"]}

    def list_subscriptions(self, tenant_id: str) -> List[Dict[str, Any]]:
        out = []
        for sub in self.registry._data["webhooks"].values():
            if sub.get("tenant_id") == tenant_id:
                item = deepcopy(sub)
                item.pop("secret", None)
                out.append(item)
        return out

    def revoke_subscription(self, tenant_id: str, subscription_id: str) -> bool:
        with self.registry._lock:
            sub = self.registry._data["webhooks"].get(subscription_id)
            if not sub or sub.get("tenant_id") != tenant_id:
                return False
            sub["status"] = "revoked"
            self.registry._save()
            return True

    # ---------------------------------------------------------------- delivery

    def publish(self, event: IntegrationEvent, max_attempts: int = 3) -> List[Dict[str, Any]]:
        payload = event.payload_bytes()
        deliveries: List[Dict[str, Any]] = []
        for sub in list(self.registry._data["webhooks"].values()):
            if sub.get("tenant_id") != event.tenant_id or sub.get("status") != "active":
                continue
            if sub.get("event_types") and event.event_type not in sub["event_types"] and "*" not in sub["event_types"]:
                continue
            delivery = self._deliver(sub, event, payload, max_attempts=max_attempts)
            deliveries.append(delivery)
        return deliveries

    def _deliver(self, subscription: Dict[str, Any], event: IntegrationEvent, payload: bytes, max_attempts: int = 3) -> Dict[str, Any]:
        delivery_id = str(uuid.uuid4())
        key = f"{subscription['tenant_id']}:{delivery_id}"
        existing_key = f"{subscription['subscription_id']}:{event.event_id}"
        with self.registry._lock:
            for existing in self.registry._data["deliveries"].values():
                if existing.get("dedupe_key") == existing_key:
                    return deepcopy(existing)
            record = {
                "delivery_id": delivery_id,
                "dedupe_key": existing_key,
                "tenant_id": subscription["tenant_id"],
                "subscription_id": subscription["subscription_id"],
                "event_id": event.event_id,
                "event_type": event.event_type,
                "case_id": event.case_id,
                "status": "pending",
                "attempts": 0,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "last_error": None,
                "next_attempt_at": None,
            }
            self.registry._data["deliveries"][key] = record
            self.registry._save()

        headers_base = sign_payload(subscription["secret"], payload)
        headers = {
            "Content-Type": "application/json",
            "X-FolioShield-Event": event.event_type,
            "X-FolioShield-Event-Id": event.event_id,
            "X-FolioShield-Delivery-Id": delivery_id,
            "X-FolioShield-Timestamp": headers_base["timestamp"],
            "X-FolioShield-Signature": headers_base["signature"],
            "Idempotency-Key": event.event_id,
        }
        last_error: Optional[str] = None
        for attempt in range(1, max_attempts + 1):
            try:
                status = self.sender(subscription["url"], payload, headers)
                if 200 <= int(status) < 300:
                    return self._finish_delivery(key, "delivered", attempt, None)
                last_error = f"HTTP {status}"
            except Exception as exc:  # sender errors are delivery failures, not publisher crashes
                last_error = str(exc)[:300]
            if attempt < max_attempts:
                delay = min(2 ** attempt, 30)
                record = self._finish_delivery(key, "retrying", attempt, last_error, delay_seconds=delay)
        return self._finish_delivery(key, "failed", max_attempts, last_error)

    def _finish_delivery(self, key: str, status: str, attempts: int, error: Optional[str], delay_seconds: int = 0) -> Dict[str, Any]:
        with self.registry._lock:
            record = self.registry._data["deliveries"][key]
            record["status"] = status
            record["attempts"] = attempts
            record["last_error"] = error
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            record["next_attempt_at"] = (
                (datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)).isoformat() if delay_seconds else None
            )
            self.registry._save()
            return deepcopy(record)

    def list_deliveries(self, tenant_id: str, status: Optional[str] = None) -> List[Dict[str, Any]]:
        out = []
        for delivery in self.registry._data["deliveries"].values():
            if delivery.get("tenant_id") != tenant_id:
                continue
            if status and delivery.get("status") != status:
                continue
            out.append(deepcopy(delivery))
        return out
