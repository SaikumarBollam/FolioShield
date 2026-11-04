"""
Escalation Engine for FolioShield (Phases 7–9: If You Lose).

Stage machine for the post-loss lifecycle:

    chargeback → submitted → under_review → won ───────────────→ closed
                                          → lost → second_chargeback → closed
                                                 → pre_arbitration → arbitration → closed
                                                 → accepted_loss → closed

Responsibilities:
  * Legal stage transitions + per-stage deadlines (network-configurable).
  * Round snapshots: at each submission the case state (exhibits, verdicts,
    readiness) is frozen so "what the issuer saw" is reconstructable.
  * Case reopening: a second-chargeback / pre-arb notice (or matching ARN /
    prior_case_id) finds the prior case and produces a round diff.
  * Loss analysis: structured loss reasons + automatic gap report from the
    round-1 Phase 3 verdicts (missing/weak/adverse, criticality-ranked).
  * Arbitration decision support: per-network fee schedule and an expected-
    value heuristic. The readiness score is used as a labelled proxy for
    evidence strength — it is NOT a win probability and is presented as such.

Stage rules differ by network and change over time; deadlines/fees here are
configurable defaults labelled "verify with your acquirer".
"""

import json
import os
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ._jsonl import append_jsonl, read_jsonl

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")

STAGES = ("chargeback", "submitted", "under_review", "won", "lost",
          "second_chargeback", "pre_arbitration", "arbitration",
          "accepted_loss", "closed")

LEGAL_TRANSITIONS: Dict[str, List[str]] = {
    "chargeback": ["submitted", "accepted_loss", "closed"],
    "submitted": ["under_review", "won", "lost", "closed"],
    "under_review": ["won", "lost", "closed"],
    "won": ["closed"],
    "lost": ["second_chargeback", "pre_arbitration", "arbitration", "accepted_loss", "closed"],
    "second_chargeback": ["pre_arbitration", "arbitration", "accepted_loss", "closed"],
    "pre_arbitration": ["won", "lost", "arbitration", "accepted_loss", "closed"],
    "arbitration": ["won", "lost", "closed"],
    "accepted_loss": ["closed"],
    "closed": [],
}

# Days the merchant typically has to act at each stage (defaults; verify).
STAGE_DEADLINE_DAYS: Dict[str, Dict[str, int]] = {
    "Visa": {"second_chargeback": 30, "pre_arbitration": 30, "arbitration": 30},
    "Mastercard": {"second_chargeback": 45, "pre_arbitration": 45, "arbitration": 30},
    "American Express": {"second_chargeback": 30, "pre_arbitration": 30, "arbitration": 30},
    "Discover": {"second_chargeback": 30, "pre_arbitration": 30, "arbitration": 30},
}

# Arbitration filing fees (USD, defaults; loser typically pays both sides'
# fees — verify current network schedules with your acquirer).
ARBITRATION_FEES: Dict[str, Dict[str, float]] = {
    "Visa": {"filing_fee": 250.0, "review_fee": 250.0},
    "Mastercard": {"filing_fee": 300.0, "review_fee": 300.0},
    "American Express": {"filing_fee": 250.0, "review_fee": 250.0},
    "Discover": {"filing_fee": 250.0, "review_fee": 250.0},
}

LOSS_REASONS = {
    "insufficient_occupancy": "Insufficient evidence of occupancy / physical presence",
    "policy_not_proven": "Cancellation/no-show policy not proven as disclosed & accepted",
    "authorization_gap": "Authorization evidence insufficient (AVS/3DS/EMV/auth record)",
    "amount_unproven": "Amount not proven (folio footing / per-item slips missing)",
    "identity_gap": "Cardholder identity / third-party authorization not established",
    "late_response": "Response late or incomplete at first representment",
    "new_evidence_barred": "New evidence not admissible at this stage",
    "other": "Other (see issuer text)",
}

# Whether NEW evidence is generally admissible per stage (guidance only).
NEW_EVIDENCE_ADMISSIBLE = {
    "second_chargeback": False,   # Visa generally bars new evidence here
    "pre_arbitration": True,      # the negotiation round — new evidence allowed
    "arbitration": True,          # full record considered, at a price
}


def _safe(name: str) -> str:
    return _SAFE.sub("_", name or "unknown")[:80]


def can_transition(current: str, nxt: str) -> bool:
    return nxt in LEGAL_TRANSITIONS.get(current, [])


def stage_deadline(network: Optional[str], stage: str, stage_entered: date) -> Optional[str]:
    days = STAGE_DEADLINE_DAYS.get(network or "", {}).get(stage)
    if days is None:
        days = STAGE_DEADLINE_DAYS["Visa"].get(stage)
    if days is None:
        return None
    return (stage_entered + timedelta(days=days)).isoformat()


