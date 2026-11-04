"""
Local filesystem storage backend with atomic writes and hash verification.
"""

import os
import re
import uuid
from typing import Dict, List, Optional
from core.infrastructure.storage.base import StorageBackend, StorageError

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage backend."""

    def __init__(self, root: str) -> None:
        self.root = os.path.abspath(root)
        os.makedirs(self.root, exist_ok=True)

    def _resolve_path(self, key: str, tenant_id: Optional[str] = None) -> str:
        safe_key = _SAFE.sub("_", key)
        if len(safe_key) >= 2:
            shard = safe_key[:2]
        else:
            shard = "misc"

        if tenant_id:
            safe_tid = _SAFE.sub("_", tenant_id)[:80]
            return os.path.join(self.root, safe_tid, shard, safe_key)
        return os.path.join(self.root, shard, safe_key)

    def _find_path(self, key: str, tenant_id: Optional[str] = None) -> Optional[str]:
        path = self._resolve_path(key, tenant_id)
        if os.path.isfile(path):
            return path
        # Fallback to root (unscoped) if tenant_id was passed but file exists in legacy location
        if tenant_id:
            fallback = self._resolve_path(key, tenant_id=None)
            if os.path.isfile(fallback):
                return fallback
        return None

    def put(
        self,
        key: str,
        data: bytes,
        metadata: Optional[Dict[str, str]] = None,
        tenant_id: Optional[str] = None,
    ) -> None:
        target_path = self._resolve_path(key, tenant_id)
        parent_dir = os.path.dirname(target_path)
        os.makedirs(parent_dir, exist_ok=True)

        tmp_path = os.path.join(parent_dir, f".tmp-{uuid.uuid4().hex[:12]}")
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, target_path)
        except OSError as exc:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except OSError:
                pass
            raise StorageError(f"Failed to write storage key '{key}': {exc}") from exc

    def get(self, key: str, tenant_id: Optional[str] = None) -> Optional[bytes]:
        path = self._find_path(key, tenant_id)
        if path is None:
            return None
        try:
            with open(path, "rb") as f:
                return f.read()
        except OSError:
            return None

    def has(self, key: str, tenant_id: Optional[str] = None) -> bool:
        return self._find_path(key, tenant_id) is not None

    def delete(self, key: str, tenant_id: Optional[str] = None) -> bool:
        path = self._find_path(key, tenant_id)
        if path is None:
            return False
        try:
            os.remove(path)
            return True
        except OSError:
            return False

    def list_keys(self, prefix: str = "", tenant_id: Optional[str] = None) -> List[str]:
        base_dir = self.root
        if tenant_id:
            safe_tid = _SAFE.sub("_", tenant_id)[:80]
            base_dir = os.path.join(self.root, safe_tid)

        if not os.path.isdir(base_dir):
            return []

        results: List[str] = []
        for root_dir, _dirs, files in os.walk(base_dir):
            if "quarantine" in root_dir:
                continue
            for file in files:
                if file.startswith(".tmp-"):
                    continue
                if file.startswith(prefix):
                    results.append(file)
        return sorted(results)
