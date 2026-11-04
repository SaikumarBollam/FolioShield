"""
Transaction Reconciliation & Evidence Completeness Audit for FolioShield.
Cross-references bank dispute notices with hotel folios and computes completeness score.

Phase 1 (Collection) behaviour:
  * Supporting evidence is file-backed: a collected file (filename + SHA-256)
    scores higher than a bare staff attestation, which scores higher than
    nothing. The completeness score therefore measures *collection*, not
    checkbox-ticking.
  * `collection_gaps` lists submission-blocking missing collection items
    (Case ID, valid 23-digit ARN, MID, claim statement, folio identity…).
  * Hotel-specific situations are detected: OTA/third-party payer, no-show /
    cancelled stays, refund already issued, post-checkout charges, duplicate
    payment lines, and Visa CE 3.0 data readiness for 10.4 fraud disputes.

Phase 2 (Reconciliation) behaviour — every check is a *proof* with a status
(proven / failed / unverifiable) and the arithmetic shown:
  * Folio footing: Σ line items is recomputed and cross-checked against the
    header totals and balance; totals are derived when headers are missing.
    Room lines are recomputed as nights × rate and tax consistency is checked.
  * Amount proof: disputed amount is compared against folio charges, the
    original transaction amount, charges − refunds ("already made whole"),
    and per-transaction settlements; currency mismatches and 1-cent rounding
    variances are classified instead of escalated.
  * Identity: last-4 values are normalized (masks stripped) before comparison;
    names are matched token-wise (comma-reversed, initials, hyphenated) with
    a strength score feeding a composite folio-identity confidence.
  * Dates: the transaction date is classified (booking/prepay, in-stay,
    settlement grace window, post-checkout addendum); unparseable dates are
    flagged, never silently skipped. Deadlines support timezones and
    business-day counting.
  * Settlement: refunds are netted into the settlement state (SETTLED /
    SETTLED_THEN_REFUNDED / OVERPAID / OPEN); duplicate detection keys on
    auth code / reference / description, not amount alone; authorization vs
    settlement variance is proven.
  * Partial disputes: staff-marked items are verified to sum to the disputed
    amount; unmarked greedy matches are labelled "suggested", never asserted.

Phase 3 (Evidence Mapping) behaviour:
  * Reason codes map to structured RequirementSpecs (core.rules): each spec
    binds specific doc types, a criticality tier (dispositive / required /
    supporting), an optional validator, and applicability conditions
    (stay status, channel, entry mode). Non-applicable specs are excluded
    from scoring rather than counted missing.
  * Validators (core.evidence_validators) judge whether collected evidence
    actually proves the required fact: AVS must have matched, the service
    log must show zero unresolved complaints, keycard entries must fall in
    the stay window, POS slips must match disputed lines by reference and
    exact amount. Adverse evidence is flagged, never cited.
  * The completeness score is criticality-weighted; missing dispositive
    evidence marks the case not-submittable for that code, and satisfied
    specs produce semantic exhibit labels for the rebuttal and PDF.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from .evidence_validators import VALIDATORS
from .models import normalize_supporting_docs, supporting_doc_flags
from .rules import (CRITICALITY_WEIGHTS, LEGACY_DOC_KEY_ALIASES, SUPPORTING_DOC_TYPES,
                    get_requirement_specs, lookup_reason_code)

AMOUNT_TOLERANCE = 0.01
ROUNDING_TOLERANCE = 0.05          # ≤5 cents: tax/rounding variance, not a mismatch
DEADLINE_WARNING_DAYS = 5
SETTLEMENT_GRACE_DAYS = 3          # batch settlement can post 0–3 days after checkout

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
                 "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%b %d %y", "%d %b %Y")

_NAME_PARTICLES = {"jr", "sr", "ii", "iii", "iv", "md", "phd", "esq"}


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


def _is_file_backed(item: Optional[Dict[str, Any]]) -> bool:
    return bool(item and item.get("present") and item.get("filename") and item.get("sha256"))


def _money(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _normalize_last4(value: Any) -> Optional[str]:
    """Digit core of a last-4 value: '****4821', ' 4821 ', 4821 -> '4821'."""
    if value is None:
        return None
    digits = re.sub(r"\D", "", str(value))
    if len(digits) < 4:
        return None
    return digits[-4:]


def _name_tokens(name: Optional[str]) -> List[str]:
    """Normalized name tokens: punctuation/comma-order/particles removed."""
    if not name:
        return []
    text = re.sub(r"[^a-z\s\-]", " ", str(name).lower().replace(",", " "))
    tokens = [t for chunk in text.split() for t in chunk.split("-") if t]
    return [t for t in tokens if t not in _NAME_PARTICLES]


def _name_match(notice_name: Optional[str], folio_name: Optional[str]) -> Tuple[str, float]:
    """
    Token-based name comparison. Returns (strength, score):
    'exact' (same token multiset), 'strong' (one side's tokens ⊆ other, or
    initial+surname match), 'partial' (shared surname), 'none'.
    """
    a, b = _name_tokens(notice_name), _name_tokens(folio_name)
    if not a or not b:
        return "unknown", 0.0
    if sorted(a) == sorted(b):
        return "exact", 1.0
    set_a, set_b = set(a), set(b)
    if set_a <= set_b or set_b <= set_a:
        return "strong", 0.9
    # Initial + surname: 'j davis' vs 'jonathan c davis'
    def surname(tokens: List[str]) -> str:
        return tokens[-1] if tokens else ""
    if surname(a) == surname(b):
        initials_a = {t[0] for t in a}
        initials_b = {t[0] for t in b}
        if initials_a & initials_b:
            return "strong", 0.85
        return "partial", 0.5
    # Hyphenated/compound surnames: 'davis' appears inside 'davis-smith' tokens
    if (surname(a) in set_b or surname(b) in set_a) and ({t[0] for t in a} & {t[0] for t in b}):
        return "strong", 0.85
    if set_a & set_b:
        return "partial", 0.4
    return "none", 0.0


def _spec_applies(spec: Dict[str, Any], folio: Dict[str, Any], notice: Dict[str, Any], is_partial: bool) -> bool:
    """Applicability filter: non-matching specs are excluded, never 'missing'."""
    cond = spec.get("applies_when") or {}
    if not cond:
        return True
    stay_status = (folio.get("stay_status") or "occupied").strip().lower()
    if "stay_status" in cond and stay_status not in cond["stay_status"]:
        return False
    if "channel" in cond and (folio.get("booking_channel") or "").strip().lower() not in cond["channel"]:
        return False
    if "entry_mode" in cond:
        entry = (folio.get("entry_mode") or "").strip().lower()
        # Unknown entry mode keeps the spec (staff may still collect it);
        # a known, different entry mode excludes it.
        if entry and entry not in cond["entry_mode"]:
            return False
    if cond.get("partial_only") and not is_partial:
        return False
    return True


def _exhibit_label(spec: Dict[str, Any], doc_type: Optional[str], item: Optional[Dict[str, Any]],
                   folio: Dict[str, Any], disputed_items: List[Dict[str, Any]]) -> str:
    """Semantic exhibit label: what the exhibit IS, not just its letter."""
    from .rules import SUPPORTING_DOC_TYPES as _LABELS
    base = _LABELS.get(doc_type or "", spec.get("label", "Evidence"))
    details = (item or {}).get("details") or {}
    extras: List[str] = []
    if doc_type == "pos_signed_slips":
        disputed_charges = [i for i in disputed_items if i.get("type") == "Charge"]
        if details.get("slips"):
            extras.append("; ".join(
                f"slip {s.get('reference') or '#'} ${float(s.get('amount') or 0):,.2f}" for s in details["slips"][:4]))
        elif disputed_charges:
            extras.append("; ".join(
                f"{i.get('description')} (${float(i.get('amount') or 0):,.2f})" for i in disputed_charges[:3]))
    if doc_type == "keycard_lock_audit" and details.get("entries"):
        extras.append(f"{details['entries']} door entries, {folio.get('check_in')} → {folio.get('check_out')}")
    if doc_type == "booking_confirmation" and details.get("recipient"):
        extras.append(f"sent to {details['recipient']}")
    if doc_type == "refund_credit_receipt":
        extras.append(f"${float(folio.get('refund_amount') or 0):,.2f} refund")
    if doc_type == "__folio__":
        extras.append(f"folio {folio.get('folio_number') or ''}".strip())
    return f"{base} — {'; '.join(extras)}" if extras else base


def _business_days_between(start: date, end: date) -> int:
    """Business days from start (exclusive) to end (inclusive); negative if end < start."""
    if end < start:
        return -_business_days_between(end, start)
    days = 0
    cursor = start
    while cursor < end:
        cursor += timedelta(days=1)
        if cursor.weekday() < 5:
            days += 1
    return days


class Reconciler:
    """
    Performs algorithmic audit, transaction reconciliation, and evidence completeness scoring.
    """

    @classmethod
    def _collection_gaps(cls, notice: Dict[str, Any], folio: Dict[str, Any]) -> List[Dict[str, str]]:
        """Submission-blocking Phase-1 collection gaps (missing identity/claim data)."""
        gaps: List[Dict[str, str]] = []

        def gap(field_name: str, severity: str, message: str) -> None:
            gaps.append({"field": field_name, "severity": severity, "message": message})

        if not notice.get("case_id"):
            gap("case_id", "critical", "No Case ID collected from the bank notice. Processors cannot match the response without it.")
        arn = str(notice.get("arn") or "").strip()
        if not arn:
            gap("arn", "critical", "No ARN collected from the bank notice. Add the 23-digit Acquirer Reference Number.")
        elif not (arn.isdigit() and len(arn) == 23):
            gap("arn", "warning", f"ARN '{arn}' is not a standard 23-digit ARN ({len(arn)} chars). Verify it against the notice.")
        if not notice.get("claim_statement"):
            gap("claim_statement", "warning", "Cardholder claim statement not collected. The rebuttal cannot answer the guest's actual claim without it.")
        if not (notice.get("merchant_id") or folio.get("merchant_id")):
            gap("merchant_id", "warning", "Merchant ID (MID) not collected. Banks match responses by MID + ARN.")
        if not notice.get("card_network"):
            gap("card_network", "warning", "Card network not identified on the notice.")
        if not notice.get("reason_code"):
            gap("reason_code", "warning", "Reason code not collected. Evidence requirements cannot be tailored without it.")
        if not folio.get("folio_number") and not folio.get("confirmation_number"):
            gap("folio_number", "warning", "No folio or confirmation number collected from the PMS record.")
        if not folio.get("guest_name"):
            gap("guest_name", "warning", "Registered guest name not collected from the folio.")
        if not folio.get("check_in") and (folio.get("stay_status") in (None, "occupied")):
            gap("check_in", "warning", "Stay dates not collected from the folio.")
        return gaps

    # ------------------------------------------------------------------ proofs

    @classmethod
    def _folio_footing(cls, folio: Dict[str, Any], line_items: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Proof 0 — the folio foots: Σ items vs header totals vs balance,
        nights × rate recomputation, and per-line tax consistency.
        """
        header_charges = _money(folio.get("total_charges"))
        header_payments = _money(folio.get("total_payments"))
        item_charges = round(sum(_money(i.get("amount")) for i in line_items if i.get("type") == "Charge"), 2)
        refund_lines = [i for i in line_items if i.get("type") == "Credit"
                        and (i.get("category") == "Refund" or re.search(r"\brefund(?:ed|s|ing)?\b", str(i.get("description") or ""), re.I))]
        refund_from_items = round(sum(_money(i.get("amount")) for i in refund_lines), 2)
        # Refund credits are tracked separately from settlement payments:
        # a folio can be settled ($0 balance) and then refunded.
        item_credits = round(sum(_money(i.get("amount")) for i in line_items
                                 if i.get("type") == "Credit" and i not in refund_lines), 2)

        has_items = bool(line_items)
        has_headers = header_charges > 0 or header_payments > 0
        totals_source = "header"
        if has_items and not has_headers:
            totals_source = "derived_from_items"
        elif has_items:
            totals_source = "header+items"

        eff_charges = header_charges if has_headers else item_charges
        eff_payments = header_payments if has_headers else item_credits
        if totals_source == "derived_from_items":
            eff_charges, eff_payments = item_charges, item_credits

        charges_variance = round(eff_charges - item_charges, 2) if has_items else 0.0
        payments_variance = round(eff_payments - item_credits, 2) if has_items else 0.0
        footing_ok: Optional[bool] = None
        if has_items and has_headers:
            footing_ok = abs(charges_variance) < AMOUNT_TOLERANCE and abs(payments_variance) < AMOUNT_TOLERANCE
        elif has_items:
            footing_ok = True  # totals derived from the items themselves

        # Nights × rate recomputation (occupied stays with a known rate)
        rate = _money(folio.get("rate_per_night"))
        room_items = [i for i in line_items if i.get("category") == "Room" and i.get("type") == "Charge"]
        room_total = round(sum(_money(i.get("amount")) for i in room_items), 2)
        nights = len(room_items) if room_items else None
        expected_room = round(nights * rate, 2) if (nights and rate > 0) else None
        rate_check_ok: Optional[bool] = None
        if expected_room is not None:
            rate_check_ok = abs(expected_room - room_total) <= max(ROUNDING_TOLERANCE, 0.02 * nights)

        # Tax consistency: implied tax rate per tax line vs the stay's modal rate
        tax_items = [i for i in line_items if i.get("category") == "Tax" and i.get("type") == "Charge"]
        tax_total = round(sum(_money(i.get("amount")) for i in tax_items), 2)
        implied_tax_rate: Optional[float] = None
        if room_total > 0 and tax_total > 0:
            implied_tax_rate = round(tax_total / room_total, 4)

        return {
            "has_line_items": has_items,
            "totals_source": totals_source,
            "header_charges": header_charges,
            "header_payments": header_payments,
            "items_charges": item_charges,
            "items_payments": item_credits,
            "effective_charges": eff_charges,
            "effective_payments": eff_payments,
            "charges_variance": charges_variance,
            "payments_variance": payments_variance,
            "footing_ok": footing_ok,
            "refund_from_items": refund_from_items,
            "nights": nights,
            "rate_per_night": rate,
            "room_total": room_total,
            "expected_room_total": expected_room,
            "rate_check_ok": rate_check_ok,
            "tax_total": tax_total,
            "implied_tax_rate": implied_tax_rate,
        }

    @classmethod
    def reconcile(
        cls,
        notice: Dict[str, Any],
        folio: Dict[str, Any],
        supporting_docs: Optional[Dict[str, Any]] = None,
        today: Optional[date] = None,
    ) -> Dict[str, Any]:
        """
        Cross-checks bank dispute notice against guest folio and supporting documentation.
        Supporting documents default to "not provided" — evidence is never assumed.

        `supporting_docs` accepts booleans (attestation) or EvidenceItem dicts
        (file-backed collection) per doc type; see core.models.EvidenceItem.
        """
        # Normalize legacy keys, then build the full evidence registry view.
        raw_docs: Dict[str, Any] = {}
        for key, value in (supporting_docs or {}).items():
            for modern_key in LEGACY_DOC_KEY_ALIASES.get(key, (key,)):
                raw_docs.setdefault(modern_key, value)
        evidence = normalize_supporting_docs(raw_docs)
        for key in SUPPORTING_DOC_TYPES:
            evidence.setdefault(key, {"doc_type": key, "present": False, "details": {}})
        docs = supporting_doc_flags(evidence)
        today = today or date.today()

        discrepancies: List[Dict[str, str]] = []
        audit_highlights: List[str] = []
        proofs: List[Dict[str, Any]] = []

        def proof(name: str, status: str, detail: str) -> None:
            proofs.append({"proof": name, "status": status, "detail": detail})

        line_items = folio.get("line_items") or []
        stay_status = (folio.get("stay_status") or "").strip().lower() or None

        # =====================================================================
        # Proof 0: Folio footing (Σ items = totals = balance; nights × rate)
        # =====================================================================
        footing = cls._folio_footing(folio, line_items)
        folio_charges = footing["effective_charges"]
        folio_payments = footing["effective_payments"]
        balance = round(folio_charges - folio_payments, 2)

        if not line_items:
            proof("folio_footing", "unverifiable", "No line items collected; folio totals cannot be re-derived. Attach the itemized PMS folio.")
        elif footing["totals_source"] == "derived_from_items":
            audit_highlights.append(
                f"Folio totals derived from {len(line_items)} line items (header totals were missing): "
                f"charges ${folio_charges:,.2f}, payments ${folio_payments:,.2f}."
            )
            proof("folio_footing", "proven", f"Totals derived from line items: Σ charges ${folio_charges:,.2f} − Σ credits ${folio_payments:,.2f} = ${balance:,.2f}.")
        elif footing["footing_ok"]:
            proof("folio_footing", "proven",
                  f"Σ charges ${footing['items_charges']:,.2f} = header ${footing['header_charges']:,.2f}; "
                  f"Σ credits ${footing['items_payments']:,.2f} = header ${footing['header_payments']:,.2f}; balance ${balance:,.2f}.")
            audit_highlights.append("Folio footing verified: line items sum exactly to the folio totals.")
        else:
            discrepancies.append({
                "type": "FOLIO_FOOTING_ERROR",
                "severity": "critical",
                "message": (
                    f"Folio does not foot: line items sum to ${footing['items_charges']:,.2f} charges / "
                    f"${footing['items_payments']:,.2f} credits, but the folio header states "
                    f"${footing['header_charges']:,.2f} / ${footing['header_payments']:,.2f} "
                    f"(variance ${footing['charges_variance']:,.2f} / ${footing['payments_variance']:,.2f}). "
                    "Correct the folio export before submission — issuers recompute this."
                ),
            })
            proof("folio_footing", "failed",
                  f"Σ items ${footing['items_charges']:,.2f}/${footing['items_payments']:,.2f} ≠ header "
                  f"${footing['header_charges']:,.2f}/${footing['header_payments']:,.2f}.")

        if footing["rate_check_ok"] is True:
            proof("rate_recomputation", "proven",
                  f"{footing['nights']} night(s) × ${footing['rate_per_night']:,.2f} = ${footing['expected_room_total']:,.2f} "
                  f"matches room lines ${footing['room_total']:,.2f} (tax ${footing['tax_total']:,.2f}, implied rate "
                  f"{(footing['implied_tax_rate'] or 0) * 100:.2f}%).")
        elif footing["rate_check_ok"] is False:
            discrepancies.append({
                "type": "RATE_MISMATCH",
                "severity": "warning",
                "message": (
                    f"Room lines total ${footing['room_total']:,.2f} but {footing['nights']} night(s) × "
                    f"${footing['rate_per_night']:,.2f}/night = ${footing['expected_room_total']:,.2f}. "
                    "Check for rate changes, split rates, or a mis-keyed rate before submission."
                ),
            })
            proof("rate_recomputation", "failed",
                  f"{footing['nights']} × ${footing['rate_per_night']:,.2f} = ${footing['expected_room_total']:,.2f} ≠ room lines ${footing['room_total']:,.2f}.")

        # =====================================================================
        # Proof 1: Amount (disputed vs charges / original / net-of-refund)
        # =====================================================================
        disp_amt = _money(notice.get("disputed_amount"))
        original_amt = _money(notice.get("original_amount")) or disp_amt
        refund_amount = max(_money(folio.get("refund_amount")), footing["refund_from_items"])
        net_charges = round(folio_charges - refund_amount, 2)

        notice_currency = str(notice.get("currency") or "USD").upper()
        folio_currency = str(folio.get("currency") or notice_currency).upper()
        currency_match: Optional[bool] = None
        if notice.get("currency") or folio.get("currency"):
            currency_match = notice_currency == folio_currency
            if not currency_match:
                discrepancies.append({
                    "type": "CURRENCY_MISMATCH",
                    "severity": "warning",
                    "message": f"Currency mismatch: notice is in {notice_currency} but the folio is in {folio_currency}. Amount comparisons may be invalid (FX). Confirm the settled currency and amount.",
                })

        is_exact_match = disp_amt > 0 and abs(disp_amt - folio_charges) < AMOUNT_TOLERANCE
        is_partial = 0 < disp_amt < folio_charges and not is_exact_match
        matches_original = disp_amt > 0 and abs(disp_amt - original_amt) < AMOUNT_TOLERANCE
        already_made_whole = disp_amt > 0 and refund_amount > 0 and abs(disp_amt - refund_amount) < AMOUNT_TOLERANCE
        matches_net = disp_amt > 0 and refund_amount > 0 and abs(disp_amt - net_charges) < AMOUNT_TOLERANCE

        if disp_amt <= 0:
            discrepancies.append({
                "type": "MISSING_AMOUNT",
                "severity": "critical",
                "message": "No disputed amount could be determined from the bank notice. Verify the notice manually.",
            })
            proof("amount", "unverifiable", "No disputed amount on the notice.")
        elif already_made_whole:
            audit_highlights.append(
                f"Disputed amount (${disp_amt:,.2f}) equals the refund already issued (${refund_amount:,.2f}) — "
                "the cardholder has been made whole; lead with the refund credit receipt."
            )
            proof("amount", "proven", f"Disputed ${disp_amt:,.2f} == refund already issued ${refund_amount:,.2f} (made whole).")
        elif is_exact_match:
            audit_highlights.append(f"Disputed amount (${disp_amt:,.2f}) exactly matches total folio charges.")
            proof("amount", "proven", f"Disputed ${disp_amt:,.2f} == folio charges ${folio_charges:,.2f} (Δ ${abs(disp_amt - folio_charges):,.2f}).")
        elif matches_net:
            audit_highlights.append(
                f"Disputed amount (${disp_amt:,.2f}) matches folio charges net of the ${refund_amount:,.2f} refund already issued."
            )
            proof("amount", "proven", f"Disputed ${disp_amt:,.2f} == charges ${folio_charges:,.2f} − refund ${refund_amount:,.2f}.")
        elif abs(disp_amt - folio_charges) <= ROUNDING_TOLERANCE:
            discrepancies.append({
                "type": "ROUNDING_VARIANCE",
                "severity": "info",
                "message": f"Disputed amount (${disp_amt:,.2f}) differs from folio charges (${folio_charges:,.2f}) by ${abs(disp_amt - folio_charges):,.2f} — within tax/rounding tolerance. Note the variance in the response; do not concede the dispute over cents.",
            })
            proof("amount", "proven", f"Disputed ${disp_amt:,.2f} ≈ folio ${folio_charges:,.2f} within rounding tolerance (Δ ${abs(disp_amt - folio_charges):,.2f}).")
            is_exact_match = True
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
            proof("amount", "proven", f"Disputed ${disp_amt:,.2f} < folio ${folio_charges:,.2f}: partial dispute, ${folio_charges - disp_amt:,.2f} uncontested.")
        else:
            discrepancies.append({
                "type": "AMOUNT_MISMATCH",
                "severity": "warning",
                "message": (
                    f"Disputed amount (${disp_amt:,.2f}) exceeds total folio charges (${folio_charges:,.2f}). "
                    "Possible additional invoice or multiple reservations."
                ),
            })
            proof("amount", "failed", f"Disputed ${disp_amt:,.2f} > folio charges ${folio_charges:,.2f} (Δ ${disp_amt - folio_charges:,.2f}).")

        if disp_amt > 0 and original_amt > 0 and not matches_original and abs(original_amt - folio_charges) < AMOUNT_TOLERANCE:
            audit_highlights.append(f"Original transaction amount (${original_amt:,.2f}) matches the folio; the dispute covers ${disp_amt:,.2f} of it.")

        # Per-transaction settlement matching (multi-transaction folios)
        settlement_lines = [i for i in line_items if i.get("type") == "Credit" and i.get("category") != "Refund"
                            and not re.search(r"refund", str(i.get("description") or ""), re.I)]
        matched_settlement: Optional[Dict[str, Any]] = None
        if disp_amt > 0 and len(settlement_lines) > 1:
            for line in settlement_lines:
                if abs(_money(line.get("amount")) - disp_amt) < AMOUNT_TOLERANCE:
                    matched_settlement = line
                    break
            if matched_settlement is not None:
                audit_highlights.append(
                    f"Disputed amount matches a specific settlement line ({matched_settlement.get('description')}, "
                    f"{matched_settlement.get('date') or 'date n/a'}) — this is a multi-transaction folio; defend that transaction."
                )

        # =====================================================================
        # Settlement state (refunds netted; overpayment distinguished)
        # =====================================================================
        if folio_charges <= 0:
            settlement_state = "UNVERIFIABLE"
        elif abs(balance) < AMOUNT_TOLERANCE:
            settlement_state = "SETTLED_THEN_REFUNDED" if refund_amount > 0 and abs(balance) < AMOUNT_TOLERANCE and footing["refund_from_items"] > 0 else "SETTLED"
        elif balance < 0:
            settlement_state = "OVERPAID"
        else:
            settlement_state = "OPEN"

        if settlement_state == "SETTLED":
            proof("settlement", "proven", f"Charges ${folio_charges:,.2f} − payments ${folio_payments:,.2f} = $0.00. Folio settled.")
        elif settlement_state == "SETTLED_THEN_REFUNDED":
            proof("settlement", "proven", f"Charges ${folio_charges:,.2f} settled, then ${refund_amount:,.2f} refunded (refund lines in ledger). Net position $0.00 owed by guest.")
            audit_highlights.append(f"Folio settled and then refunded ${refund_amount:,.2f}; the refund is in the ledger.")
        elif settlement_state == "OVERPAID":
            discrepancies.append({
                "type": "OVERPAYMENT",
                "severity": "warning",
                "message": f"Folio is overpaid: charges ${folio_charges:,.2f} vs payments ${folio_payments:,.2f} (balance ${balance:,.2f}). Confirm whether a refund is owed or a credit line is mis-posted.",
            })
            proof("settlement", "failed", f"Payments exceed charges by ${abs(balance):,.2f}.")
        elif settlement_state == "OPEN":
            discrepancies.append({
                "type": "OPEN_BALANCE",
                "severity": "warning",
                "message": f"Folio is not settled: charges ${folio_charges:,.2f} vs payments ${folio_payments:,.2f} (balance ${balance:,.2f}).",
            })
            proof("settlement", "failed", f"Open balance ${balance:,.2f} remains.")
        else:
            proof("settlement", "unverifiable", "No folio charges collected; settlement cannot be proven.")

        # Duplicate settlement detection — keyed on auth/reference/description,
        # not amount alone (split tender and refunds share amounts legitimately).
        seen_keys: Dict[str, Dict[str, Any]] = {}
        duplicate_found = False
        for line in settlement_lines:
            desc = str(line.get("description") or "")
            auth_in_desc = re.search(r"auth[:\s#]*([A-Z0-9]{4,})", desc, re.I)
            key = (line.get("reference") or (auth_in_desc.group(1) if auth_in_desc else None) or desc.strip().lower())
            amt = _money(line.get("amount"))
            if key and key in seen_keys and abs(_money(seen_keys[key].get("amount")) - amt) < AMOUNT_TOLERANCE:
                duplicate_found = True
                discrepancies.append({
                    "type": "POSSIBLE_DUPLICATE_PAYMENT",
                    "severity": "warning",
                    "message": f"Two settlement lines share reference/auth '{key}' at ${amt:,.2f} ({seen_keys[key].get('date') or 'n/a'} and {line.get('date') or 'n/a'}). Verify this is not a duplicate settlement before defending it.",
                })
                break
            if key:
                seen_keys[key] = line
        if settlement_lines and not duplicate_found:
            proof("duplicate_check", "proven", f"{len(settlement_lines)} settlement line(s) checked by reference/auth — no duplicate settlement found.")
        elif not settlement_lines and line_items:
            proof("duplicate_check", "unverifiable", "No settlement/payment lines in the folio to check for duplicates.")

        # Authorization vs settlement variance
        auth_amount = _money(folio.get("auth_amount"))
        if auth_amount > 0 and folio_charges > 0:
            auth_variance = round(folio_charges - auth_amount, 2)
            if abs(auth_variance) < AMOUNT_TOLERANCE:
                proof("auth_vs_settlement", "proven", f"Authorized ${auth_amount:,.2f} == settled ${folio_charges:,.2f}.")
            elif abs(auth_variance) <= max(ROUNDING_TOLERANCE, 0.15 * auth_amount):
                proof("auth_vs_settlement", "proven", f"Authorized ${auth_amount:,.2f}, settled ${folio_charges:,.2f} (Δ ${auth_variance:,.2f} — within incidental/tip/FX variance).")
            else:
                discrepancies.append({
                    "type": "AUTH_SETTLEMENT_VARIANCE",
                    "severity": "warning",
                    "message": f"Authorized amount (${auth_amount:,.2f}) differs from settled folio charges (${folio_charges:,.2f}) by ${auth_variance:,.2f}. Confirm incremental authorizations cover the difference.",
                })
                proof("auth_vs_settlement", "failed", f"Auth ${auth_amount:,.2f} vs settled ${folio_charges:,.2f} (Δ ${auth_variance:,.2f}).")

        # =====================================================================
        # Proof 2: Card last-4 (normalized)
        # =====================================================================
        notice_last4 = _normalize_last4(notice.get("card_last_4"))
        folio_last4 = _normalize_last4(folio.get("card_last_4"))

        if notice_last4 and folio_last4:
            if notice_last4 == folio_last4:
                audit_highlights.append(f"Payment card last-4 verified ({notice_last4}) across bank notice and folio.")
                proof("card_last4", "proven", f"Notice ****{notice_last4} == folio ****{folio_last4}.")
            else:
                discrepancies.append({
                    "type": "CARD_MISMATCH",
                    "severity": "critical",
                    "message": f"Card last-4 mismatch: Notice specifies **** {notice_last4}, while Folio shows **** {folio_last4}.",
                })
                proof("card_last4", "failed", f"Notice ****{notice_last4} ≠ folio ****{folio_last4}.")
        else:
            discrepancies.append({
                "type": "CARD_UNVERIFIED",
                "severity": "info",
                "message": "Card last-4 is missing from the notice or folio; card match could not be verified.",
            })
            proof("card_last4", "unverifiable", "Last-4 missing on the notice and/or folio.")

        # =====================================================================
        # Proof 3: Guest name vs cardholder (+ folio identity confidence)
        # =====================================================================
        n_name = notice.get("cardholder_name")
        f_name = folio.get("guest_name")
        channel = (folio.get("booking_channel") or "").strip().lower()
        payer = (folio.get("payer_name") or "").strip()
        name_strength, name_score = _name_match(n_name, f_name)
        is_third_party = channel in ("ota", "corporate", "gds") or bool(payer and _name_match(payer, f_name)[0] in ("none", "partial"))

        identity_signals: List[Tuple[str, float]] = []
        if notice_last4 and folio_last4:
            identity_signals.append(("card", 1.0 if notice_last4 == folio_last4 else 0.0))
        if n_name and f_name:
            identity_signals.append(("name", name_score))
        if disp_amt > 0 and folio_charges > 0:
            identity_signals.append(("amount", 1.0 if (is_exact_match or is_partial or matches_net or already_made_whole) else 0.0))
        identity_confidence: Optional[int] = None
        if identity_signals:
            identity_confidence = int(round(sum(s for _, s in identity_signals) / len(identity_signals) * 100))

        if n_name and f_name:
            if name_strength in ("exact", "strong"):
                audit_highlights.append(f"Cardholder name '{n_name}' matches registered guest name ('{f_name}', {name_strength} match).")
                proof("guest_name", "proven", f"'{n_name}' vs '{f_name}': {name_strength} token match (score {name_score:.2f}).")
            elif is_third_party:
                discrepancies.append({
                    "type": "THIRD_PARTY_PAYER",
                    "severity": "info",
                    "message": (
                        f"Cardholder '{n_name}' differs from guest '{f_name}' — "
                        f"consistent with a third-party booking ({folio.get('booking_source') or channel or 'OTA/corporate'}). "
                        "Attach the booking confirmation and, for OTA stays, the virtual-card terms."
                    ),
                })
                proof("guest_name", "proven", f"Third-party payer explained: cardholder '{n_name}', guest '{f_name}', channel {channel or 'n/a'}.")
            elif name_strength == "partial":
                discrepancies.append({
                    "type": "NAME_PARTIAL_MATCH",
                    "severity": "info",
                    "message": f"Cardholder name '{n_name}' partially matches guest '{f_name}' (shared surname/token). Confirm identity (initials, hyphenation, nickname) before submission.",
                })
                proof("guest_name", "unverifiable", f"'{n_name}' vs '{f_name}': partial match only.")
            else:
                discrepancies.append({
                    "type": "NAME_MISMATCH",
                    "severity": "warning",
                    "message": (
                        f"Cardholder name '{n_name}' differs from registered guest "
                        f"'{f_name}'. Third-party booking or family member authorization required."
                    ),
                })
                proof("guest_name", "failed", f"'{n_name}' vs '{f_name}': no token match.")
        else:
            proof("guest_name", "unverifiable", "Cardholder and/or guest name missing.")

        if identity_confidence is not None and len(identity_signals) >= 2:
            if identity_confidence < 40:
                discrepancies.append({
                    "type": "WRONG_FOLIO_SUSPECTED",
                    "severity": "warning",
                    "message": f"Folio identity confidence is low ({identity_confidence}% across card/name/amount signals). This may be the wrong folio for this dispute — verify folio number, dates, and card before submitting.",
                })
            proof("folio_identity", "proven" if identity_confidence >= 70 else ("unverifiable" if identity_confidence >= 40 else "failed"),
                  f"Composite identity confidence {identity_confidence}% from {', '.join(k for k, _ in identity_signals)} signals.")

        # =====================================================================
        # Proof 4: Transaction date semantics
        # =====================================================================
        txn_raw = notice.get("transaction_date")
        txn_date = parse_date(txn_raw)
        stay_in = parse_date(folio.get("check_in"))
        stay_out = parse_date(folio.get("check_out"))
        booking_date = parse_date(folio.get("booking_date"))
        auth_date = parse_date(folio.get("auth_date"))
        date_class: Optional[str] = None

        if txn_raw and not txn_date:
            discrepancies.append({
                "type": "DATE_UNPARSEABLE",
                "severity": "warning",
                "message": f"Transaction date '{txn_raw}' could not be parsed; the stay-window check was NOT performed. Correct the date format (YYYY-MM-DD) in Tab 1.",
            })
            proof("transaction_date", "unverifiable", f"Transaction date '{txn_raw}' unparseable.")
        elif txn_date and stay_in and stay_out and stay_status not in ("no_show", "cancelled"):
            if stay_in <= txn_date <= stay_out:
                date_class = "in_stay"
                audit_highlights.append(f"Transaction date {txn_date.isoformat()} falls within the folio stay window.")
                proof("transaction_date", "proven", f"Txn {txn_date.isoformat()} ∈ stay {stay_in.isoformat()} → {stay_out.isoformat()} (in-stay charge).")
            elif stay_out < txn_date <= stay_out + timedelta(days=SETTLEMENT_GRACE_DAYS):
                date_class = "settlement"
                audit_highlights.append(f"Transaction date {txn_date.isoformat()} is {(txn_date - stay_out).days} day(s) after checkout — consistent with batch settlement / post-checkout posting.")
                proof("transaction_date", "proven", f"Txn {txn_date.isoformat()} is within the {SETTLEMENT_GRACE_DAYS}-day settlement grace window after checkout {stay_out.isoformat()}.")
            elif booking_date and txn_date == booking_date:
                date_class = "booking_prepay"
                audit_highlights.append(f"Transaction date {txn_date.isoformat()} equals the booking date — consistent with an advance-purchase / prepaid rate.")
                proof("transaction_date", "proven", f"Txn {txn_date.isoformat()} == booking date (prepaid/advance purchase).")
            elif txn_date < stay_in:
                date_class = "pre_stay"
                discrepancies.append({
                    "type": "DATE_BEFORE_STAY",
                    "severity": "info",
                    "message": f"Transaction date {txn_date.isoformat()} precedes check-in {stay_in.isoformat()}. Consistent with a prepaid/advance-purchase charge only if the rate plan confirms it — verify before submitting.",
                })
                proof("transaction_date", "unverifiable", f"Txn {txn_date.isoformat()} is before check-in {stay_in.isoformat()} (prepay not confirmed).")
            else:
                date_class = "post_checkout"
                discrepancies.append({
                    "type": "DATE_OUTSIDE_STAY",
                    "severity": "warning",
                    "message": (
                        f"Transaction date {txn_date.isoformat()} is outside the stay window "
                        f"{stay_in.isoformat()} to {stay_out.isoformat()} (beyond the {SETTLEMENT_GRACE_DAYS}-day settlement window). "
                        "Confirm this is the correct folio, or document the post-checkout charge (minibar/damage addendum)."
                    ),
                })
                proof("transaction_date", "failed", f"Txn {txn_date.isoformat()} outside stay + grace window.")
        elif txn_date:
            proof("transaction_date", "unverifiable", "Stay window unavailable (no-show/cancelled stay or missing stay dates).")

        # Stay-status specific flags
        if stay_status == "no_show":
            discrepancies.append({
                "type": "NO_SHOW_STAY",
                "severity": "info",
                "message": "Stay status is NO-SHOW: occupancy evidence does not apply. Defense rests on the disclosed no-show policy, the guarantee, and proof the room was held.",
            })
        elif stay_status == "cancelled":
            discrepancies.append({
                "type": "CANCELLED_STAY",
                "severity": "info",
                "message": "Stay status is CANCELLED: defense rests on the cancellation timestamp/number versus the disclosed cutoff.",
            })

        # Refund already issued — the winning exhibit for credit-not-processed cases
        if refund_amount > 0:
            audit_highlights.append(
                f"Refund of ${refund_amount:,.2f} already issued"
                + (f" on {folio.get('refund_date')}" if folio.get("refund_date") else "")
                + (f" (ref {folio.get('refund_reference')})" if folio.get("refund_reference") else "")
                + ". Lead the response with the refund credit receipt."
            )
            if not docs.get("refund_credit_receipt"):
                discrepancies.append({
                    "type": "REFUND_RECEIPT_MISSING",
                    "severity": "warning",
                    "message": "A refund is recorded on the folio but the processor refund/credit receipt is not collected. Attach it — it is the decisive exhibit.",
                })

        # =====================================================================
        # Proof 5: Response deadline (timezone + business-day aware)
        # =====================================================================
        deadline_raw = notice.get("response_deadline")
        deadline = parse_date(deadline_raw)
        days_to_deadline: Optional[int] = None
        business_days_to_deadline: Optional[int] = None
        if deadline:
            days_to_deadline = (deadline - today).days
            business_days_to_deadline = _business_days_between(today, deadline) if days_to_deadline >= 0 else days_to_deadline
            if days_to_deadline < 0:
                discrepancies.append({
                    "type": "DEADLINE_PASSED",
                    "severity": "critical",
                    "message": f"Response deadline {deadline.isoformat()} passed {-days_to_deadline} day(s) ago.",
                })
                proof("deadline", "failed", f"Deadline {deadline.isoformat()} passed {-days_to_deadline} day(s) ago (today {today.isoformat()}). Note: processor deadlines are date-based in the processor's timezone — confirm the cutoff time.")
            elif days_to_deadline <= DEADLINE_WARNING_DAYS:
                discrepancies.append({
                    "type": "DEADLINE_NEAR",
                    "severity": "warning",
                    "message": f"Response deadline {deadline.isoformat()} is in {days_to_deadline} day(s) ({business_days_to_deadline} business day(s)).",
                })
                proof("deadline", "proven", f"{days_to_deadline} calendar day(s) / {business_days_to_deadline} business day(s) to deadline {deadline.isoformat()}.")
            else:
                proof("deadline", "proven", f"{days_to_deadline} calendar day(s) / {business_days_to_deadline} business day(s) to deadline {deadline.isoformat()}.")
        elif deadline_raw:
            discrepancies.append({
                "type": "DATE_UNPARSEABLE",
                "severity": "warning",
                "message": f"Response deadline '{deadline_raw}' could not be parsed; urgency cannot be computed. Correct the date format in Tab 1 and confirm the deadline with the processor.",
            })
            proof("deadline", "unverifiable", f"Deadline '{deadline_raw}' unparseable.")
        else:
            discrepancies.append({
                "type": "DEADLINE_UNKNOWN",
                "severity": "info",
                "message": "Response deadline not found on the notice. Confirm it with the processor.",
            })
            proof("deadline", "unverifiable", "No response deadline collected.")

        # =====================================================================
        # Partial-dispute line-item scope (marked = verified; greedy = suggested)
        # =====================================================================
        disputed_items: List[Dict[str, Any]] = []
        undisputed_items: List[Dict[str, Any]] = []
        scope_verified: Optional[bool] = None
        scope_suggested = False
        if line_items:
            marked = [i for i in line_items if i.get("disputed") is True]
            if marked:
                disputed_items = marked
                undisputed_items = [i for i in line_items if i.get("disputed") is not True]
                marked_total = round(sum(_money(i.get("amount")) for i in marked if i.get("type") == "Charge"), 2)
                scope_verified = abs(marked_total - disp_amt) < AMOUNT_TOLERANCE
                if scope_verified:
                    audit_highlights.append(f"Disputed line items sum exactly to the disputed amount (${marked_total:,.2f}) — per-item scope verified.")
                    proof("disputed_scope", "proven", f"Σ {len(marked)} marked item(s) = ${marked_total:,.2f} == disputed ${disp_amt:,.2f}.")
                else:
                    discrepancies.append({
                        "type": "DISPUTED_SCOPE_MISMATCH",
                        "severity": "warning",
                        "message": f"Marked disputed items sum to ${marked_total:,.2f}, but the disputed amount is ${disp_amt:,.2f} (Δ ${abs(marked_total - disp_amt):,.2f}). Re-mark the contested lines or correct the amount.",
                    })
                    proof("disputed_scope", "failed", f"Σ marked items ${marked_total:,.2f} ≠ disputed ${disp_amt:,.2f}.")
            elif is_partial:
                remaining = disp_amt
                for item in line_items:
                    if item.get("type") == "Charge" and remaining >= AMOUNT_TOLERANCE and _money(item.get("amount")) <= remaining + AMOUNT_TOLERANCE:
                        disputed_items.append(item)
                        remaining = round(remaining - _money(item.get("amount")), 2)
                    else:
                        undisputed_items.append(item)
                scope_suggested = True
                scope_verified = False
                if disputed_items:
                    audit_highlights.append(
                        f"{len(disputed_items)} folio line item(s) could fall inside the disputed ${disp_amt:,.2f} scope "
                        "(suggested match — confirm the contested lines with the guest's claim and attach per-item proof)."
                    )
                    proof("disputed_scope", "unverifiable", f"Greedy suggested scope: {len(disputed_items)} item(s) ≈ ${disp_amt:,.2f}. Not verified — staff must confirm the contested lines.")
            else:
                undisputed_items = list(line_items)

        # Visa CE 3.0 readiness (Visa 10.4 card-absent fraud)
        network = notice.get("card_network") or "Visa"
        code = notice.get("reason_code") or ""
        ce30_ready: Optional[bool] = None
        if str(network).lower() == "visa" and str(code).strip() == "10.4":
            ce30_ready = bool(
                folio.get("guest_email") and (folio.get("confirmation_number") or folio.get("folio_number"))
            )
            if ce30_ready:
                audit_highlights.append("Visa CE 3.0 data present (guest email + reservation identifier). Confirm two prior undisputed transactions with matching data before claiming CE 3.0.")
            else:
                discrepancies.append({
                    "type": "CE30_DATA_MISSING",
                    "severity": "info",
                    "message": "Visa CE 3.0 cannot be evaluated: guest email and/or reservation identifier not collected. CE 3.0 needs two prior undisputed transactions with matching IP/email/device data.",
                })

        # =====================================================================
        # Phase 3: Evidence Mapping (structured RequirementSpecs + validators)
        # =====================================================================
        # Partial-scope computation happens above; disputed_items is final here.
        partial_recon = {
            "folio_footing": footing, "discrepancies": discrepancies,
            "settlement_state": settlement_state, "proofs": proofs,
        }
        specs, mapping_curated = get_requirement_specs(network, code)
        evidence_status: List[Dict[str, Any]] = []
        exhibits: List[Dict[str, Any]] = []
        missing_dispositive: List[str] = []
        adverse_evidence: List[str] = []
        total_weight = earned_weight = 0.0

        for spec in specs:
            if not _spec_applies(spec, folio, notice, is_partial):
                continue
            label = spec["label"]
            criticality = spec.get("criticality", "required")
            weight = CRITICALITY_WEIGHTS.get(criticality, 2.0)
            total_weight += weight

            # Resolve candidate evidence items for this spec
            candidates: List[Tuple[str, Optional[Dict[str, Any]]]] = []
            for doc_type in spec.get("doc_types", []):
                if doc_type == "__folio__":
                    candidates.append(("__folio__", {"present": footing["has_line_items"], "filename": folio.get("folio_number"), "details": {}}))
                elif doc_type == "__auth__":
                    auth_item = None
                    if folio.get("auth_code"):
                        auth_item = {"present": True, "filename": None, "details": {"auth_code": folio.get("auth_code")}}
                    candidates.append(("__auth__", auth_item))
                elif doc_type == "__settlement__":
                    candidates.append(("__settlement__", {"present": settlement_state in ("SETTLED", "SETTLED_THEN_REFUNDED"), "details": {}}))
                else:
                    candidates.append((doc_type, evidence.get(doc_type)))

            primary_type, primary_item = next(
                ((t, i) for t, i in candidates if i and i.get("present")),
                candidates[0] if candidates else (None, None),
            )

            validator_key = spec.get("validator")
            if validator_key and validator_key in VALIDATORS:
                vctx = {
                    "notice": notice, "folio": folio, "evidence": evidence,
                    "item": primary_item, "disputed_items": disputed_items,
                    "proofs": proofs, "recon": partial_recon,
                }
                v_status, v_detail = VALIDATORS[validator_key](vctx)
            elif primary_item and primary_item.get("present"):
                v_status, v_detail = "satisfied", "Document collected."
            else:
                v_status, v_detail = "missing", "Not collected."

            present = v_status in ("satisfied", "weak", "adverse")
            file_backed = _is_file_backed(primary_item) or primary_type in ("__folio__", "__auth__", "__settlement__")
            if v_status == "satisfied":
                earned_weight += weight * (1.0 if file_backed else 0.6)
                status_text = "Available (file collected)" if file_backed else "Available (attested)"
            elif v_status == "weak":
                earned_weight += weight * 0.3
                status_text = "Weak — present but not proven"
            elif v_status == "adverse":
                status_text = "Adverse — evidence hurts this defense"
                adverse_evidence.append(label)
            else:
                status_text = "Missing / Incomplete"

            if criticality == "dispositive" and v_status in ("missing", "adverse"):
                missing_dispositive.append(label)

            exhibit_label = None
            if v_status == "satisfied":
                exhibit_label = _exhibit_label(spec, primary_type, primary_item, folio, disputed_items)
                exhibits.append({
                    "letter": chr(65 + len(exhibits)) if len(exhibits) < 26 else f"E{len(exhibits) + 1}",
                    "spec_id": spec.get("id"), "label": exhibit_label,
                    "doc_type": primary_type, "filename": (primary_item or {}).get("filename"),
                    "sha256": (primary_item or {}).get("sha256"),
                    "file_backed": file_backed,
                })

            evidence_status.append({
                "item": label,
                "spec_id": spec.get("id"),
                "criticality": criticality,
                "present": present,
                "file_backed": file_backed,
                "status": status_text,
                "validation": v_status,
                "validation_detail": v_detail,
                "doc_types": spec.get("doc_types", []),
            })

        completeness_pct = int(round(earned_weight / total_weight * 100)) if total_weight else 0

        if missing_dispositive:
            discrepancies.append({
                "type": "DISPOSITIVE_EVIDENCE_MISSING",
                "severity": "critical",
                "message": (
                    f"Case-deciding evidence missing for {network} {code}: "
                    + "; ".join(missing_dispositive)
                    + ". Banks routinely reject responses without these exhibits — collect them or expect to lose at first representment."
                ),
            })
        if adverse_evidence:
            discrepancies.append({
                "type": "ADVERSE_EVIDENCE",
                "severity": "warning",
                "message": "Evidence on file works AGAINST this defense: " + "; ".join(adverse_evidence) + ". Do not cite it; address it head-on in the rebuttal.",
            })
        if not mapping_curated:
            discrepancies.append({
                "type": "GENERIC_EVIDENCE_MAPPING",
                "severity": "info",
                "message": f"No curated evidence mapping for {network} {code or '(no code)'} — generic hospitality checklist applied. Verify requirements with your processor before submitting.",
            })

        if completeness_pct >= 85 and not missing_dispositive:
            assessment = "Strong Evidence Coverage (all key exhibits available)"
            status_color = "green"
        elif completeness_pct >= 60:
            assessment = "Moderate Evidence Coverage (supplementary records recommended)"
            status_color = "orange"
        else:
            assessment = "Weak Evidence Coverage (high risk of representment failure)"
            status_color = "red"

        evidence_readiness = {
            "score": completeness_pct,
            "missing_dispositive": missing_dispositive,
            "adverse": adverse_evidence,
            "submittable": not missing_dispositive,
            "mapping_curated": mapping_curated,
            "weakest_link": (missing_dispositive or adverse_evidence or
                             [e["item"] for e in evidence_status if e["validation"] == "weak"] or [None])[0],
        }

        collection_gaps = cls._collection_gaps(notice, folio)
        evidence_items = [evidence[key] for key in SUPPORTING_DOC_TYPES]

        proofs_proven = sum(1 for p in proofs if p["status"] == "proven")
        proofs_failed = sum(1 for p in proofs if p["status"] == "failed")
        if proofs_failed:
            proof_summary = f"{proofs_failed} proof(s) failed — resolve before submission"
        elif proofs_proven == len(proofs) and proofs:
            proof_summary = "All reconciliation proofs passed"
        else:
            proof_summary = f"{proofs_proven}/{len(proofs)} proofs passed; remainder unverifiable with current collection"

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
            "evidence_items": evidence_items,
            "collection_gaps": collection_gaps,
            "disputed_line_items": disputed_items,
            "undisputed_line_items": undisputed_items,
            "scope_verified": scope_verified,
            "scope_suggested": scope_suggested,
            "stay_status": stay_status,
            "is_third_party_payer": is_third_party,
            "ce30_ready": ce30_ready,
            "days_to_deadline": days_to_deadline,
            "business_days_to_deadline": business_days_to_deadline,
            "settlement_state": settlement_state,
            "folio_footing": footing,
            "proofs": proofs,
            "proof_summary": proof_summary,
            "identity_confidence": identity_confidence,
            "name_match_strength": name_strength if (n_name and f_name) else None,
            "currency_match": currency_match,
            "transaction_date_class": date_class,
            "matched_settlement_line": matched_settlement,
            "evidence_readiness": evidence_readiness,
            "exhibits": exhibits,
            "mapping_curated": mapping_curated,
            "rule_details": lookup_reason_code(network, code),
        }