def snapshot_round(round_no: int, recon: Dict[str, Any], submission: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Freezes what the issuer saw in a round: exhibits + verdicts + readiness."""
    return {
        "round": round_no,
        "snapshot_at": datetime.now(timezone.utc).isoformat(),
        "exhibits": [
            {"letter": e.get("letter"), "spec_id": e.get("spec_id"), "label": e.get("label"),
             "doc_type": e.get("doc_type"), "filename": e.get("filename"), "sha256": e.get("sha256")}
            for e in (recon.get("exhibits") or [])
        ],
        "verdicts": [
            {"spec_id": c.get("spec_id"), "item": c.get("item"), "criticality": c.get("criticality"),
             "validation": c.get("validation"), "validation_detail": c.get("validation_detail")}
            for c in (recon.get("evidence_checklist") or [])
        ],
        "readiness": recon.get("evidence_readiness") or {},
        "completeness_score": recon.get("completeness_score"),
        "proofs_failed": [p.get("proof") for p in (recon.get("proofs") or []) if p.get("status") == "failed"],
        "submission": submission,
    }


def gap_analysis(round_snapshot: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    The pre-arb collection checklist: everything round 1 failed to prove,
    ranked dispositive → required → supporting, adverse first within tier.
    """
    rank = {"dispositive": 0, "required": 1, "supporting": 2}
    gaps = []
    for v in (round_snapshot or {}).get("verdicts", []):
        if v.get("validation") in ("missing", "weak", "adverse"):
            gaps.append({
                "spec_id": v.get("spec_id"), "item": v.get("item"),
                "criticality": v.get("criticality"), "validation": v.get("validation"),
                "detail": v.get("validation_detail"),
                "action": ("Address head-on — do not cite; add counter-evidence or concede this element"
                           if v.get("validation") == "adverse" else
                           "Collect and validate this exhibit for the supplemental round"),
            })
    gaps.sort(key=lambda g: (rank.get(g.get("criticality"), 3), 0 if g["validation"] == "adverse" else 1))
    return gaps


def round_diff(prior_snapshot: Dict[str, Any], current_recon: Dict[str, Any]) -> Dict[str, Any]:
    """What changed since the prior round: new exhibits, resolved gaps, still-open gaps."""
    prior_letters = {e.get("spec_id") for e in (prior_snapshot or {}).get("exhibits", [])}
    current_exhibits = current_recon.get("exhibits") or []
    new_exhibits = [e for e in current_exhibits if e.get("spec_id") not in prior_letters]
    prior_gaps = gap_analysis(prior_snapshot)
    current_verdicts = {c.get("spec_id"): c.get("validation") for c in current_recon.get("evidence_checklist") or []}
    resolved, still_open = [], []
    for gap in prior_gaps:
        if current_verdicts.get(gap["spec_id"]) == "satisfied":
            resolved.append(gap)
        else:
            still_open.append(gap)
    return {
        "prior_round": (prior_snapshot or {}).get("round"),
        "new_exhibits": new_exhibits,
        "resolved_gaps": resolved,
        "still_open_gaps": still_open,
        "prior_readiness": (prior_snapshot or {}).get("readiness"),
        "current_readiness": current_recon.get("evidence_readiness"),
    }


def next_exhibit_letter(existing_letters: List[str]) -> str:
    """Continues exhibit lettering across rounds (…G → H)."""
    used = {str(l).strip().upper() for l in existing_letters if l}
    idx = len([l for l in used if len(l) == 1 and "A" <= l <= "Z"])
    while idx < 26 and chr(65 + idx) in used:
        idx += 1
    return chr(65 + idx) if idx < 26 else f"E{len(used) + 1}"


def arbitration_assessment(network: Optional[str], disputed_amount: float,
                           readiness_score: Optional[int],
                           fees: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """
    Expected-value decision support for arbitration.

    readiness_score (0–100, Phase 3) is used ONLY as a labelled proxy for
    evidence strength — it is not a measured win probability. The output
    says so, and shows break-even strength so staff can judge.
    """
    schedule = dict(ARBITRATION_FEES.get(network or "", ARBITRATION_FEES["Visa"]))
    if fees:
        schedule.update(fees)
    total_fees = float(schedule.get("filing_fee", 0)) + float(schedule.get("review_fee", 0))
    amount = float(disputed_amount or 0)
    strength = readiness_score if readiness_score is not None else 50
    p = max(0.05, min(0.95, strength / 100.0))
    # Win: recover amount, pay no fees (loser pays). Lose: lose amount already
    # debited + pay fees. EV of arbitrating vs accepting the loss now (0):
    ev = p * amount - (1 - p) * total_fees
    breakeven = total_fees / (amount + total_fees) * 100 if (amount + total_fees) > 0 else 100.0
    if amount <= 0:
        recommendation, rationale = "accept_loss", "No amount at stake recorded — arbitration cannot be evaluated."
    elif ev > 0 and strength >= 60:
        recommendation = "arbitrate"
        rationale = (f"Evidence readiness {strength}% with ${amount:,.2f} at stake: expected value ${ev:,.2f} is positive "
                     f"and readiness clears the 60% strength floor.")
    elif ev > 0:
        recommendation = "consider"
        rationale = (f"Expected value is positive (${ev:,.2f}) but evidence readiness is only {strength}% — "
                     "strengthen the record (pre-arb new evidence) before risking fees.")
    else:
        recommendation = "accept_loss"
        rationale = (f"Expected value ${ev:,.2f} is negative at {strength}% readiness: break-even needs "
                     f"{breakeven:.0f}% win strength against ${total_fees:,.2f} in loser-pays fees.")
    return {
        "network": network, "disputed_amount": amount,
        "filing_fee": float(schedule.get("filing_fee", 0)), "review_fee": float(schedule.get("review_fee", 0)),
        "total_fees_at_risk": total_fees,
        "evidence_readiness": strength,
        "ev_estimate": round(ev, 2),
        "breakeven_strength_pct": round(breakeven, 1),
        "recommendation": recommendation,
        "rationale": rationale,
        "disclaimer": ("Readiness is FolioShield's evidence-completeness score, used only as a strength proxy — "
                       "not a measured win probability. Fees are configurable defaults; verify the current "
                       "network fee schedule and deadlines with your acquirer before filing."),
    }


class EscalationRegistry:
    """Stage history + round snapshots, JSONL per case (extends Phase 6 registry dir)."""

    def __init__(self, root: str = "data/submissions"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, case_id: str) -> str:
        return os.path.join(self.root, f"{_safe(case_id or 'unknown')}.jsonl")

    def _append(self, case_id: str, kind: str, record: Dict[str, Any]) -> None:
        entry = {"kind": kind, "recorded_at": datetime.now(timezone.utc).isoformat(), "record": record}
        append_jsonl(self._path(case_id), entry)

    def load(self, case_id: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {"stage_history": [], "rounds": [], "losses": [], "arbitration": [], "corrupt_lines": []}
        kind_map = {"stage": "stage_history", "round_snapshot": "rounds", "loss": "losses", "arbitration": "arbitration"}
        entries, corrupt = read_jsonl(self._path(case_id))
        for entry in entries:
            key = kind_map.get(entry.get("kind"))
            if key:
                out[key].append(entry.get("record") or {})
        out["corrupt_lines"] = corrupt
        return out

    def transition(self, case_id: str, to_stage: str, network: Optional[str] = None,
                   actor: str = "", notes: str = "", entered_on: Optional[date] = None) -> Dict[str, Any]:
        data = self.load(case_id)
        current = data["stage_history"][-1]["stage"] if data["stage_history"] else "chargeback"
        if not can_transition(current, to_stage):
            raise ValueError(f"Illegal stage transition {current} → {to_stage}. Legal next stages: {LEGAL_TRANSITIONS.get(current, [])}")
        entered = entered_on or date.today()
        record = {
            "case_id": case_id, "stage": to_stage, "from_stage": current,
            "entered_at": entered.isoformat(),
            "deadline": stage_deadline(network, to_stage, entered),
            "actor": actor, "notes": notes,
            "network": network,
        }
        self._append(case_id, "stage", record)
        return record

    def save_round_snapshot(self, case_id: str, snapshot: Dict[str, Any]) -> None:
        self._append(case_id, "round_snapshot", snapshot)

    def record_loss(self, case_id: str, reason_code_key: str, issuer_text: str = "",
                    decided_at: Optional[str] = None, actor: str = "") -> Dict[str, Any]:
        record = {
            "case_id": case_id, "loss_reason": reason_code_key,
            "loss_reason_label": LOSS_REASONS.get(reason_code_key, reason_code_key),
            "issuer_text": issuer_text, "decided_at": decided_at or datetime.now(timezone.utc).isoformat(),
            "actor": actor,
        }
        self._append(case_id, "loss", record)
        return record

    def record_arbitration(self, case_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        self._append(case_id, "arbitration", record)
        return record

    def status(self, case_id: str, today: Optional[date] = None) -> Dict[str, Any]:
        today = today or date.today()
        data = self.load(case_id)
        current = data["stage_history"][-1] if data["stage_history"] else None
        deadline = (current or {}).get("deadline")
        days_left: Optional[int] = None
        overdue = False
        if deadline:
            try:
                days_left = (datetime.fromisoformat(deadline).date() - today).days
                overdue = days_left < 0 and (current or {}).get("stage") not in ("won", "closed", "accepted_loss")
            except ValueError:
                pass
        return {
            "case_id": case_id,
            "stage": (current or {}).get("stage", "chargeback"),
            "stage_entered_at": (current or {}).get("entered_at"),
            "stage_deadline": deadline,
            "stage_days_left": days_left,
            "stage_overdue": overdue,
            "stage_history": data["stage_history"],
            "rounds": data["rounds"],
            "losses": data["losses"],
            "arbitration": data["arbitration"],
            "legal_next_stages": LEGAL_TRANSITIONS.get((current or {}).get("stage", "chargeback"), []),
        }
