"""
Tenant-scoped integration registry.

Stores tenants, credentials, agents, webhook subscriptions, cases, jobs,
and webhook deliveries. Phase 2 (P1) replaced the v1 single-file JSON
store with SQLite (WAL) behind the same public interface:

- Records are partitioned by tenant_id (enforced in every query).
- Credential secrets are never stored raw (PBKDF2 hashes only).
- Webhook secrets are stored encrypted (see integrations/secrets.py);
  only a last-4 hint is kept in clear text.
- Case lookups require tenant_id and internal case_id.
- Revoked/suspended credentials and agents fail closed.
- Concurrent processes serialize through SQLite transactions instead of
  overwriting each other's in-memory copies of a JSON file.

Migration: when the SQLite database is empty and a legacy registry.json
exists, its contents are imported once, verified, and the JSON file is
renamed to registry.json.migrated-<timestamp> (never deleted). A corrupt
legacy file raises IntegrationRegistryError — the registry never starts
silently empty over real data.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .authentication import CredentialRecord, generate_api_key, hash_secret, verify_secret
from .contracts import IntegrationCaseRef, ProcessingJob, TenantContext
from .secrets import decrypt_secret, encrypt_secret, secret_hint

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS tenants (
    tenant_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS credentials (
    credential_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_credentials_tenant ON credentials(tenant_id);
CREATE TABLE IF NOT EXISTS agents (
    agent_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_agents_tenant ON agents(tenant_id);
CREATE TABLE IF NOT EXISTS webhooks (
    subscription_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_webhooks_tenant ON webhooks(tenant_id);
CREATE TABLE IF NOT EXISTS cases (
    case_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, case_id TEXT NOT NULL, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_cases_tenant ON cases(tenant_id);
CREATE TABLE IF NOT EXISTS jobs (
    job_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, idempotency_key TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_jobs_tenant ON jobs(tenant_id);
CREATE TABLE IF NOT EXISTS deliveries (
    delivery_key TEXT PRIMARY KEY, tenant_id TEXT NOT NULL, dedupe_key TEXT, payload TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_deliveries_tenant ON deliveries(tenant_id);
CREATE INDEX IF NOT EXISTS idx_deliveries_dedupe ON deliveries(dedupe_key);
"""


def _safe(value: str) -> str:
    return _SAFE.sub("_", value or "unknown")[:100]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IntegrationRegistryError(RuntimeError):
    """The integration registry storage is unavailable or corrupt."""


