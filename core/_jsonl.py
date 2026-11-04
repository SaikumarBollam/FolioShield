"""
Shared JSONL append/read helpers (Phase 2 P1).

Used by the submission/escalation/legal registries and the audit logger
so every append-only trail gets the same guarantees:

- append_jsonl: single-line write + flush + fsync (a crash can lose at
  most the in-flight line, never tear previously written lines).
- read_jsonl: returns (records, corrupt_line_numbers). Corrupt lines —
  e.g. a torn final line from a crash — are REPORTED, never silently
  dropped, so callers can surface data-quality warnings.
"""

import json
import os
import threading
from typing import Any, Dict, List, Tuple

# Per-path locks serialize appends within this process so concurrent
# writers can never interleave partial lines. Cross-process writers are
# protected by the single write+fsync of one complete line (POSIX append
# semantics; on Windows the line write is a single buffered flush).
_LOCKS: Dict[str, threading.Lock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(path: str) -> threading.Lock:
    key = os.path.abspath(path)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _LOCKS[key] = lock
        return lock


def append_jsonl(path: str, entry: Dict[str, Any]) -> None:
    """Appends one JSON object as a single fsynced line. Raises OSError."""
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    line = json.dumps(entry, default=str) + "\n"
    with _lock_for(path):
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def read_jsonl(path: str) -> Tuple[List[Dict[str, Any]], List[int]]:
    """Reads a JSONL file. Returns (records, corrupt_line_numbers)."""
    records: List[Dict[str, Any]] = []
    corrupt: List[int] = []
    if not os.path.exists(path):
        return records, corrupt
    with open(path, "r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                corrupt.append(line_no)
                continue
            if isinstance(parsed, dict):
                records.append(parsed)
            else:
                corrupt.append(line_no)
    return records, corrupt
