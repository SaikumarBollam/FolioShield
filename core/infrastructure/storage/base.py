"""
Abstract base class and error definitions for storage backends.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Optional


class StorageError(OSError):
    """Base exception for storage backend operations."""


class StorageBackend(ABC):
    """Abstract interface for storing and retrieving binary documents/exhibits."""

    @abstractmethod
    def put(
        self,
        key: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        """Store bytes associated with key and optional tenant_id."""

    @abstractmethod
    def get(self, key: str, tenant_id: Optional[str] = None) -> Optional[bytes]:
        """Retrieve bytes associated with key and optional tenant_id, or None if absent."""

    @abstractmethod
    def has(self, key: str, tenant_id: Optional[str] = None) -> bool:
        """Check whether key exists in storage."""

    @abstractmethod
    def delete(self, key: str, tenant_id: Optional[str] = None) -> bool:
        """Delete key from storage; return True if deleted, False if not found."""

    @abstractmethod
    def list_keys(self, prefix: str = "", tenant_id: Optional[str] = None) -> List[str]:
        """List keys matching prefix for a tenant."""
