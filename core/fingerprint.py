"""
Case Fingerprint for FolioShield (Phase 5: Approval & Chain of Custody).

Canonical, versioned fingerprint of everything that goes into a dispute
packet: SHA256 over normalized {notice, folio, evidence, draft, policy,
notes, merchant}. Normalization rules (v2):

  * Volatile fields are excluded: raw_text, verified_at/verified_by churn,
    file paths — re-extracting or re-attesting the same facts must NOT
    invalidate an approval.
  * Numbers are coerced (100 and 100.0 hash identically); None-valued keys
    are dropped; strings are whitespace-collapsed.
  * Evidence is reduced to its probative core per doc type:
    {present, sha256, details} — the file hash is the identity of the file.

Per-component sub-hashes are returned so a stale warning can name WHAT
changed ("folio changed since approval") instead of a bare mismatch.
"""

import hashlib
import json
import re
from typing import Any, Dict

FINGERPRINT_VERSION = "v2"

_VOLATILE_KEYS = {"raw_text", "verified_at", "verified_by", "filename"}


def _normalize(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        out = {}
        for k in sorted(value.keys()):
            if k in _VOLATILE_KEYS:
                continue
            normalized = _normalize(value[k], k)
            if normalized is None:
                continue
            out[k] = normalized
        return out
    if isinstance(value, list):
        return [_normalize(v) for v in value]
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    if isinstance(value, str):
        return re.sub(r"\s+", " ", value).strip()
    return value


def _hash_component(value: Any) -> str:
    payload = json.dumps(_normalize(value), sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def case_fingerprint(notice: Dict[str, Any], folio: Dict[str, Any], evidence: Dict[str, Any],
                     draft: str, policy: str, notes: str = "", merchant: str = "") -> Dict[str, Any]:
    """
    Returns {"version", "fingerprint", "components": {name: hash}}.
    The fingerprint is the SHA-256 of the sorted component hashes + version.
    """
    components = {
        "notice": _hash_component(notice or {}),
        "folio": _hash_component(folio or {}),
        "evidence": _hash_component(evidence or {}),
        "draft": hashlib.sha256((draft or "").encode("utf-8")).hexdigest(),
        "policy": hashlib.sha256((policy or "").encode("utf-8")).hexdigest(),
        "notes": hashlib.sha256((notes or "").encode("utf-8")).hexdigest(),
        "merchant": hashlib.sha256((merchant or "").encode("utf-8")).hexdigest(),
    }
    combined = hashlib.sha256(
        json.dumps({"v": FINGERPRINT_VERSION, "c": components}, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return {"version": FINGERPRINT_VERSION, "fingerprint": combined, "components": components}


def changed_components(before: Dict[str, Any], after: Dict[str, Any]) -> list:
    """Names of components whose hash differs between two fingerprint dicts."""
    b = (before or {}).get("components") or {}
    a = (after or {}).get("components") or {}
    return sorted(k for k in set(b) | set(a) if b.get(k) != a.get(k))
