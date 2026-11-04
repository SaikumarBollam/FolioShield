"""
Tenant-scoped integration registry.

Stores tenants, credentials, agents, webhook subscriptions, cases, jobs,
and webhook deliveries in a local JSON registry. This is the v1 enterprise
integration store behind a small interface; it can be replaced by SQLite or
hosted storage without changing API/agent callers.

Security properties:
- Records are partitioned by tenant_id.
- Credential secrets are never stored raw.
- Case lookups require tenant_id and internal case_id.
- Revoked/suspended credentials and agents fail closed.
"""

from __future__ import annotations

import json
import os
import re
import threading
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .authentication import CredentialRecord, generate_api_key, hash_secret, verify_secret
from .contracts import IntegrationCaseRef, ProcessingJob, TenantContext

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(value: str) -> str:
    return _SAFE.sub("_", value or "unknown")[:100]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IntegrationRegistry:
    """File-backed tenant/integration registry (v1)."""

    def __init__(self, root: str | Path = "data/integrations"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._path = self.root / "registry.json"
        self._lock = threading.RLock()
        self._data = self._load()

    # ------------------------------------------------------------------ storage

    def _load(self) -> Dict[str, Any]:
        if not self._path.exists():
            return {"tenants": {}, "credentials": {}, "agents": {}, "webhooks": {}, "cases": {}, "jobs": {}, "deliveries": {}}
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"tenants": {}, "credentials": {}, "agents": {}, "webhooks": {}, "cases": {}, "jobs": {}, "deliveries": {}}
        for key in ("tenants", "credentials", "agents", "webhooks", "cases", "jobs", "deliveries"):
            data.setdefault(key, {})
        return data

    def _save(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, default=str), encoding="utf-8")
        os.replace(tmp, self._path)

    # ------------------------------------------------------------------ tenants

    def create_tenant(self, tenant_id: str, name: str, property_ids: Optional[List[str]] = None) -> Dict[str, Any]:
        tenant_id = _safe(tenant_id)
        with self._lock:
            tenant = {"tenant_id": tenant_id, "name": name, "property_ids": property_ids or [],
                      "status": "active", "created_at": _now()}
            self._data["tenants"][tenant_id] = tenant
            self._save()
            return deepcopy(tenant)

    def get_tenant(self, tenant_id: str) -> Optional[Dict[str, Any]]:
        tenant = self._data["tenants"].get(_safe(tenant_id))
        return deepcopy(tenant) if tenant else None

    def require_tenant(self, tenant_id: str) -> Dict[str, Any]:
        tenant = self.get_tenant(tenant_id)
        if not tenant or tenant.get("status") != "active":
            raise PermissionError("Tenant is not active")
        return tenant

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
        with self._lock:
            self._data["credentials"][credential_id] = record.to_dict()
            self._save()
        return record.public_dict(), raw_secret

    def authenticate(self, raw_secret: str):
        from .authentication import AuthenticatedPrincipal, credential_id_from_secret

        credential_id = credential_id_from_secret(raw_secret or "")
        if not credential_id:
            return None
        stored = self._data["credentials"].get(credential_id)
        if not stored:
            return None
        record = CredentialRecord.from_dict(stored)
        if not record.is_usable() or not verify_secret(raw_secret, record.secret_hash):
            return None
        tenant = self.get_tenant(record.tenant_id)
        if not tenant or tenant.get("status") != "active":
            return None
        with self._lock:
            record.last_used_at = _now()
            self._data["credentials"][credential_id] = record.to_dict()
            self._save()
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
        with self._lock:
            stored = self._data["credentials"].get(credential_id)
            if not stored or stored.get("tenant_id") != _safe(tenant_id):
                return False
            stored["status"] = status
            if status == "revoked":
                stored["revoked_at"] = _now()
            self._save()
            return True

    def list_credentials(self, tenant_id: str) -> List[Dict[str, Any]]:
        out = []
        for stored in self._data["credentials"].values():
            if stored.get("tenant_id") == _safe(tenant_id):
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
        with self._lock:
            self._data["agents"][f"{_safe(tenant_id)}:{agent_id}"] = agent
            self._save()
        return deepcopy(agent), raw_secret

    def agent_heartbeat(self, tenant_id: str, agent_id: str, version: str = "", status: str = "online") -> Optional[Dict[str, Any]]:
        key = f"{_safe(tenant_id)}:{agent_id}"
        with self._lock:
            agent = self._data["agents"].get(key)
            if not agent or agent.get("status") != "active":
                return None
            agent["last_seen_at"] = _now()
            agent["last_success_at"] = _now()
            agent["version"] = version or agent.get("version")
            agent["runtime_status"] = status
            self._save()
            return deepcopy(agent)

    def set_agent_status(self, tenant_id: str, agent_id: str, status: str) -> bool:
        key = f"{_safe(tenant_id)}:{agent_id}"
        with self._lock:
            agent = self._data["agents"].get(key)
            if not agent:
                return False
            agent["status"] = status
            self._save()
            return True

    def list_agents(self, tenant_id: str) -> List[Dict[str, Any]]:
        return [deepcopy(a) for a in self._data["agents"].values() if a.get("tenant_id") == _safe(tenant_id)]

    # ------------------------------------------------------------------ cases

    def upsert_case(self, context: TenantContext, case_ref: IntegrationCaseRef, payload: Dict[str, Any]) -> Dict[str, Any]:
        if case_ref.tenant_id != context.tenant_id:
            raise PermissionError("Case tenant does not match authenticated tenant")
        key = f"{context.tenant_id}:{case_ref.case_id}"
        with self._lock:
            existing = self._data["cases"].get(key, {})
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
            self._data["cases"][key] = record
            self._save()
            return deepcopy(record)

    def get_case(self, tenant_id: str, case_id: str) -> Optional[Dict[str, Any]]:
        record = self._data["cases"].get(f"{_safe(tenant_id)}:{case_id}")
        return deepcopy(record) if record else None

    def list_cases(self, tenant_id: str) -> List[Dict[str, Any]]:
        prefix = f"{_safe(tenant_id)}:"
        return [deepcopy(v) for k, v in self._data["cases"].items() if k.startswith(prefix)]

    # ------------------------------------------------------------------ jobs

    def create_job(self, job: ProcessingJob) -> Dict[str, Any]:
        with self._lock:
            key = f"{job.tenant_id}:{job.job_id}"
            if job.idempotency_key:
                for existing in self._data["jobs"].values():
                    if existing.get("tenant_id") == job.tenant_id and existing.get("idempotency_key") == job.idempotency_key:
                        return deepcopy(existing)
            self._data["jobs"][key] = job.to_dict()
            self._save()
            return deepcopy(self._data["jobs"][key])

    def update_job(self, job: ProcessingJob) -> Dict[str, Any]:
        job.touch()
        with self._lock:
            self._data["jobs"][f"{job.tenant_id}:{job.job_id}"] = job.to_dict()
            self._save()
            return job.to_dict()

    def get_job(self, tenant_id: str, job_id: str) -> Optional[Dict[str, Any]]:
        record = self._data["jobs"].get(f"{_safe(tenant_id)}:{job_id}")
        return deepcopy(record) if record else None

    # --------------------------------------------------------------- monitoring

    def monitoring_snapshot(self, tenant_id: str) -> Dict[str, Any]:
        tenant_key = _safe(tenant_id)
        agents = self.list_agents(tenant_id)
        jobs = [j for j in self._data["jobs"].values() if j.get("tenant_id") == tenant_key]
        deliveries = [d for d in self._data["deliveries"].values() if d.get("tenant_id") == tenant_key]
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
