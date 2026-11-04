"""
Bulk evidence import from a ZIP archive.

Staff export evidence from several systems (PMS, lock system, gateway,
booking engine). This module lets them drop ONE zip and have each file
routed to its evidence slot. Matching is deterministic and conservative:

  1. An explicit ``manifest.json`` in the archive ({"doc_type": "filename"})
     always wins.
  2. A filename containing the registry key (e.g. ``wifi_usage_log.csv``).
  3. Filename keywords (e.g. ``keycard``, ``3ds``, ``clickwrap``).

Anything unmatched, duplicated, oversized, or of a disallowed type is
reported back — never silently dropped and never guessed into two slots.
Archive safety: entry-count / per-file / total-size caps, no path
traversal (only basenames are used), no nested archives.
"""

import io
import json
import zipfile
from typing import Any, Dict, List, Optional

from .rules import SUPPORTING_DOC_TYPES

ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "csv", "eml", "txt"}
MAX_ENTRIES = 100
DEFAULT_MAX_FILE_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_TOTAL_BYTES = 50 * 1024 * 1024

# Keyword hints per doc type, checked in registry order. Keep specific
# tokens first within each list; matching is substring on the lowercase
# basename without extension.
_KEYWORD_HINTS: Dict[str, List[str]] = {
    "signed_registration_card": ["registration_card", "registration", "check_in_card", "checkin_card"],
    "id_verification_log": ["id_verification", "photo_id", "id_log", "passport"],
    "emv_terminal_receipt": ["emv", "terminal_receipt", "chip_receipt"],
    "avs_cvv_result": ["avs_cvv", "avs", "cvv"],
    "three_ds_authentication": ["3ds", "3_ds", "3d_secure", "three_ds", "threeds"],
    "keycard_lock_audit": ["keycard", "lock_audit", "door_lock", "onity", "saflok"],
    "pos_signed_slips": ["pos_signed", "pos_slip", "signed_slip"],
    "booking_confirmation": ["booking_confirmation", "confirmation_email"],
    "cancellation_policy_acceptance": ["cancellation_policy", "policy_acceptance", "cancellation_terms"],
    "guest_communication_log": ["communication_log", "guest_communication", "comms_log"],
    "guest_service_log": ["service_log", "guest_service"],
    "wifi_usage_log": ["wifi", "network_usage", "wi_fi"],
    "incident_damage_evidence": ["incident", "damage"],
    "refund_credit_receipt": ["refund_credit", "refund_receipt", "credit_receipt"],
    "clickwrap_record": ["clickwrap", "click_wrap"],
    "cctv_footage": ["cctv", "footage", "surveillance"],
    "suspect_id_copy": ["suspect_id", "id_copy"],
    "witness_declaration": ["witness", "declaration"],
    "demand_letter": ["demand_letter", "demand"],
    "police_report": ["police", "ic3"],
}


def match_doc_type(filename: str) -> Optional[str]:
    """Best-effort doc-type match for one filename; None when unsure."""
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1].lower()
    stem = base.rsplit(".", 1)[0] if "." in base else base
    for key in SUPPORTING_DOC_TYPES:
        if key in stem:
            return key
    for key, hints in _KEYWORD_HINTS.items():
        if any(hint in stem for hint in hints):
            return key
    return None


def _extension(filename: str) -> str:
    base = (filename or "").replace("\\", "/").rsplit("/", 1)[-1]
    return base.rsplit(".", 1)[-1].lower() if "." in base else ""


