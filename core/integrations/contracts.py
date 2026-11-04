"""
Canonical integration contracts for FolioShield.

These transport/integration envelopes wrap the existing business models
(core.models.NoticeData/FolioData/EvidenceItem and reconciliation dicts).
They intentionally do not duplicate dispute-processing data structures.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TenantContext:
    """Server-resolved tenant and actor context. Never trust raw client roles."""

    tenant_id: str
    actor_id: str = "system"
    actor_type: str = "api_client"  # api_client / agent / user / system
    property_ids: List[str] = field(default_factory=list)
    roles: List[str] = field(default_factory=list)
    scopes: List[str] = field(default_factory=list)
    request_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    credential_id: Optional[str] = None

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes or "*" in self.scopes

    def require_scope(self, scope: str) -> None:
        if not self.has_scope(scope):
            raise PermissionError(f"Missing required scope: {scope}")

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrationCaseRef:
    """Maps external-system identifiers to a FolioShield internal case."""

    tenant_id: str
    case_id: str  # FolioShield internal case identifier
    external_system: Optional[str] = None
    external_case_id: Optional[str] = None
    external_folio_id: Optional[str] = None
    external_transaction_id: Optional[str] = None
    property_id: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntegrationCaseRef":
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class DocumentSubmission:
    """Metadata for a document submitted through an integration channel."""

    document_type: str  # dispute_notice / guest_folio / supporting_evidence
    filename: str
    media_type: str
    size_bytes: int
    sha256: str
    source: str = "api"
    external_reference: Optional[str] = None
    evidence_doc_type: Optional[str] = None
    stored_ref: Optional[str] = None

    @classmethod
    def for_bytes(cls, document_type: str, filename: str, media_type: str, data: bytes,
                  source: str = "api", external_reference: Optional[str] = None,
                  evidence_doc_type: Optional[str] = None,
                  stored_ref: Optional[str] = None) -> "DocumentSubmission":
        return cls(
            document_type=document_type,
            filename=filename,
            media_type=media_type,
            size_bytes=len(data),
            sha256=hashlib.sha256(data).hexdigest(),
            source=source,
            external_reference=external_reference,
            evidence_doc_type=evidence_doc_type,
            stored_ref=stored_ref,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ProcessingJob:
    """Durable processing job envelope used by API and agent synchronization."""

    job_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tenant_id: str = ""
    case_id: Optional[str] = None
    job_type: str = "process_dispute"
    status: str = "queued"  # queued / running / succeeded / failed / dead_letter
    attempts: int = 0
    max_attempts: int = 5
    idempotency_key: Optional[str] = None
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
    next_attempt_at: Optional[str] = None
    last_error: Optional[str] = None
    result: Dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.updated_at = utc_now_iso()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProcessingJob":
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


@dataclass
class ApprovalReference:
    """Reference to an explicit human approval. Machine processing is not approval."""

    case_id: str
    tenant_id: str
    approved_by: str
    approved_at: str
    approval_fingerprint: str
    approver_role: Optional[str] = None
    audit_event_hash: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class IntegrationEvent:
    """Canonical event envelope for webhooks and integration monitoring."""

    event_type: str
    tenant_id: str
    case_id: Optional[str] = None
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(default_factory=utc_now_iso)
    actor_id: Optional[str] = None
    data: Dict[str, Any] = field(default_factory=dict)

    def payload_bytes(self) -> bytes:
        return json.dumps(self.to_dict(), sort_keys=True, default=str).encode("utf-8")

    def payload_hash(self) -> str:
        return hashlib.sha256(self.payload_bytes()).hexdigest()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "IntegrationEvent":
        valid = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid})


EVENT_TYPES = (
    "dispute.received",
    "document.processed",
    "reconciliation.completed",
    "evidence.missing_identified",
    "rebuttal.drafted",
    "approval.recorded",
    "packet.generated",
    "processing.failed",
    "submission.registered",
    "outcome.recorded",
)
