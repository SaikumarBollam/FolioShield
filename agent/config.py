"""
Agent configuration.

Configuration is local to the customer machine. Secrets are referenced by
environment variable name or a local credential file path; example configs
must never contain real secrets.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class SourceConfig:
    source_id: str
    kind: str  # filesystem / rest / sql
    path: str = ""  # filesystem path or REST base URL or DB connection reference
    enabled: bool = True
    schedule_seconds: int = 300
    include_patterns: List[str] = field(default_factory=lambda: ["*.pdf", "*.csv"])
    field_selection: List[str] = field(default_factory=list)
    options: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentConfig:
    tenant_id: str
    agent_id: str
    agent_name: str = "FolioShield Connector Agent"
    server_url: str = "https://localhost:8000"
    credential_env: str = "FOLIOSHIELD_AGENT_API_KEY"
    credential_file: str = ""
    queue_path: str = "agent_queue.sqlite3"
    state_path: str = "agent_state.json"
    heartbeat_seconds: int = 60
    max_attempts: int = 5
    backoff_base_seconds: int = 5
    backoff_max_seconds: int = 300
    minimize_data: bool = True
    allowed_document_types: List[str] = field(default_factory=lambda: ["dispute_notice", "guest_folio", "supporting_evidence"])
    sources: List[SourceConfig] = field(default_factory=list)
    version: str = "0.1.0"

    @property
    def api_key(self) -> str:
        if self.credential_file:
            path = Path(self.credential_file)
            if path.exists():
                return path.read_text(encoding="utf-8").strip()
        return os.getenv(self.credential_env, "").strip()

    def save_credential_file(self, secret: str) -> None:
        if not self.credential_file:
            raise ValueError("credential_file is not configured")
        path = Path(self.credential_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(secret, encoding="utf-8")
        try:
            os.chmod(path, 0o600)
        except OSError:
            # Windows ACLs differ; document that the file must be ACL-restricted.
            pass

    def to_dict(self, include_secret: bool = False) -> Dict[str, Any]:
        data = asdict(self)
        if not include_secret:
            data.pop("credential_file", None)
        return data

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentConfig":
        sources = [SourceConfig(**s) if isinstance(s, dict) else s for s in data.get("sources", [])]
        valid = {f for f in cls.__dataclass_fields__}
        payload = {k: v for k, v in data.items() if k in valid}
        payload["sources"] = sources
        return cls(**payload)

    @classmethod
    def load(cls, path: str | Path) -> "AgentConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(include_secret=True), indent=2), encoding="utf-8")
