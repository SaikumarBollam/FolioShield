"""
Rebuttal Draft Validation for FolioShield (Phase 4).

Post-generation guardrails applied to ANY draft (Llama output or staff-edited
text) before it can be approved:

  * Structure: the five bank-expected sections must be present
    (Executive Summary, Factual Rebuttal, Chronology, Exhibit Index, Closing).
  * Exhibit discipline: every "Exhibit X" cited must exist in the
    reconciler's exhibit index; satisfied exhibits should be cited.
  * Evidence discipline: the draft must not assert evidence the validators
    marked missing/adverse (checked against known adverse labels and the
    [MISSING] convention), and unresolved [MISSING] markers are counted.
  * Identity: case ID / ARN / disputed amount should appear.

Returns {"valid": bool, "issues": [...], "missing_markers": int,
         "sections_found": [...]}. Validation never rewrites text — callers
decide (LLM path falls back to the deterministic template; the UI gate
blocks approval on unresolved markers).
"""

import re
from typing import Any, Dict, List

SECTION_PATTERNS = {
    "executive_summary": re.compile(r"executive summary", re.I),
    "factual_rebuttal": re.compile(r"factual rebuttal|rebuttal", re.I),
    "chronology": re.compile(r"chronology|timeline", re.I),
    "exhibit_index": re.compile(r"exhibit", re.I),
    "closing": re.compile(r"closing|request for reversal|respectfully", re.I),
}

# Phrases that assert an exhibit exists; used to catch claims about
# evidence the validators marked adverse/missing.
_ASSERTION_PATTERNS = [
    (re.compile(r"avs.{0,30}(match|matched|verified|passed)", re.I), "avs_cvv"),
    (re.compile(r"3-?d secure.{0,30}(authenticated|verified|passed)", re.I), "three_ds"),
    (re.compile(r"no unresolved complaints|no complaints (?:were|on file)", re.I), "service_log"),
    (re.compile(r"keycard.{0,40}(show|shows|confirm|demonstrat)", re.I), "keycard"),
    (re.compile(r"signed (?:the )?registration", re.I), "registration"),
]


def validate_rebuttal(text: str, recon: Dict[str, Any], notice: Dict[str, Any] = None) -> Dict[str, Any]:
    notice = notice or {}
    issues: List[str] = []
    body = text or ""

    sections_found = [name for name, pat in SECTION_PATTERNS.items() if pat.search(body)]
    for name in SECTION_PATTERNS:
        if name not in sections_found:
            issues.append(f"Missing required section: {name.replace('_', ' ')}")

    # Exhibit letters cited vs assigned
    assigned = {e.get("letter") for e in (recon.get("exhibits") or []) if e.get("letter")}
    cited = set(re.findall(r"Exhibit\s+([A-Z])\b", body))
    for letter in sorted(cited - assigned):
        issues.append(f"Cites Exhibit {letter}, which is not in the validated exhibit index")
    uncited = assigned - cited
    if assigned and len(uncited) == len(assigned):
        issues.append("No exhibits are cited in the letter body")

    # Adverse / missing evidence must not be asserted as support.
    # An assertion is excused when the surrounding text explicitly disclaims
    # reliance ("not relied upon", "does not rely", "addressed directly").
    checklist = recon.get("evidence_checklist") or []
    adverse_specs = {e.get("spec_id") for e in checklist if e.get("validation") == "adverse"}
    missing_specs = {e.get("spec_id") for e in checklist if e.get("validation") in ("missing", "weak")}

    def _disclaimed(match_start: int) -> bool:
        window = body[max(0, match_start - 250):match_start + 250].lower()
        return any(phrase in window for phrase in ("not relied upon", "does not rely", "not rely on", "addressed directly", "matters addressed"))

    for pattern, spec_id in _ASSERTION_PATTERNS:
        m = pattern.search(body)
        if m:
            if spec_id in adverse_specs and not _disclaimed(m.start()):
                issues.append(f"Asserts '{spec_id}' as support, but validators marked it ADVERSE")
            elif spec_id in missing_specs and "[MISSING" not in body[max(0, m.start() - 200):m.start()] and not _disclaimed(m.start()):
                issues.append(f"Asserts '{spec_id}' without a [MISSING] qualifier, but it is not validated as satisfied")

    missing_markers = body.count("[MISSING")

    case_id = str(notice.get("case_id") or "")
    if case_id and case_id not in body:
        issues.append("Case ID does not appear in the draft")
    arn = str(notice.get("arn") or "")
    if arn and arn not in body:
        issues.append("ARN does not appear in the draft")

    return {
        "valid": not issues,
        "issues": issues,
        "missing_markers": missing_markers,
        "sections_found": sections_found,
    }
