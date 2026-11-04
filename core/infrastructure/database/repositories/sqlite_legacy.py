"""
Adapter implementing CaseRepository on top of legacy CaseStore.
"""

from typing import Any, Dict, List, Optional
from core.case_store import CaseStore
from core.infrastructure.database.repositories.base import CaseRepository


class SqliteLegacyCaseRepository(CaseRepository):
    """Adapter wrapping the legacy CaseStore as a CaseRepository."""

    def __init__(self, store: Optional[CaseStore] = None) -> None:
        self.store = store or CaseStore()

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
        return self.store.save_case(
            case_id=case_id,
            notice=notice,
            folio=folio,
            evidence_items=evidence_items,
            draft_text=draft_text,
            policy_text=policy_text,
            custom_notes=custom_notes,
            approval=approval,
            fingerprint=fingerprint,
            audit_session_id=audit_session_id,
            audit_head_hash=audit_head_hash,
            audit_event_count=audit_event_count,
            tenant_id=tenant_id,
            status=status,
            expected_updated_at=expected_updated_at,
        )

    def get(self, case_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        return self.store.load_case(case_id, tenant_id=tenant_id)

    def list(self, tenant_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        return self.store.list_cases(tenant_id=tenant_id)[:limit]

    def delete(self, case_id: str, tenant_id: Optional[str] = None) -> bool:
        return self.store.delete_case(case_id, tenant_id=tenant_id)

    def close(self) -> None:
        if hasattr(self.store, "close"):
            self.store.close()
