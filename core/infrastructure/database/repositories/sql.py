"""
SQLAlchemy-backed implementation of CaseRepository.
"""

import json
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select

from core.case_store import CaseConflictError
from core.infrastructure.database.models import CaseModel
from core.infrastructure.database.repositories.base import CaseRepository
from core.infrastructure.database.session import DatabaseEngine, get_db_session


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dumps(val: Any) -> str:
    return json.dumps(val, ensure_ascii=False) if val is not None else "{}"


def _loads(val: Optional[str]) -> Any:
    return json.loads(val) if val else None


class SqlCaseRepository(CaseRepository):
    """SQLAlchemy repository for dispute cases."""

    def __init__(self, engine: Optional[DatabaseEngine] = None) -> None:
        self.engine = engine or DatabaseEngine()
        self.engine.create_all()

    def save(
        self,
        case_id: str,
        notice: Dict[str, Any],
        folio: Dict[str, Any],
        evidence_items: Optional[Dict[str, Any]] = None,
        draft_text: Optional[str] = None,
        policy_text: Optional[str] = None,
        custom_notes: Optional[str] = None,
        approval: Optional[Dict[str, Any]] = None,
        fingerprint: Optional[str] = None,
        audit_session_id: Optional[str] = None,
        audit_head_hash: Optional[str] = None,
        audit_event_count: Optional[int] = None,
        tenant_id: Optional[str] = None,
        status: Optional[str] = None,
        expected_updated_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not case_id:
            raise ValueError("case_id is required")

        now = _now()
        with get_db_session(self.engine) as session:
            stmt = select(CaseModel).where(CaseModel.case_id == case_id)
            existing = session.scalars(stmt).first()

            if existing:
                # Optimistic lock check
                if expected_updated_at is not None and existing.updated_at != expected_updated_at:
                    raise CaseConflictError(
                        f"Case '{case_id}' was modified at {existing.updated_at} by another session."
                    )
                # Tenant isolation check
                if tenant_id and existing.tenant_id and existing.tenant_id != tenant_id:
                    raise PermissionError(f"Case '{case_id}' belongs to another tenant.")

                eff_tenant = existing.tenant_id if (existing.tenant_id and not tenant_id) else tenant_id
                created_at = existing.created_at

                existing.tenant_id = eff_tenant
                existing.updated_at = now
                existing.status = status or existing.status
                existing.notice_json = _dumps(notice)
                existing.folio_json = _dumps(folio)
                existing.evidence_items_json = _dumps(evidence_items) if evidence_items else None
                existing.draft_text = draft_text
                existing.policy_text = policy_text
                existing.custom_notes = custom_notes
                existing.approval_json = _dumps(approval) if approval else None
                existing.fingerprint = fingerprint
                existing.audit_session_id = audit_session_id
                existing.audit_head_hash = audit_head_hash
                existing.audit_event_count = audit_event_count or existing.audit_event_count
            else:
                created_at = now
                new_case = CaseModel(
                    case_id=case_id,
                    tenant_id=tenant_id,
                    created_at=created_at,
                    updated_at=now,
                    status=status or "open",
                    notice_json=_dumps(notice),
                    folio_json=_dumps(folio),
                    evidence_items_json=_dumps(evidence_items) if evidence_items else None,
                    draft_text=draft_text,
                    policy_text=policy_text,
                    custom_notes=custom_notes,
                    approval_json=_dumps(approval) if approval else None,
                    fingerprint=fingerprint,
                    audit_session_id=audit_session_id,
                    audit_head_hash=audit_head_hash,
                    audit_event_count=audit_event_count or 0,
                )
                session.add(new_case)

        return {"case_id": case_id, "created_at": created_at, "updated_at": now}

    def get(self, case_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        with get_db_session(self.engine) as session:
            stmt = select(CaseModel).where(CaseModel.case_id == case_id)
            model = session.scalars(stmt).first()
            if not model:
                return None

            if tenant_id and model.tenant_id and model.tenant_id != tenant_id:
                return None

            return {
                "case_id": model.case_id,
                "tenant_id": model.tenant_id,
                "created_at": model.created_at,
                "updated_at": model.updated_at,
                "status": model.status,
                "notice": _loads(model.notice_json) or {},
                "folio": _loads(model.folio_json) or {},
                "evidence_items": _loads(model.evidence_items_json) or {},
                "draft_text": model.draft_text,
                "policy_text": model.policy_text,
                "custom_notes": model.custom_notes,
                "approval": _loads(model.approval_json),
                "fingerprint": model.fingerprint,
                "audit_session_id": model.audit_session_id,
                "audit_head_hash": model.audit_head_hash,
                "audit_event_count": model.audit_event_count,
            }

    def list(self, tenant_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        with get_db_session(self.engine) as session:
            stmt = select(CaseModel).order_by(CaseModel.updated_at.desc()).limit(limit)
            if tenant_id:
                stmt = stmt.where(CaseModel.tenant_id == tenant_id)

            models = session.scalars(stmt).all()
            return [
                {
                    "case_id": m.case_id,
                    "tenant_id": m.tenant_id,
                    "created_at": m.created_at,
                    "updated_at": m.updated_at,
                    "status": m.status,
                    "disputed_amount": (_loads(m.notice_json) or {}).get("disputed_amount"),
                    "guest_name": (_loads(m.folio_json) or {}).get("guest_name"),
                }
                for m in models
            ]

    def delete(self, case_id: str, tenant_id: Optional[str] = None) -> bool:
        with get_db_session(self.engine) as session:
            stmt = select(CaseModel).where(CaseModel.case_id == case_id)
            model = session.scalars(stmt).first()
            if not model:
                return False

            if tenant_id and model.tenant_id and model.tenant_id != tenant_id:
                return False

            session.delete(model)
            return True
