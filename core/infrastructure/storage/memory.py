"""
In-memory storage backend for testing and ephemeral execution.
"""

from typing import Dict, List, Optional
from core.infrastructure.storage.base import StorageBackend


class MemoryStorageBackend(StorageBackend):
    """In-memory storage backend."""

    def __init__(self) -> None:
        self._data: Dict[str, bytes] = {}
        self._metadata: Dict[str, Dict[str, str]] = {}

    def _scoped_key(self, key: str, tenant_id: Optional[str] = None) -> str:
        if tenant_id:
            return f"tenant::{tenant_id}::{key}"
        return f"global::{key}"

    def put(
        self,
        key: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        k = self._scoped_key(key, tenant_id)
        self._data[k] = bytes(data)
        if metadata:
            self._metadata[k] = dict(metadata)

    def get(self, key: str, tenant_id: Optional[str] = None) -> Optional[bytes]:
        k = self._scoped_key(key, tenant_id)
        if k in self._data:
            return self._data[k]
        # Backward compatibility fallback if queried with tenant_id but stored globally
        if tenant_id and f"global::{key}" in self._data:
            return self._data[f"global::{key}"]
        return None

    def has(self, key: str, tenant_id: Optional[str] = None) -> bool:
        return self.get(key, tenant_id=tenant_id) is not None

    def delete(self, key: str, tenant_id: Optional[str] = None) -> bool:
        k = self._scoped_key(key, tenant_id)
        existed = False
        if k in self._data:
            del self._data[k]
            self._metadata.pop(k, None)
            existed = True
        if tenant_id and f"global::{key}" in self._data:
            del self._data[f"global::{key}"]
            self._metadata.pop(f"global::{key}", None)
            existed = True
        return existed

    def list_keys(self, prefix: str = "", tenant_id: Optional[str] = None) -> List[str]:
        scope_prefix = f"tenant::{tenant_id}::" if tenant_id else "global::"
        res: List[str] = []
        for k in self._data:
            if k.startswith(scope_prefix):
                raw_key = k[len(scope_prefix):]
                if raw_key.startswith(prefix):
                    res.append(raw_key)
        return sorted(res)
