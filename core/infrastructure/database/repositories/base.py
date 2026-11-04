"""
Abstract Base Class for Case Repositories.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class CaseRepository(ABC):
    """Abstract interface for dispute case persistence."""

    @abstractmethod
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
        """Saves or updates a case. Returns dict with {case_id, created_at, updated_at}."""

    @abstractmethod
    def get(self, case_id: str, tenant_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieves a case by ID with tenant verification."""

    @abstractmethod
    def list(self, tenant_id: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """Lists cases scoped by tenant."""

    @abstractmethod
    def delete(self, case_id: str, tenant_id: Optional[str] = None) -> bool:
        """Deletes a case with tenant authorization."""
