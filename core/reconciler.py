"""
Transaction Reconciliation & Evidence Completeness Audit for FolioShield.
Cross-references bank dispute notices with hotel folios and computes completeness score.
"""

import re
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

from .rules import SUPPORTING_DOC_TYPES, get_evidence_checklist_for_dispute, lookup_reason_code

AMOUNT_TOLERANCE = 0.01
DEADLINE_WARNING_DAYS = 5

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y")

# Ordered evidence-matching rules: first matching pattern decides which proof satisfies the item.
# Each rule maps a requirement keyword pattern to a "source" resolved in _evidence_present().
_EVIDENCE_RULES: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bfolio\b|billing statement|\bledger\b", re.I), "folio"),
    (re.compile(r"incidental", re.I), "line_items"),
    (re.compile(r"keycard|\bkey\b|door lock|occupancy|physically present|entry log", re.I), "keycard_or_wifi_audit|id_verification_copy"),
    (re.compile(r"\bid\b|identification|photo", re.I), "id_verification_copy"),
    (re.compile(r"cancell?ation|no-show|non-refundable|refund|cutoff|forfeiture|polic(?:y|ies)", re.I), "cancellation_policy_acknowledged"),
    (re.compile(r"sign(?:ed|ature)|registration|check-in", re.I), "signed_registration_card"),
    (re.compile(r"\bavs\b|cvv|\bcid\b|\bchip\b|\bemv\b|3d secure|cryptogram|authori[sz]ation|authentication|address verification|terminal", re.I), "auth"),
    (re.compile(r"e-?mail|confirmation|communication|correspondence", re.I), "booking_confirmation"),
    (re.compile(r"service log|complaint|maintenance", re.I), "guest_service_log"),
]