class IntegrationRegistry:
    """SQLite-backed tenant/integration registry (Phase 2)."""

    def __init__(self, root: str | Path = "data/integrations"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._db_path = self.root / "registry.db"
        self._legacy_path = self.root / "registry.json"
        self._lock = threading.RLock()
        from .secrets import configure_key_file

        configure_key_file(self.root / "webhook_secret.key")
        try:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")
            with self._conn:
                self._conn.executescript(_SCHEMA)
        except (sqlite3.Error, OSError) as exc:
            raise IntegrationRegistryError(
                f"Integration registry database '{self._db_path}' is unavailable: {exc}") from exc
        self._migrate_legacy_json()

    # ------------------------------------------------------------------ storage

    def _migrate_legacy_json(self) -> None:
        """One-time import of the v1 registry.json (verified, then renamed)."""
        if not self._legacy_path.exists():
            return
        count = self._conn.execute("SELECT COUNT(*) FROM tenants").fetchone()[0]
        count += self._conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
        count += self._conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        if count:
            return  # DB already populated; leave the legacy file untouched.
        try:
            data = json.loads(self._legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise IntegrationRegistryError(
                f"Legacy registry '{self._legacy_path}' is corrupt and was NOT discarded: {exc}. "
                "Repair or remove the file manually, then restart.") from exc
        if not isinstance(data, dict):
            raise IntegrationRegistryError(
                f"Legacy registry '{self._legacy_path}' has an unexpected shape and was NOT discarded.")
        imported = 0
        with self._lock, self._conn:
            for tenant_id, tenant in (data.get("tenants") or {}).items():
                self._put("tenants", tenant_id, tenant)
                imported += 1
            for credential_id, record in (data.get("credentials") or {}).items():
                self._put("credentials", credential_id, record, tenant_id=record.get("tenant_id"))
                imported += 1
            for key, agent in (data.get("agents") or {}).items():
                self._put("agents", key, agent, tenant_id=agent.get("tenant_id"))
                imported += 1
            for subscription_id, sub in (data.get("webhooks") or {}).items():
                self._put("webhooks", subscription_id, self._protect_webhook_secret(dict(sub)),
                          tenant_id=sub.get("tenant_id"))
                imported += 1
            for key, record in (data.get("cases") or {}).items():
                case_id = record.get("case_id") or key.split(":", 1)[-1]
                self._put("cases", key, record, tenant_id=record.get("tenant_id"), case_id=case_id)
                imported += 1
            for key, job in (data.get("jobs") or {}).items():
                self._put("jobs", key, job, tenant_id=job.get("tenant_id"),
                          idempotency_key=job.get("idempotency_key"))
                imported += 1
            for key, delivery in (data.get("deliveries") or {}).items():
                self._put("deliveries", key, delivery, tenant_id=delivery.get("tenant_id"),
                          dedupe_key=delivery.get("dedupe_key"))
                imported += 1
        if imported:
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            try:
                os.replace(self._legacy_path, self.root / f"registry.json.migrated-{stamp}")
            except OSError:
                pass  # Import succeeded; a leftover JSON is ignored from now on.

    def _protect_webhook_secret(self, subscription: Dict[str, Any]) -> Dict[str, Any]:
        """Replaces a plaintext webhook secret with its encrypted form."""
        secret = subscription.pop("secret", None)
        if secret:
            subscription["secret_encrypted"] = encrypt_secret(str(secret))
            subscription["secret_hint"] = secret_hint(str(secret))
        return subscription

    def _put(self, table: str, key: str, payload: Dict[str, Any], tenant_id: Optional[str] = None,
             case_id: Optional[str] = None, idempotency_key: Optional[str] = None,
             dedupe_key: Optional[str] = None) -> None:
        blob = json.dumps(payload, default=str)
        if table == "tenants":
            sql = "INSERT OR REPLACE INTO tenants(tenant_id, payload) VALUES (?, ?)"
            args = (key, blob)
        elif table == "credentials":
            sql = "INSERT OR REPLACE INTO credentials(credential_id, tenant_id, payload) VALUES (?, ?, ?)"
            args = (key, tenant_id or "", blob)
        elif table == "agents":
            sql = "INSERT OR REPLACE INTO agents(agent_key, tenant_id, payload) VALUES (?, ?, ?)"
            args = (key, tenant_id or "", blob)
        elif table == "webhooks":
            sql = "INSERT OR REPLACE INTO webhooks(subscription_id, tenant_id, payload) VALUES (?, ?, ?)"
            args = (key, tenant_id or "", blob)
        elif table == "cases":
            sql = "INSERT OR REPLACE INTO cases(case_key, tenant_id, case_id, payload) VALUES (?, ?, ?, ?)"
            args = (key, tenant_id or "", case_id or "", blob)
        elif table == "jobs":
            sql = "INSERT OR REPLACE INTO jobs(job_key, tenant_id, idempotency_key, payload) VALUES (?, ?, ?, ?)"
            args = (key, tenant_id or "", idempotency_key, blob)
        elif table == "deliveries":
            sql = "INSERT OR REPLACE INTO deliveries(delivery_key, tenant_id, dedupe_key, payload) VALUES (?, ?, ?, ?)"
            args = (key, tenant_id or "", dedupe_key, blob)
        else:  # pragma: no cover - internal guard
            raise ValueError(f"Unknown registry table: {table}")
        self._conn.execute(sql, args)

    @staticmethod
    def _pk(table: str) -> str:
        return {"tenants": "tenant_id", "credentials": "credential_id", "agents": "agent_key",
                "webhooks": "subscription_id", "cases": "case_key", "jobs": "job_key",
                "deliveries": "delivery_key"}[table]

    def _get(self, table: str, key: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(f"SELECT payload FROM {table} WHERE {self._pk(table)} = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _list(self, table: str, tenant_id: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute(
            f"SELECT payload FROM {table} WHERE tenant_id = ?", (_safe(tenant_id),)).fetchall()
        return [json.loads(r[0]) for r in rows]

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass

    def __enter__(self) -> "IntegrationRegistry":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def __del__(self):  # best-effort cleanup for short-lived instances
        try:
            self._conn.close()
        except Exception:
            pass

    # ------------------------------------------------------------------ tenants

    def create_tenant(self, tenant_id: str, name: str, property_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        tenant_id = _safe(tenant_id)
        tenant = {"tenant_id": tenant_id, "name": name, "property_ids": property_ids or [],
                  "status": "active", "created_at": _now()}
        with self._lock, self._conn:
            self._put("tenants", tenant_id, tenant)
        return deepcopy(tenant)

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        tenant = self._get("tenants", _safe(tenant_id))
        return deepcopy(tenant) if tenant else None

    def require_tenant(self, tenant_id: str) -> Dict[str, Any]:
        tenant = self.get_tenant(tenant_id)
        if not tenant or tenant.get("status") != "active":
            raise PermissionError("Tenant is not active")
        return tenant

    def set_tenant_status(self, tenant_id: str, status: str) -> bool:
        tenant = self.get_tenant(tenant_id)
        if not tenant:
            return False
        tenant["status"] = status
        with self._lock, self._conn:
            self._put("tenants", tenant["tenant_id"], tenant)
        return True

    # --------------------------------------------------------------- credentials

    def issue_credential(self, tenant_id: str, label: str, scopes: List[str],
                         actor_type: str = "api_client", actor_id: Optional[str] = None,
                         property_ids: Optional[List[str]] = None, roles: Optional[List[str]] = None,
                         expires_at: Optional[str] = None) -> tuple[Dict[str, Any], str]:
        self.require_tenant(tenant_id)
        credential_id, raw_secret = generate_api_key()
        record = CredentialRecord(
            credential_id=credential_id,
            tenant_id=_safe(tenant_id),
            label=label,
            secret_hash=hash_secret(raw_secret),
            scopes=scopes,
            actor_type=actor_type,
            actor_id=actor_id or credential_id,
            property_ids=property_ids or [],
            roles=roles or [],
            expires_at=expires_at,
        )
        with self._lock, self._conn:
            self._put("credentials", credential_id, record.to_dict(), tenant_id=record.tenant_id)
        return record.public_dict(), raw_secret

    def authenticate(self, raw_secret: str):
        from .authentication import AuthenticatedPrincipal, credential_id_from_secret

        credential_id = credential_id_from_secret(raw_secret or "")
        if not credential_id:
            return None
        stored = self._get("credentials", credential_id)
        if not stored:
            return None
        record = CredentialRecord.from_dict(stored)
        if not record.is_usable() or not verify_secret(raw_secret, record.secret_hash):
            return None
        tenant = self.get_tenant(record.tenant_id)
        if not tenant or tenant.get("status") != "active":
            return None
        with self._lock, self._conn:
            record.last_used_at = _now()
            self._put("credentials", credential_id, record.to_dict(), tenant_id=record.tenant_id)
        return AuthenticatedPrincipal(
            tenant_id=record.tenant_id,
            actor_id=record.actor_id or record.credential_id,
            actor_type=record.actor_type,
            credential_id=record.credential_id,
            scopes=list(record.scopes),
            roles=list(record.roles),
            property_ids=list(record.property_ids),
        )

    def revoke_credential(self, tenant_id: str, credential_id: str) -> bool:
        return self._set_credential_status(tenant_id, credential_id, "revoked")

    def suspend_credential(self, tenant_id: str, credential_id: str) -> bool:
        return self._set_credential_status(tenant_id, credential_id, "suspended")

    def _set_credential_status(self, tenant_id: str, credential_id: str, status: str) -> bool:
        with self._lock, self._conn:
            stored = self._get("credentials", credential_id)
            if not stored or stored.get("tenant_id") != _safe(tenant_id):
                return False
            stored["status"] = status
            if status == "revoked":
                stored["revoked_at"] = _now()
            self._put("credentials", credential_id, stored, tenant_id=stored.get("tenant_id"))
            return True

    def list_credentials(self, tenant_id: str) -> List[Dict[str, Any]]:
        out = []
        for stored in self._list("credentials", tenant_id):
            record = CredentialRecord.from_dict(stored)
            out.append(record.public_dict())
        return out

    # ------------------------------------------------------------------ agents

    def register_agent(self, tenant_id: str, agent_id: str, name: str, version: str = "",
                       property_ids: Optional[List[str]] = None, data_sources: Optional[List[Dict[str, Any]]] = None) -> tuple[Dict[str, Any], str]:
        self.require_tenant(tenant_id)
        public, raw_secret = self.issue_credential(
            tenant_id, label=f"agent:{name}", scopes=["agent:sync", "cases:write", "documents:write", "cases:read"],
            actor_type="agent", actor_id=agent_id, property_ids=property_ids or [])
        agent = {
            "tenant_id": _safe(tenant_id), "agent_id": agent_id, "name": name, "version": version,
            "status": "active", "credential_id": public["credential_id"], "property_ids": property_ids or [],
            "data_sources": data_sources or [], "registered_at": _now(), "last_seen_at": None,
            "last_success_at": None, "failed_jobs": 0,
        }
        with self._lock, self._conn:
            self._put("agents", f"{_safe(tenant_id)}:{agent_id}", agent, tenant_id=agent["tenant_id"])
        return deepcopy(agent), raw_secret

    def agent_heartbeat(self, tenant_id: str, agent_id: str, version: str = "", status: str = "online") -> Optional[Dict[str, Any]]:
        key = f"{_safe(tenant_id)}:{agent_id}"
        with self._lock, self._conn:
            agent = self._get("agents", key)
            if not agent or agent.get("status") != "active":
                return None
            agent["last_seen_at"] = _now()
            agent["last_success_at"] = _now()
            agent["version"] = version or agent.get("version")
            agent["runtime_status"] = status
            self._put("agents", key, agent, tenant_id=agent.get("tenant_id"))
            return deepcopy(agent)

    def set_agent_status(self, tenant_id: str, agent_id: str, status: str) -> bool:
        key = f"{_safe(tenant_id)}:{agent_id}"
        with self._lock, self._conn:
            agent = self._get("agents", key)
            if not agent:
                return False
            agent["status"] = status
            self._put("agents", key, agent, tenant_id=agent.get("tenant_id"))
            return True

    def list_agents(self, tenant_id: str) -> List[Dict[str, Any]]:
        return [deepcopy(a) for a in self._list("agents", tenant_id)]

    # ------------------------------------------------------------------ cases

    def upsert_case(self, context: TenantContext, case_ref: IntegrationCaseRef, payload: Dict[str, Any]) -> Dict[str, Any]:
        if case_ref.tenant_id != context.tenant_id:
            raise PermissionError("Case tenant does not match authenticated tenant")
        key = f"{context.tenant_id}:{case_ref.case_id}"
        with self._lock, self._conn:
            existing = self._get("cases", key) or {}
            record = {
                **existing,
                "tenant_id": context.tenant_id,
                "case_id": case_ref.case_id,
                "case_ref": case_ref.to_dict(),
                "payload": payload,
                "updated_at": _now(),
                "created_at": existing.get("created_at") or _now(),
                "updated_by": context.actor_id,
            }
            self._put("cases", key, record, tenant_id=context.tenant_id, case_id=case_ref.case_id)
            return deepcopy(record)

    def get_case(self, tenant_id: str, case_id: str) -> Optional[Dict[str, Any]]:
        record = self._get("cases", f"{_safe(tenant_id)}:{case_id}")
        return deepcopy(record) if record else None

    def list_cases(self, tenant_id: str) -> List[Dict[str, Any]]:
        return [deepcopy(v) for v in self._list("cases", tenant_id)]

    # ------------------------------------------------------------------ jobs

    def create_job(self, job: ProcessingJob) -> Dict[str, Any]:
        with self._lock, self._conn:
            if job.idempotency_key:
                row = self._conn.execute(
                    "SELECT payload FROM jobs WHERE tenant_id = ? AND idempotency_key = ?",
                    (job.tenant_id, job.idempotency_key)).fetchone()
                if row:
                    return deepcopy(json.loads(row[0]))
            key = f"{job.tenant_id}:{job.job_id}"
            self._put("jobs", key, job.to_dict(), tenant_id=job.tenant_id,
                      idempotency_key=job.idempotency_key)
            return deepcopy(self._get("jobs", key))

    def update_job(self, job: ProcessingJob) -> Dict[str, Any]:
        job.touch()
        with self._lock, self._conn:
            self._put("jobs", f"{job.tenant_id}:{job.job_id}", job.to_dict(),
                      tenant_id=job.tenant_id, idempotency_key=job.idempotency_key)
            return job.to_dict()

    def get_job(self, tenant_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        record = self._get("jobs", f"{_safe(tenant_id)}:{job_id}")
        return deepcopy(record) if record else None

    # ---------------------------------------------------------------- webhooks

    def put_webhook(self, subscription: Dict[str, Any]) -> Dict[str, Any]:
        """Stores a subscription; any plaintext `secret` is encrypted first."""
        sub = self._protect_webhook_secret(dict(subscription))
        with self._lock, self._conn:
            self._put("webhooks", sub["subscription_id"], sub, tenant_id=sub.get("tenant_id"))
        return deepcopy(sub)

    def get_webhooks(self, tenant_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if tenant_id is not None:
            return [deepcopy(s) for s in self._list("webhooks", tenant_id)]
        rows = self._conn.execute("SELECT payload FROM webhooks").fetchall()
        return [json.loads(r[0]) for r in rows]

    def get_webhook(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        sub = self._get("webhooks", subscription_id)
        return deepcopy(sub) if sub else None

    def webhook_secret(self, subscription: Dict[str, Any]) -> Optional[str]:
        """Resolves the signing secret for a stored subscription, if possible.

        Returns None when the secret cannot be recovered (e.g. the
        encryption key is unavailable) — callers must treat the delivery
        as undeliverable rather than signing with anything else.
        """
        encrypted = subscription.get("secret_encrypted")
        if encrypted:
            return decrypt_secret(encrypted)
        legacy = subscription.get("secret")
        return str(legacy) if legacy else None

    # --------------------------------------------------------------- deliveries

    def find_delivery_by_dedupe(self, dedupe_key: str) -> Optional[Dict[str, Any]]:
        row = self._conn.execute(
            "SELECT payload FROM deliveries WHERE dedupe_key = ?", (dedupe_key,)).fetchone()
        return deepcopy(json.loads(row[0])) if row else None

    def put_delivery(self, key: str, record: Dict[str, Any]) -> Dict[str, Any]:
        with self._lock, self._conn:
            self._put("deliveries", key, record, tenant_id=record.get("tenant_id"),
                      dedupe_key=record.get("dedupe_key"))
        return deepcopy(record)

    def get_delivery(self, key: str) -> Optional[Dict[str, Any]]:
        record = self._get("deliveries", key)
        return deepcopy(record) if record else None

    def list_deliveries(self, tenant_id: str) -> List[Dict[str, Any]]:
        return [deepcopy(d) for d in self._list("deliveries", tenant_id)]

    def due_deliveries(self, now_iso: str) -> List[Dict[str, Any]]:
        rows = self._conn.execute("SELECT payload FROM deliveries").fetchall()
        out = []
        for row in rows:
            record = json.loads(row[0])
            if record.get("status") == "retrying" and (record.get("next_attempt_at") or "") <= now_iso:
                out.append(record)
        return out

    # --------------------------------------------------------------- monitoring

    def monitoring_snapshot(self, tenant_id: str) -> Dict[str, Any]:
        tenant_key = _safe(tenant_id)
        agents = self.list_agents(tenant_id)
        jobs = self._list("jobs", tenant_id)
        deliveries = self.list_deliveries(tenant_id)
        return {
            "tenant_id": tenant_key,
            "agents": {"total": len(agents), "active": sum(1 for a in agents if a.get("status") == "active")},
            "cases": len(self.list_cases(tenant_id)),
            "jobs": {
                "total": len(jobs),
                "failed": sum(1 for j in jobs if j.get("status") in ("failed", "dead_letter")),
                "queued": sum(1 for j in jobs if j.get("status") == "queued"),
            },
            "webhook_deliveries": {
                "total": len(deliveries),
                "failed": sum(1 for d in deliveries if d.get("status") == "failed"),
                "delivered": sum(1 for d in deliveries if d.get("status") == "delivered"),
            },
            "credentials": len(self.list_credentials(tenant_id)),
        }
