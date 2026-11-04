"""
Connector protocol and built-in source connectors.

Connectors only collect authorized documents/records and normalize them
into agent jobs. They do not run dispute processing locally and do not
submit anything to banks.

SQL connectors are intentionally protocol-only in this iteration: real
SQL Server/PostgreSQL access requires vendor/driver validation against
customer systems and must not be represented as production-verified.
"""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any, Dict, Iterable, List, Protocol

from .config import SourceConfig


class Connector(Protocol):
    source_id: str

    def discover(self) -> Iterable[Dict[str, Any]]:
        """Yield normalized document jobs: {case_id, document_type, filename, media_type, data, evidence_doc_type}."""
        ...


def _media_type(filename: str) -> str:
    ext = Path(filename).suffix.lower()
    return {".pdf": "application/pdf", ".csv": "text/csv", ".png": "image/png",
            ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".txt": "text/plain",
            ".eml": "message/rfc822"}.get(ext, "application/octet-stream")


def infer_document_type(filename: str) -> str:
    name = filename.lower()
    if "notice" in name or "dispute" in name or "chargeback" in name:
        return "dispute_notice"
    if "folio" in name or "ledger" in name or "guest" in name:
        return "guest_folio"
    return "supporting_evidence"


class FilesystemConnector:
    """Collects PDF/CSV/image documents from an authorized local folder."""

    def __init__(self, config: SourceConfig):
        self.config = config
        self.source_id = config.source_id

    def discover(self) -> Iterable[Dict[str, Any]]:
        root = Path(self.config.path)
        if not root.exists():
            return []
        jobs: List[Dict[str, Any]] = []
        patterns = self.config.include_patterns or ["*.pdf", "*.csv"]
        seen: set[Path] = set()
        for pattern in patterns:
            for path in root.rglob(pattern):
                if path in seen or not path.is_file():
                    continue
                seen.add(path)
                data = path.read_bytes()
                # Case ID convention: parent folder name or filename stem prefix.
                case_hint = path.parent.name if path.parent != root else path.stem.split("_")[0]
                jobs.append({
                    "case_id": case_hint,
                    "document_type": infer_document_type(path.name),
                    "filename": path.name,
                    "media_type": _media_type(path.name),
                    "data": data,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "source_path": str(path),
                    "evidence_doc_type": self.config.options.get("evidence_doc_type"),
                })
        return jobs


class RestConnector:
    """Collects documents from an authorized local REST endpoint.

    Expected endpoint contract (customer-controlled): GET returns JSON list
    of {case_id, document_type, filename, media_type, content_base64,
    evidence_doc_type}. This is a generic adapter, not a PMS vendor claim.
    """

    def __init__(self, config: SourceConfig):
        self.config = config
        self.source_id = config.source_id

    def discover(self) -> Iterable[Dict[str, Any]]:
        import base64

        import requests

        headers: Dict[str, str] = {}
        token_env = self.config.options.get("token_env")
        if token_env and os.getenv(token_env):
            headers["Authorization"] = f"Bearer {os.getenv(token_env)}"
        response = requests.get(self.config.path, headers=headers, timeout=20)
        response.raise_for_status()
        items = response.json()
        if not isinstance(items, list):
            raise ValueError("REST connector endpoint must return a JSON list")
        jobs = []
        for item in items:
            data = base64.b64decode(str(item.get("content_base64") or ""), validate=True)
            jobs.append({
                "case_id": item.get("case_id"),
                "document_type": item.get("document_type") or infer_document_type(str(item.get("filename") or "")),
                "filename": item.get("filename") or "document.bin",
                "media_type": item.get("media_type") or _media_type(str(item.get("filename") or "")),
                "data": data,
                "sha256": hashlib.sha256(data).hexdigest(),
                "evidence_doc_type": item.get("evidence_doc_type"),
            })
        return jobs


class SqlConnector:
    """
    SQL connector protocol placeholder.

    Requires vendor validation: production SQL Server/PostgreSQL access
    depends on customer schema, drivers, network policy, and read-only
    credentials. This class deliberately refuses to run until a validated
    query adapter is supplied.
    """

    def __init__(self, config: SourceConfig):
        self.config = config
        self.source_id = config.source_id

    def discover(self) -> Iterable[Dict[str, Any]]:
        raise NotImplementedError(
            "SQL connector requires vendor validation (driver, schema, read-only credentials). "
            "Use filesystem or REST connectors until a customer-specific SQL adapter is validated."
        )


CONNECTOR_TYPES = {
    "filesystem": FilesystemConnector,
    "rest": RestConnector,
    "sql": SqlConnector,
}


def create_connector(config: SourceConfig):
    connector_cls = CONNECTOR_TYPES.get(config.kind)
    if not connector_cls:
        raise ValueError(f"Unsupported connector kind: {config.kind}")
    return connector_cls(config)


def minimize_payload(payload: Dict[str, Any], field_selection: List[str]) -> Dict[str, Any]:
    """Keep only selected top-level fields when field selection is configured."""
    if not field_selection:
        return payload
    return {k: v for k, v in payload.items() if k in field_selection}
