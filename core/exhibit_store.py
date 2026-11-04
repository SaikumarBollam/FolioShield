"""
Exhibit Store for FolioShield (Phase 6: Bank Submission; Phase 1 P0 hardening).

Retains the actual bytes of collected evidence files so exhibits can be
bundled and submitted — previously the UI hashed uploads and discarded the
bytes, making attachment impossible.

Storage is content-addressed: files are keyed by their SHA-256 and written
under `<root>/<sha256[:2]>/<sha256><ext>` when a root directory is given.
The store also works purely in memory (root=None) for tests/headless use.
EvidenceItem.stored_ref carries the SHA-256 key.

Fail-safety guarantees (Phase 1 P0):
  * Writes are atomic: bytes go to a temp file in the target shard, are
    fsynced, then os.replace()d into place. A crash can only orphan a
    temp file — never a truncated exhibit at its content address.
  * Writes are verified: the file on disk is re-hashed after the replace;
    a mismatch deletes the file and raises ExhibitStoreError.
  * Reads are verified: get() hashes the bytes it returns. Corrupt bytes
    are quarantined under <root>/quarantine/ and get() returns None, so
    callers honestly report the exhibit as "not retained".
"""

import hashlib
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

_MIME_BY_EXT = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".csv": "text/csv", ".txt": "text/plain",
    ".eml": "message/rfc822",
}


class ExhibitStoreError(OSError):
    """Raised when exhibit bytes cannot be durably stored or verified."""


def mime_for(filename: str) -> str:
    ext = os.path.splitext(filename or "")[1].lower()
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


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

    def _find_on_disk(self, stored_ref: str, filename: str = "") -> Optional[str]:
        """Locates the stored file for a ref (exact path, else shard scan)."""
        if not self.root:
            return None
        path = self._path_for(stored_ref, filename)
        if os.path.exists(path):
            return path
        shard = os.path.join(self.root, stored_ref[:2])
        if os.path.isdir(shard):
            for name in os.listdir(shard):
                if name.startswith(stored_ref) and ".tmp-" not in name:
                    return os.path.join(shard, name)
        return None

    def _quarantine(self, path: str, stored_ref: str) -> None:
        """Moves a corrupt file aside for forensics; never raises."""
        try:
            qdir = os.path.join(self.root or "", "quarantine")
            os.makedirs(qdir, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            os.replace(path, os.path.join(qdir, f"{stored_ref}.{stamp}.bad"))
        except OSError:
            try:
                os.remove(path)
            except OSError:
                pass

    def put(self, data: bytes, filename: str) -> Dict[str, object]:
        """Stores bytes; returns {sha256, size_bytes, mime, stored_ref}.

        With a root directory the write is atomic (temp + fsync + replace)
        and verified by re-hashing the file on disk. Raises
        ExhibitStoreError when the bytes cannot be durably stored — the
        caller must treat the exhibit as NOT collected in that case.
        """
        sha256 = _sha256(data)
        if self.root:
            path = self._path_for(sha256, filename)
            if not os.path.exists(path):
                shard = os.path.dirname(path)
                tmp_path = os.path.join(shard, f"{sha256}.tmp-{uuid.uuid4().hex[:12]}")
                try:
                    os.makedirs(shard, exist_ok=True)
                    with open(tmp_path, "wb") as f:
                        f.write(data)
                        f.flush()
                        os.fsync(f.fileno())
                    os.replace(tmp_path, path)
                except OSError as exc:
                    try:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                    except OSError:
                        pass
                    raise ExhibitStoreError(
                        f"Could not durably store exhibit '{filename}' ({len(data)} bytes): {exc}"
                    ) from exc
                # Verify what actually landed on disk before claiming success.
                try:
                    with open(path, "rb") as f:
                        on_disk = f.read()
                except OSError as exc:
                    raise ExhibitStoreError(f"Could not verify stored exhibit '{filename}': {exc}") from exc
                if _sha256(on_disk) != sha256:
                    self._quarantine(path, sha256)
                    raise ExhibitStoreError(
                        f"Stored exhibit '{filename}' failed its integrity check and was quarantined."
                    )
        self._memory[sha256] = data
        return {
            "sha256": sha256,
            "size_bytes": len(data),
            "mime": mime_for(filename),
            "stored_ref": sha256,
        }

    def get(self, stored_ref: Optional[str], filename: str = "") -> Optional[bytes]:
        """Returns retained bytes, or None when unavailable/corrupt.

        Bytes are hash-verified against stored_ref on every read. Corrupt
        files are quarantined and reported as not retained.
        """
        if not stored_ref:
            return None
        cached = self._memory.get(stored_ref)
        if cached is not None:
            if _sha256(cached) == stored_ref:
                return cached
            del self._memory[stored_ref]  # memory copy corrupt; fall through to disk
        path = self._find_on_disk(stored_ref, filename)
        if path is None:
            return None
        try:
            with open(path, "rb") as f:
                data = f.read()
        except OSError:
            return None
        if _sha256(data) != stored_ref:
            self._quarantine(path, stored_ref)
            return None
        self._memory[stored_ref] = data
        return data

    def has(self, stored_ref: Optional[str], filename: str = "") -> bool:
        return self.get(stored_ref, filename) is not None

    def verify_all(self, limit: int = 1000) -> Dict[str, object]:
        """Hashes stored files and reports integrity (bounded sweep).

        Returns {checked, ok, corrupt: [sha256...], root}. Corrupt files
        are quarantined. Memory-only stores report their cache only.
        """
        corrupt: List[str] = []
        checked = 0
        if not self.root:
            for ref, data in list(self._memory.items())[:limit]:
                checked += 1
                if _sha256(data) != ref:
                    corrupt.append(ref)
                    del self._memory[ref]
            return {"checked": checked, "ok": checked - len(corrupt), "corrupt": corrupt, "root": None}
        for shard in sorted(os.listdir(self.root)):
            shard_path = os.path.join(self.root, shard)
            if not os.path.isdir(shard_path) or shard == "quarantine" or len(shard) != 2:
                continue
            for name in sorted(os.listdir(shard_path)):
                if checked >= limit:
                    break
                if ".tmp-" in name:
                    continue  # orphaned temp from an interrupted write; not an exhibit
                ref = name.split(".")[0]
                if len(ref) != 64:
                    continue
                checked += 1
                path = os.path.join(shard_path, name)
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                except OSError:
                    corrupt.append(ref)
                    continue
                if _sha256(data) != ref:
                    corrupt.append(ref)
                    self._quarantine(path, ref)
                    self._memory.pop(ref, None)
        return {"checked": checked, "ok": checked - len(corrupt), "corrupt": corrupt, "root": self.root}
