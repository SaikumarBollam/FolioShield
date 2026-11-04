"""
Exhibit Store for FolioShield (Phase 6: Bank Submission).

Retains the actual bytes of collected evidence files so exhibits can be
bundled and submitted — previously the UI hashed uploads and discarded the
bytes, making attachment impossible.

Storage is content-addressed: files are keyed by their SHA-256 and written
under `<root>/<sha256[:2]>/<sha256><ext>` when a root directory is given.
The store also works purely in memory (root=None) for tests/headless use.
EvidenceItem.stored_ref carries the SHA-256 key.
"""

import hashlib
import os
from typing import Dict, Optional

_MIME_BY_EXT = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".csv": "text/csv", ".txt": "text/plain",
    ".eml": "message/rfc822",
}


def mime_for(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


class ExhibitStore:
    """Content-addressed retention for evidence file bytes."""

    def __init__(self, root: Optional[str] = None):
        self.root = root
        self._memory: Dict[str, bytes] = {}
        if root:
            os.makedirs(root, exist_ok=True)

    def _path_for(self, sha256: str, filename: str) -> str:
        ext = os.path.splitext(filename or "")[1].lower()
        return os.path.join(self.root, sha256[:2], f"{sha256}{ext}")  # type: ignore[arg-type]

    def put(self, data: bytes, filename: str) -> Dict[str, object]:
        """Stores bytes; returns {sha256, size_bytes, mime, stored_ref}."""
        sha256 = hashlib.sha256(data).hexdigest()
        self._memory[sha256] = data
        if self.root:
            path = self._path_for(sha256, filename)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if not os.path.exists(path):
                with open(path, "wb") as f:
                    f.write(data)
        return {
            "sha256": sha256,
            "size_bytes": len(data),
            "mime": mime_for(filename),
            "stored_ref": sha256,
        }

    def get(self, stored_ref: Optional[str], filename: str = "") -> Optional[bytes]:
        if not stored_ref:
            return None
        if stored_ref in self._memory:
            return self._memory[stored_ref]
        if self.root:
            path = self._path_for(stored_ref, filename)
            if os.path.exists(path):
                with open(path, "rb") as f:
                    data = f.read()
                self._memory[stored_ref] = data
                return data
            # Extension may differ from the original filename; scan the shard.
            shard = os.path.join(self.root, stored_ref[:2])
            if os.path.isdir(shard):
                for name in os.listdir(shard):
                    if name.startswith(stored_ref):
                        with open(os.path.join(shard, name), "rb") as f:
                            data = f.read()
                        self._memory[stored_ref] = data
                        return data
        return None

    def has(self, stored_ref: Optional[str], filename: str = "") -> bool:
        return self.get(stored_ref, filename) is not None