def parse_date(value: Any) -> Optional[date]:
    """Parses common dispute-notice date formats; returns None if unparseable."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


class Reconciler:
    """
    Performs algorithmic audit, transaction reconciliation, and evidence completeness scoring.
    """

    @staticmethod
    def _evidence_present(source: str, folio: Dict[str, Any], folio_charges: float, docs: Dict[str, bool]) -> bool:
        if source == "folio":
            return folio_charges > 0
        if source == "line_items":
            return any(item.get("type") == "Charge" for item in folio.get("line_items") or [])
        if source == "auth":
            return bool(docs.get("emv_chip_or_avs_auth")) or bool(folio.get("auth_code"))
        return any(bool(docs.get(key)) for key in source.split("|"))

    @classmethod
    def reconcile(
        cls,
        notice: Dict[str, Any],
        folio: Dict[str, Any],
        supporting_docs: Optional[Dict[str, bool]] = None,
        today: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Cross-checks bank dispute notice against guest folio and supporting documentation.
        Supporting documents default to "not provided" — evidence is never assumed.
        """
        docs = {key: False for key in SUPPORTING_DOC_TYPES}
        docs.update(supporting_docs or {})
        today = today or date.today()

        discrepancies: List[Dict[str, str]] = []
        audit_highlights: List[str] = []

        # 1. Amount Reconciliation
        disp_amt = float(notice.get("disputed_amount") or 0.0)
        folio_charges = float(folio.get("total_charges") or 0.0)
        folio_payments = float(folio.get("total_payments") or 0.0)

        is_exact_match = disp_amt > 0 and abs(disp_amt - folio_charges) < AMOUNT_TOLERANCE
        is_partial = 0 < disp_amt < folio_charges and not is_exact_match

        if disp_amt <= 0:
            discrepancies.append({
                "type": "MISSING_AMOUNT",
                "severity": "critical",
                "message": "No disputed amount could be determined from the bank notice. Verify the notice manually.",
            })
        elif is_exact_match:
            audit_highlights.append(f"Disputed amount (${disp_amt:,.2f}) exactly matches total folio charges.")
        elif is_partial:
            discrepancies.append({
                "type": "PARTIAL_DISPUTE",
                "severity": "info",
                "message": (
                    f"Partial chargeback: Disputed amount (${disp_amt:,.2f}) is less than total folio "
                    f"(${folio_charges:,.2f}). Difference: ${folio_charges - disp_amt:,.2f} represents uncontested folio items."
                ),
            })
            audit_highlights.append(f"Partial chargeback identified (${disp_amt:,.2f} of ${folio_charges:,.2f} total).")
        else:
            discrepancies.append({
                "type": "AMOUNT_MISMATCH",
                "severity": "warning",
                "message": (
                    f"Disputed amount (${disp_amt:,.2f}) exceeds total folio charges (${folio_charges:,.2f}). "
                    "Possible additional invoice or multiple reservations."
                ),
            })

        balance = round(folio_charges - folio_payments, 2)
        if folio_charges > 0 and abs(balance) >= AMOUNT_TOLERANCE:
            discrepancies.append({
                "type": "OPEN_BALANCE",
                "severity": "warning",
                "message": f"Folio is not settled: charges ${folio_charges:,.2f} vs payments ${folio_payments:,.2f} (balance ${balance:,.2f}).",
            })

        # 2. Card Last-4 Reconciliation
        notice_last4 = str(notice.get("card_last_4") or "").strip()
        folio_last4 = str(folio.get("card_last_4") or "").strip()

        if notice_last4 and folio_last4:
            if notice_last4 == folio_last4:
                audit_highlights.append(f"Payment card last-4 verified ({notice_last4}) across bank notice and folio.")
            else:
                discrepancies.append({
                    "type": "CARD_MISMATCH",
                    "severity": "critical",
                    "message": f"Card last-4 mismatch: Notice specifies **** {notice_last4}, while Folio shows **** {folio_last4}.",
                })
        else:
            discrepancies.append({
                "type": "CARD_UNVERIFIED",
                "severity": "info",
                "message": "Card last-4 is missing from the notice or folio; card match could not be verified.",
            })

        # 3. Guest Name Reconciliation
        n_name = (notice.get("cardholder_name") or "").strip().lower()
        f_name = (folio.get("guest_name") or "").strip().lower()

        if n_name and f_name:
            if n_name in f_name or f_name in n_name:
                audit_highlights.append(f"Cardholder name '{notice.get('cardholder_name')}' matches registered guest name.")
            else:
                discrepancies.append({
                    "type": "NAME_MISMATCH",
                    "severity": "warning",
                    "message": (
                        f"Cardholder name '{notice.get('cardholder_name')}' differs from registered guest "
                        f"'{folio.get('guest_name')}'. Third-party booking or family member authorization required."
                    ),
                })

        # 4. Transaction date vs. stay window
        txn_date = parse_date(notice.get("transaction_date"))
        stay_in = parse_date(folio.get("check_in"))
        stay_out = parse_date(folio.get("check_out"))
        if txn_date and stay_in and stay_out:
            if stay_in <= txn_date <= stay_out:
                audit_highlights.append(f"Transaction date {txn_date.isoformat()} falls within the folio stay window.")
            else:
                discrepancies.append({
                    "type": "DATE_OUTSIDE_STAY",
                    "severity": "warning",
                    "message": (
                        f"Transaction date {txn_date.isoformat()} is outside the stay window "
                        f"{stay_in.isoformat()} to {stay_out.isoformat()}. Confirm this is the correct folio."
                    ),
                })

        # 5. Response deadline
        deadline = parse_date(notice.get("response_deadline"))
        days_to_deadline: Optional[int] = None
        if deadline:
            days_to_deadline = (deadline - today).days
            if days_to_deadline < 0:
                discrepancies.append({
                    "type": "DEADLINE_PASSED",
                    "severity": "critical",
                    "message": f"Response deadline {deadline.isoformat()} passed {-days_to_deadline} day(s) ago.",
                })
            elif days_to_deadline <= DEADLINE_WARNING_DAYS:
                discrepancies.append({
                    "type": "DEADLINE_NEAR",
                    "severity": "warning",
                    "message": f"Response deadline {deadline.isoformat()} is in {days_to_deadline} day(s).",
                })
        else:
            discrepancies.append({
                "type": "DEADLINE_UNKNOWN",
                "severity": "info",
                "message": "Response deadline not found on the notice. Confirm it with the processor.",
            })

        # 6. Evidence Completeness Calculation
        network = notice.get("card_network") or "Visa"
        code = notice.get("reason_code") or ""
        required_items = get_evidence_checklist_for_dispute(network, code)

        evidence_status = []
        for req in required_items:
            source = next((src for pattern, src in _EVIDENCE_RULES if pattern.search(req)), None)
            present = cls._evidence_present(source, folio, folio_charges, docs) if source else False
            evidence_status.append({
                "item": req,
                "present": present,
                "status": "Available" if present else ("Missing / Incomplete" if source else "Manual Verification Required"),
            })

        score_points = sum(1 for e in evidence_status if e["present"])
        completeness_pct = int(round(score_points / len(evidence_status) * 100)) if evidence_status else 0

        if completeness_pct >= 85:
            assessment = "Strong Evidence Coverage (all key exhibits available)"
            status_color = "green"
        elif completeness_pct >= 60:
            assessment = "Moderate Evidence Coverage (supplementary records recommended)"
            status_color = "orange"
        else:
            assessment = "Weak Evidence Coverage (high risk of representment failure)"
            status_color = "red"

        return {
            "disputed_amount": disp_amt,
            "folio_charges": folio_charges,
            "folio_payments": folio_payments,
            "folio_balance": balance,
            "is_exact_match": is_exact_match,
            "is_partial": is_partial,
            "discrepancies": discrepancies,
            "audit_highlights": audit_highlights,
            "completeness_score": completeness_pct,
            "completeness_assessment": assessment,
            "status_color": status_color,
            "evidence_checklist": evidence_status,
            "missing_evidence": [e["item"] for e in evidence_status if not e["present"]],
            "supporting_docs": docs,
            "days_to_deadline": days_to_deadline,
            "rule_details": lookup_reason_code(network, code),
        }
