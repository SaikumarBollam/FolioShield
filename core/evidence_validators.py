"""
Evidence Validators for FolioShield (Phase 3: Evidence Mapping).

A validator answers not "is a document present?" but "does the collected
evidence actually prove the fact this reason code requires?" Each validator
receives a context dict:

    {
      "notice": {...}, "folio": {...},
      "evidence": {doc_type: EvidenceItem-dict},
      "item": EvidenceItem-dict for the spec's primary doc type (or None),
      "disputed_items": [...], "proofs": [...], "recon": {...},
    }

and returns (status, detail) where status is:
  "satisfied"  — evidence proves the fact
  "weak"       — evidence present but does not fully prove the fact
  "adverse"    — evidence present and it hurts (e.g. AVS no-match)
  "missing"    — no usable evidence
Validators never invent facts: unknown detail fields yield "weak", not failure.
"""

import re
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

AMOUNT_TOLERANCE = 0.01

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
                 "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %I:%M %p",
                 "%m/%d/%Y %I:%M %p")


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not value or not isinstance(value, str):
        return None
    text = value.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def _money(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


def _details(item: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return (item or {}).get("details") or {}


def _present(item: Optional[Dict[str, Any]]) -> bool:
    return bool(item and item.get("present"))


# ---------------------------------------------------------------------------
# Validators
# ---------------------------------------------------------------------------

def v_folio_footing(ctx: Dict[str, Any]) -> Tuple[str, str]:
    footing = (ctx.get("recon") or {}).get("folio_footing") or {}
    if not footing.get("has_line_items"):
        return "missing", "No itemized folio collected; footing cannot be proven."
    if footing.get("footing_ok"):
        return "satisfied", (f"Folio foots: Σ charges ${footing.get('items_charges', 0):,.2f}, "
                             f"Σ credits ${footing.get('items_payments', 0):,.2f}.")
    return "adverse", "Folio does not foot (see Phase 2 footing proof) — correct the folio before citing it as evidence."


def v_avs_cvv_match(ctx: Dict[str, Any]) -> Tuple[str, str]:
    folio = ctx["folio"]
    item = ctx.get("item")
    details = _details(item)
    avs = str(folio.get("avs_result") or details.get("avs_result") or "").strip()
    cvv = str(folio.get("cvv_result") or details.get("cvv_result") or "").strip()

    def _classify(value: str) -> Optional[str]:
        v = value.lower()
        if not v:
            return None
        if "no match" in v or "not matched" in v or v.startswith("n ") or v == "n" or "fail" in v:
            return "no_match"
        if "match" in v or v.startswith("y") or "full" in v or "partial" in v or v.startswith("a ") or v.startswith("p "):
            return "match"
        return "unknown"

    avs_class, cvv_class = _classify(avs), _classify(cvv)
    if avs_class == "no_match" or cvv_class == "no_match":
        return "adverse", f"AVS/CVV result on file is a NO-MATCH (AVS: {avs or 'n/a'}, CVV: {cvv or 'n/a'}). Do not cite it as authorization proof."
    if avs_class == "match" or cvv_class == "match":
        return "satisfied", f"AVS/CVV matched at authorization (AVS: {avs or 'on file'}, CVV: {cvv or 'on file'})."
    if _present(item) or avs or cvv:
        return "weak", "AVS/CVV evidence present but the result value is not recorded — record the response code (e.g. 'Y - full match')."
    if folio.get("auth_code"):
        return "weak", "Authorization code present, but no AVS/CVV result collected."
    return "missing", "No AVS/CVV result collected."


def v_three_ds_authenticated(ctx: Dict[str, Any]) -> Tuple[str, str]:
    folio = ctx["folio"]
    status = str(folio.get("three_ds_status") or "").lower()
    eci = str(folio.get("three_ds_eci") or "")
    if status == "authenticated":
        return "satisfied", f"3-D Secure authenticated{f' (ECI {eci})' if eci else ''} — liability shift applies."
    if status == "attempted":
        return "weak", f"3-D Secure attempted but not fully authenticated{f' (ECI {eci})' if eci else ''} — partial liability shift only."
    if status == "not_authenticated":
        return "adverse", "3-D Secure was NOT authenticated for this transaction. Do not claim 3DS protection."
    if _present(ctx.get("item")):
        return "weak", "3DS record attested but status/ECI not recorded — record the ECI and authentication result."
    return "missing", "No 3-D Secure record collected."


def v_no_unresolved_complaints(ctx: Dict[str, Any]) -> Tuple[str, str]:
    item = ctx.get("item")
    if not _present(item):
        return "missing", "No guest service log collected."
    details = _details(item)
    unresolved = details.get("unresolved_complaints")
    if unresolved is None:
        unresolved = details.get("open_complaints")
    if unresolved is not None:
        try:
            count = int(unresolved)
        except (TypeError, ValueError):
            count = None
        if count == 0:
            return "satisfied", "Service log confirms zero unresolved complaints during the stay."
        if count is not None and count > 0:
            return "adverse", f"Service log shows {count} UNRESOLVED complaint(s) — this evidence hurts a defective-services defense. Resolve/address them in the rebuttal instead of citing a clean log."
    return "weak", "Service log present but unresolved-complaint count not recorded — record 'unresolved_complaints: 0' after verifying."


def v_stay_window_overlap(ctx: Dict[str, Any]) -> Tuple[str, str]:
    item = ctx.get("item")
    if not _present(item):
        return "missing", "No keycard/WiFi audit log collected."
    details = _details(item)
    folio = ctx["folio"]
    stay_in = _parse_dt(folio.get("check_in"))
    stay_out = _parse_dt(folio.get("check_out"))
    first = _parse_dt(details.get("first_entry") or details.get("first_seen"))
    last = _parse_dt(details.get("last_entry") or details.get("last_seen"))
    entries = details.get("entries")
    if stay_in and stay_out and (first or last):
        lo = stay_in - timedelta(days=1)
        hi = stay_out + timedelta(days=1, hours=23, minutes=59)
        probe = first or last
        if lo <= probe <= hi:
            return "satisfied", f"Audit entries fall inside the stay window ({folio.get('check_in')} → {folio.get('check_out')}){f', {entries} entries' if entries else ''}."
        return "adverse", "Audit-log entries fall OUTSIDE the stay window — wrong room/dates export, or the log does not prove this stay."
    if entries:
        return "weak", f"Audit log present ({entries} entries) but entry dates not recorded — record first/last entry timestamps to prove the stay window."
    return "weak", "Audit log attested but no entry timestamps recorded — record first/last entry to bind it to this stay."


def v_booking_recipient(ctx: Dict[str, Any]) -> Tuple[str, str]:
    item = ctx.get("item")
    if not _present(item):
        return "missing", "No booking confirmation collected."
    details = _details(item)
    folio = ctx["folio"]
    recipient = str(details.get("recipient") or details.get("sent_to") or "").strip().lower()
    guest_email = str(folio.get("guest_email") or "").strip().lower()
    sent_at = details.get("sent_at") or details.get("sent_timestamp")
    if recipient and guest_email:
        if recipient == guest_email or recipient in guest_email or guest_email in recipient:
            return "satisfied", f"Confirmation sent to the guest's email ({recipient}){f' at {sent_at}' if sent_at else ''}."
        return "weak", f"Confirmation recipient ({recipient}) differs from the guest email on file ({guest_email}) — confirm it is the cardholder's address."
    if recipient:
        return "weak", f"Confirmation recipient recorded ({recipient}) but no guest email on the folio to match it against."
    return "weak", "Booking confirmation present but recipient/sent-at not recorded — record who received it and when."


def v_policy_acceptance(ctx: Dict[str, Any]) -> Tuple[str, str]:
    item = ctx.get("item")
    folio = ctx["folio"]
    if not _present(item):
        if folio.get("cancellation_timestamp") or folio.get("rate_plan"):
            return "weak", "Rate plan/cancellation data on the folio, but the booking-time policy acceptance (exact text + timestamp) is not collected."
        return "missing", "No cancellation-policy acceptance collected."
    details = _details(item)
    accepted_at = details.get("accepted_at") or details.get("acceptance_timestamp") or details.get("clicked_at")
    has_text = bool(details.get("policy_text") or details.get("exact_text"))
    if accepted_at and has_text:
        return "satisfied", f"Exact policy text on file, accepted at {accepted_at}."
    if accepted_at:
        return "weak", f"Policy acceptance timestamp recorded ({accepted_at}) but the exact policy text is not attached."
    if has_text:
        return "weak", "Exact policy text on file but no acceptance timestamp — record when the guest accepted it."
    return "weak", "Policy acceptance attested but neither exact text nor acceptance timestamp recorded."


def v_refund_receipt_match(ctx: Dict[str, Any]) -> Tuple[str, str]:
    folio = ctx["folio"]
    refund = _money(folio.get("refund_amount"))
    item = ctx.get("item")
    if refund <= 0:
        return "satisfied", "No refund recorded on this folio — receipt not applicable."
    if not _present(item):
        return "missing", f"A ${refund:,.2f} refund is recorded but the processor credit receipt is not collected — it is the decisive exhibit."
    details = _details(item)
    receipt_amt = _money(details.get("amount")) if details.get("amount") is not None else None
    if receipt_amt is not None:
        if abs(receipt_amt - refund) < AMOUNT_TOLERANCE:
            return "satisfied", f"Refund receipt amount ${receipt_amt:,.2f} matches the folio refund ${refund:,.2f}."
        return "adverse", f"Refund receipt amount ${receipt_amt:,.2f} does NOT match the folio refund ${refund:,.2f} — reconcile before submitting."
    return "weak", "Refund receipt present but its amount is not recorded — record amount/date/reference from the receipt."


def v_single_settlement(ctx: Dict[str, Any]) -> Tuple[str, str]:
    recon = ctx.get("recon") or {}
    dupes = [d for d in recon.get("discrepancies", []) if d.get("type") == "POSSIBLE_DUPLICATE_PAYMENT"]
    if dupes:
        return "adverse", "A possible duplicate settlement was detected (Phase 2) — a 'single settlement' claim cannot be made until resolved."
    state = recon.get("settlement_state")
    if state in ("SETTLED", "SETTLED_THEN_REFUNDED"):
        return "satisfied", f"Single settlement proven (settlement state: {state}; duplicate check passed by auth/reference)."
    if state == "OVERPAID":
        return "weak", "Folio is overpaid — settlement count needs manual verification before claiming a single settlement."
    return "weak", "Settlement state not fully proven; attach the batch/settlement report to prove a single settlement."


def v_per_item_slip_match(ctx: Dict[str, Any]) -> Tuple[str, str]:
    """
    Per-disputed-item binding: each disputed Charge line needs slip evidence
    whose details match the line's reference and/or exact amount.
    Evidence details may carry: slip_reference, amount, slips: [{reference, amount}].
    """
    disputed = [i for i in (ctx.get("disputed_items") or []) if i.get("type") == "Charge"]
    item = ctx.get("item")
    if not disputed:
        return "satisfied", "No disputed incidental lines in scope — per-item slips not applicable."
    if not _present(item):
        return "missing", f"No POS slips collected for {len(disputed)} disputed line item(s) — the exact-amount signed slip is the decisive exhibit."
    details = _details(item)
    slips: List[Dict[str, Any]] = []
    if isinstance(details.get("slips"), list):
        slips = [s for s in details["slips"] if isinstance(s, dict)]
    if details.get("slip_reference") or details.get("amount") is not None:
        slips.append({"reference": details.get("slip_reference"), "amount": details.get("amount")})

    covered, uncovered = [], []
    for line in disputed:
        amt = _money(line.get("amount"))
        ref = str(line.get("reference") or "").strip().lower()
        hit = None
        for slip in slips:
            s_amt = _money(slip.get("amount")) if slip.get("amount") is not None else None
            s_ref = str(slip.get("reference") or "").strip().lower()
            if ref and s_ref and ref == s_ref:
                hit = slip
                break
            if s_amt is not None and abs(s_amt - amt) < AMOUNT_TOLERANCE and (not ref or not s_ref or s_ref == ref):
                hit = slip
                break
        (covered if hit else uncovered).append(line)

    total = len(disputed)
    if not uncovered:
        return "satisfied", f"Signed slip(s) match all {total} disputed item(s) by reference/exact amount."
    if covered:
        names = ", ".join(f"{u.get('description')} (${_money(u.get('amount')):,.2f})" for u in uncovered[:3])
        return "weak", f"Slips cover {len(covered)} of {total} disputed item(s). Missing exact-amount slip for: {names}."
    return "weak", f"POS slips present but none matches a disputed item by reference/exact amount ({total} item(s) uncovered). Record slip_reference + amount per slip."


VALIDATORS: Dict[str, Callable[[Dict[str, Any]], Tuple[str, str]]] = {
    "folio_footing": v_folio_footing,
    "avs_cvv_match": v_avs_cvv_match,
    "three_ds_authenticated": v_three_ds_authenticated,
    "no_unresolved_complaints": v_no_unresolved_complaints,
    "stay_window_overlap": v_stay_window_overlap,
    "booking_recipient": v_booking_recipient,
    "policy_acceptance": v_policy_acceptance,
    "refund_receipt_match": v_refund_receipt_match,
    "single_settlement": v_single_settlement,
    "per_item_slip_match": v_per_item_slip_match,
}