def plan_zip_import(
    zip_bytes: bytes,
    max_file_bytes: int = DEFAULT_MAX_FILE_BYTES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> Dict[str, Any]:
    """
    Inspects a ZIP archive and returns an import plan without storing
    anything: {ok, error, matched: {doc_type: {filename, data, via}},
    unmatched: [...], skipped: [{filename, reason}]}.
    """
    plan: Dict[str, Any] = {"ok": False, "error": None, "matched": {}, "unmatched": [], "skipped": []}
    try:
        archive = zipfile.ZipFile(io.BytesIO(zip_bytes))
    except zipfile.BadZipFile:
        plan["error"] = "That file is not a valid ZIP archive."
        return plan

    infos = [i for i in archive.infolist() if not i.is_dir()]
    if len(infos) > MAX_ENTRIES:
        plan["error"] = f"ZIP contains {len(infos)} files; the limit is {MAX_ENTRIES}. Split the archive and retry."
        return plan

    # Optional explicit manifest: {"wifi_usage_log": "exports/wifi.csv", ...}
    manifest: Dict[str, str] = {}
    for info in infos:
        if info.filename.replace("\\", "/").rsplit("/", 1)[-1].lower() == "manifest.json":
            try:
                parsed = json.loads(archive.read(info).decode("utf-8", errors="replace"))
                if isinstance(parsed, dict):
                    manifest = {str(k): str(v) for k, v in parsed.items() if k in SUPPORTING_DOC_TYPES}
            except (ValueError, UnicodeDecodeError):
                plan["skipped"].append({"filename": info.filename, "reason": "manifest.json is not valid JSON — ignored"})
            break
    manifest_by_basename = {v.replace("\\", "/").rsplit("/", 1)[-1].lower(): k for k, v in manifest.items()}

    total = 0
    # Deterministic processing order (archive order is filesystem-dependent):
    # sorted by entry name, so duplicate-slot resolution is reproducible.
    for info in sorted(infos, key=lambda i: i.filename.lower()):
        name = info.filename
        base = name.replace("\\", "/").rsplit("/", 1)[-1]
        if base.lower() == "manifest.json":
            continue
        if name.startswith("/") or ".." in name.replace("\\", "/").split("/"):
            plan["skipped"].append({"filename": name, "reason": "unsafe path inside archive"})
            continue
        if _extension(base) not in ALLOWED_EXTENSIONS:
            plan["skipped"].append({"filename": name, "reason": f"file type not allowed (use {', '.join(sorted(ALLOWED_EXTENSIONS))})"})
            continue
        if info.file_size > max_file_bytes:
            plan["skipped"].append({"filename": name, "reason": f"exceeds the per-file limit ({max_file_bytes // 1_048_576} MB)"})
            continue
        total += info.file_size
        if total > max_total_bytes:
            plan["error"] = f"ZIP contents exceed the total limit ({max_total_bytes // 1_048_576} MB uncompressed). Split the archive and retry."
            plan["matched"] = {}
            return plan
        # Streamed read with a hard cap: a lying size header (decompression
        # bomb) is stopped at max_file_bytes+1 actual bytes, never fully
        # materialized beyond the limit.
        try:
            chunks: List[bytes] = []
            read_so_far = 0
            with archive.open(info) as stream:
                while True:
                    chunk = stream.read(256 * 1024)
                    if not chunk:
                        break
                    read_so_far += len(chunk)
                    if read_so_far > max_file_bytes:
                        break
                    chunks.append(chunk)
        except (RuntimeError, zipfile.BadZipFile) as exc:
            plan["skipped"].append({"filename": name, "reason": f"could not be extracted ({exc})"})
            continue
        if read_so_far > max_file_bytes:
            plan["skipped"].append({"filename": name, "reason": f"exceeds the per-file limit ({max_file_bytes // 1_048_576} MB) when extracted"})
            continue
        data = b"".join(chunks)
        doc_type = manifest_by_basename.get(base.lower()) or match_doc_type(base)
        if doc_type is None:
            plan["unmatched"].append(base)
            continue
        via = "manifest" if base.lower() in manifest_by_basename else ("key" if doc_type in base.lower() else "keyword")
        if doc_type in plan["matched"]:
            existing = plan["matched"][doc_type]
            rank = {"manifest": 3, "key": 2, "keyword": 1}
            if rank[via] > rank[existing["via"]]:
                # A stronger match (manifest/key) replaces a weaker keyword
                # match; the replaced file is reported, not silently dropped.
                plan["skipped"].append({
                    "filename": existing["filename"],
                    "reason": f"duplicate for slot '{doc_type}' — replaced by '{base}' (stronger {via} match); attach manually if it should be kept",
                })
                plan["matched"][doc_type] = {"filename": base, "data": data, "via": via}
            else:
                plan["skipped"].append({
                    "filename": name,
                    "reason": f"duplicate for slot '{doc_type}' — '{existing['filename']}' was kept; attach this one manually if it should replace it",
                })
            continue
        plan["matched"][doc_type] = {"filename": base, "data": data, "via": via}

    plan["ok"] = True
    return plan
