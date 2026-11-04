"""
Submission Bundle Builder & Registry for FolioShield (Phase 6).

build_submission_bundle() produces the single deliverable staff upload to
the acquirer portal:

    <Case>_Submission.zip
      00_packet.pdf                 the approved 3-page packet
      Exhibit_A_<doctype>_<file>    each satisfied exhibit's retained bytes
      manifest.json                 custody manifest + exhibit map + hashes
      SUBMISSION_INSTRUCTIONS.txt   portal-specific steps

validate_bundle() runs the pre-submission checks (approval current, every
cited exhibit actually retained, file types/sizes vs the portal profile,
no unresolved [MISSING] markers, duplicate-submission guard).

SubmissionRegistry persists SubmissionRecord/OutcomeRecord as JSONL per
case directory and computes the issuer decision window (portal profile,
default 30–45 days) and overdue flags.
"""

import io
import json
import os
import re
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .audit_logger import AuditLogger
from ._jsonl import append_jsonl, read_jsonl
from .models import OutcomeRecord, SubmissionRecord
from .portals import get_portal_profile

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(name: str) -> str:
    return _SAFE.sub("_", name or "file")[:80]


def validate_bundle(
    notice: Dict[str, Any],
    recon: Dict[str, Any],
    draft_text: str,
    packet_bytes: bytes,
    exhibit_files: Dict[str, bytes],
    portal_id: str = "generic",
    approval: Optional[Dict[str, Any]] = None,
    current_fingerprint: Optional[str] = None,
    prior_submissions: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Pre-submission validation. Returns {ok, checks: [{rule, ok, detail}]}."""
    profile = get_portal_profile(portal_id)
    checks: List[Dict[str, Any]] = []

    def check(rule: str, ok: bool, detail: str) -> None:
        checks.append({"rule": rule, "ok": bool(ok), "detail": detail})

    check("packet_present", bool(packet_bytes), "3-page packet compiled" if packet_bytes else "No packet bytes — compile the packet first")
    if approval is not None:
        current = bool(approval.get("fingerprint") and current_fingerprint and approval["fingerprint"] == current_fingerprint)
        check("approval_current", current, "Approval fingerprint matches the current case" if current else "Approval is stale or missing — re-approve in Tab 3")
    unresolved = (draft_text or "").count("[MISSING")
    check("no_unresolved_missing", unresolved == 0, "No unresolved [MISSING] markers" if unresolved == 0 else f"Draft still contains {unresolved} [MISSING] marker(s)")

    exhibits = recon.get("exhibits") or []
    missing_files = [e["letter"] for e in exhibits if e.get("file_backed") and e.get("letter") not in exhibit_files]
    check("exhibits_retained", not missing_files,
          "All cited exhibits retained" if not missing_files else f"Exhibit(s) {', '.join(missing_files)} cited as attached but their file bytes could not be retrieved from the exhibit store — re-upload them in Tab 2 (check the exhibit-store directory is writable)")

    readiness = recon.get("evidence_readiness") or {}
    check("dispositive_collected", bool(readiness.get("submittable", True)),
          "All case-deciding evidence collected" if readiness.get("submittable", True)
          else f"Missing dispositive evidence: {'; '.join(readiness.get('missing_dispositive') or [])}")

    total_mb = (len(packet_bytes or b"") + sum(len(b) for b in exhibit_files.values())) / 1_048_576
    check("bundle_size", total_mb <= float(profile["max_bundle_mb"]),
          f"Bundle {total_mb:.2f} MB within {profile['name']} limit {profile['max_bundle_mb']} MB"
          if total_mb <= float(profile["max_bundle_mb"]) else f"Bundle {total_mb:.2f} MB exceeds {profile['name']} limit {profile['max_bundle_mb']} MB")

    bad_types = []
    for letter, data in exhibit_files.items():
        pass  # types checked by filename below
    exhibits_by_letter = {e.get("letter"): e for e in exhibits}
    for letter in exhibit_files:
        item = exhibits_by_letter.get(letter) or {}
        ext = os.path.splitext(item.get("filename") or "")[1].lower().lstrip(".")
        if ext and ext not in profile["accepted_types"]:
            bad_types.append(f"Exhibit {letter} ({ext})")
    check("file_types", not bad_types,
          "All exhibit file types accepted by the portal" if not bad_types
          else f"Portal does not accept: {', '.join(bad_types)} — convert to PDF/JPG before submitting")

    for field_name in profile.get("requires", []):
        value = notice.get("case_id") if field_name == "case_id" else notice.get("arn")
        check(f"has_{field_name}", bool(value), f"{field_name} present for portal matching" if value else f"{field_name} missing — the portal matches on it")

    dupes = [s for s in (prior_submissions or []) if s.get("status") in ("submitted", "acknowledged", "under_review")]
    check("not_already_submitted", not dupes,
          "No prior active submission for this case" if not dupes
          else f"Case already submitted ({dupes[0].get('submitted_at')}, ref {dupes[0].get('confirmation_reference') or 'n/a'}) — submitting again may duplicate the response")

    return {"ok": all(c["ok"] for c in checks), "checks": checks, "profile": profile}


def build_submission_bundle(
    notice: Dict[str, Any],
    folio: Dict[str, Any],
    recon: Dict[str, Any],
    packet_bytes: bytes,
    exhibit_files: Dict[str, bytes],
    manifest: Dict[str, Any],
    portal_id: str = "generic",
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Builds the submission ZIP. exhibit_files maps exhibit letter -> bytes.
    Returns (zip_bytes, bundle_info) where bundle_info carries hashes and
    the exhibit map for the submission record.
    """
    profile = get_portal_profile(portal_id)
    case_id = _safe(str(notice.get("case_id") or "case"))
    exhibits = recon.get("exhibits") or []
    exhibits_by_letter = {e.get("letter"): e for e in exhibits}

    buffer = io.BytesIO()
    exhibit_map: List[Dict[str, Any]] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("00_packet.pdf", packet_bytes)
        for letter in sorted(exhibit_files.keys()):
            item = exhibits_by_letter.get(letter) or {}
            doc_type = _safe(str(item.get("doc_type") or "exhibit"))
            filename = _safe(str(item.get("filename") or f"exhibit_{letter}"))
            arcname = f"Exhibit_{letter}_{doc_type}_{filename}"
            zf.writestr(arcname, exhibit_files[letter])
            exhibit_map.append({
                "letter": letter, "arcname": arcname, "label": item.get("label"),
                "doc_type": item.get("doc_type"), "filename": item.get("filename"),
                "sha256": item.get("sha256"),
                "bytes_sha256": AuditLogger.calculate_sha256(exhibit_files[letter]),
            })
        bundle_manifest = {
            **manifest,
            "portal": {"id": profile["id"], "name": profile["name"]},
            "case_id": notice.get("case_id"), "arn": notice.get("arn"),
            "exhibit_map": exhibit_map,
            "packet_sha256": AuditLogger.calculate_sha256(packet_bytes),
            "built_at": datetime.now(timezone.utc).isoformat(),
        }
        zf.writestr("manifest.json", json.dumps(bundle_manifest, indent=2, default=str))
        instructions = (
            f"FOLIOSHIELD SUBMISSION INSTRUCTIONS\n"
            f"Case: {notice.get('case_id')} | ARN: {notice.get('arn')} | Portal: {profile['name']}\n"
            f"Portal: {profile['portal_hint']}\n\n{profile['instructions']}\n\n"
            f"Files in this bundle:\n- 00_packet.pdf (approved 3-page dispute packet)\n"
            + "".join(f"- {m['arcname']} (Exhibit {m['letter']}: {m['label']})\n" for m in exhibit_map)
            + "\nFolioShield prepared this bundle; the portal upload itself is performed by hotel staff. "
              "Record the portal confirmation/reference back in FolioShield after submitting."
        )
        zf.writestr("SUBMISSION_INSTRUCTIONS.txt", instructions)

    zip_bytes = buffer.getvalue()
    info = {
        "bundle_sha256": AuditLogger.calculate_sha256(zip_bytes),
        "packet_sha256": AuditLogger.calculate_sha256(packet_bytes),
        "size_bytes": len(zip_bytes),
        "exhibit_map": exhibit_map,
        "filename": f"{case_id}_Submission.zip",
        "profile": profile,
    }
    return zip_bytes, info


class SubmissionRegistry:
    """JSONL persistence for submission + outcome records (per case dir)."""

    def __init__(self, root: str = "data/submissions"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, case_id: str, tenant_id: Optional[str] = None) -> str:
        safe_case = _safe(case_id or 'unknown')
        if tenant_id:
            tdir = os.path.join(self.root, _safe(tenant_id))
            os.makedirs(tdir, exist_ok=True)
            return os.path.join(tdir, f"{safe_case}.jsonl")
        return os.path.join(self.root, f"{safe_case}.jsonl")

    def _append(self, case_id: str, kind: str, record: Dict[str, Any], tenant_id: Optional[str] = None) -> None:
        entry = {"kind": kind, "recorded_at": datetime.now(timezone.utc).isoformat(), "record": record}
        tid = tenant_id or record.get("tenant_id")
        append_jsonl(self._path(case_id, tid), entry)

    def load(self, case_id: str, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Returns {submissions, outcomes, corrupt_lines}.

        corrupt_lines lists 1-based line numbers that could not be parsed
        (e.g. a torn final line after a crash) — reported, never silently
        dropped (Phase 2).
        """
        out: Dict[str, Any] = {"submissions": [], "outcomes": [], "corrupt_lines": []}
        path = self._path(case_id, tenant_id)
        if not os.path.exists(path) and tenant_id:
            fallback = self._path(case_id, None)
            if os.path.exists(fallback):
                path = fallback
        entries, corrupt = read_jsonl(path)
        for entry in entries:
            key = "submissions" if entry.get("kind") == "submission" else "outcomes"
            out[key].append(entry.get("record") or {})
        out["corrupt_lines"] = corrupt
        return out

    def register_submission(self, record: SubmissionRecord) -> SubmissionRecord:
        if not record.expected_decision_by and record.submitted_at:
            profile = get_portal_profile(record.portal_id)
            lo, hi = profile["decision_window_days"]
            try:
                submitted = datetime.fromisoformat(record.submitted_at).date()
            except ValueError:
                submitted = date.today()
            record.expected_decision_by = (submitted + timedelta(days=hi)).isoformat()
            record.notes = ((record.notes or "") + f" Issuer decision typically in {lo}–{hi} days.").strip()
        self._append(record.case_id or "unknown", "submission", record.to_dict())
        return record

    def record_outcome(self, record: OutcomeRecord) -> OutcomeRecord:
        self._append(record.case_id or "unknown", "outcome", record.to_dict())
        return record

    def decision_status(self, case_id: str, today: Optional[date] = None, tenant_id: Optional[str] = None) -> Dict[str, Any]:
        """Latest submission/outcome state + overdue-decision flag."""
        today = today or date.today()
        data = self.load(case_id, tenant_id=tenant_id)
        submissions = data["submissions"]
        outcomes = data["outcomes"]
        latest_sub = submissions[-1] if submissions else None
        latest_out = outcomes[-1] if outcomes else None
        overdue = False
        days_left: Optional[int] = None
        if latest_sub and not latest_out:
            expected = latest_sub.get("expected_decision_by")
            if expected:
                try:
                    exp_date = datetime.fromisoformat(expected).date()
                    days_left = (exp_date - today).days
                    overdue = days_left < 0
                except ValueError:
                    pass
        return {
            "submissions": submissions, "outcomes": outcomes,
            "corrupt_lines": data.get("corrupt_lines") or [],
            "latest_submission": latest_sub, "latest_outcome": latest_out,
            "decision_overdue": overdue, "decision_days_left": days_left,
            "status": (latest_out or {}).get("decision") if latest_out else (latest_sub or {}).get("status", "not_submitted"),
        }
