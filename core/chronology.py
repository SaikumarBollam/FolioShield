"""
Chronology Builder for FolioShield (Phase 4: Rebuttal Drafting).

Builds the dated timeline banks expect in section 3 of a representment
letter — booking → policy acceptance → authorization → check-in / key issued
→ stay → check-out → settlement → post-stay events — using ONLY timestamps
and facts actually collected in Phase 1. Anchors that were not collected are
reported in `missing_anchors` so the letter can mark them [MISSING: ...]
instead of inventing them.

Every event: {"ts": sort key str, "date_label": str, "event": str,
              "source": str} — source names the system of record.
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y",
                 "%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %I:%M %p",
                 "%m/%d/%Y %I:%M %p", "%Y-%m-%d %H:%M %p")


def _parse_dt(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
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


def _label(dt: Optional[datetime], raw: Any) -> str:
    if dt:
        return dt.strftime("%Y-%m-%d %H:%M") if (dt.hour or dt.minute) else dt.strftime("%Y-%m-%d")
    return str(raw or "")


def build_chronology(notice: Dict[str, Any], folio: Dict[str, Any],
                     evidence: Optional[Dict[str, Dict[str, Any]]] = None,
                     recon: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """
    Returns {"events": [...], "missing_anchors": [...], "nights": int|None}.
    Events are sorted by timestamp; undated-but-known events keep folio order
    at their stay-date position.
    """
    evidence = evidence or {}
    recon = recon or {}
    events: List[Dict[str, Any]] = []
    missing: List[str] = []

    def add(raw_ts: Any, event: str, source: str) -> None:
        dt = _parse_dt(raw_ts)
        events.append({
            "ts": dt.isoformat() if dt else "",
            "date_label": _label(dt, raw_ts),
            "event": event,
            "source": source,
        })

    stay_status = (folio.get("stay_status") or "occupied").strip().lower()
    line_items = folio.get("line_items") or []
    footing = recon.get("folio_footing") or {}
    nights = footing.get("nights")

    # --- Booking -------------------------------------------------------------
    booking_bits = []
    if folio.get("booking_source") or folio.get("booking_channel"):
        booking_bits.append(f"via {folio.get('booking_source') or folio.get('booking_channel')}")
    if folio.get("confirmation_number"):
        booking_bits.append(f"confirmation {folio['confirmation_number']}")
    if folio.get("rate_plan"):
        booking_bits.append(f"rate plan: {folio['rate_plan']}")
    if folio.get("booking_date"):
        add(folio["booking_date"], f"Reservation created {' '.join(booking_bits)}".strip(), "PMS / booking engine")
    elif booking_bits:
        events.append({"ts": "", "date_label": "[date not collected]",
                       "event": f"Reservation created {' '.join(booking_bits)}".strip(), "source": "PMS / booking engine"})
        missing.append("booking date")

    policy_item = evidence.get("cancellation_policy_acceptance") or {}
    policy_details = policy_item.get("details") or {}
    if policy_details.get("accepted_at"):
        add(policy_details["accepted_at"], "Cancellation / no-show policy displayed and accepted by the guest", "Booking engine acceptance log")
    elif policy_item.get("present") and stay_status in ("cancelled", "no_show"):
        # Only a cancelled/no-show defense rests on policy acceptance; for an
        # occupied stay the acceptance timestamp is not a chronology anchor.
        missing.append("policy acceptance timestamp")

    conf_item = evidence.get("booking_confirmation") or {}
    conf_details = conf_item.get("details") or {}
    if conf_details.get("sent_at"):
        add(conf_details["sent_at"], f"Booking confirmation sent to {conf_details.get('recipient') or 'guest email on file'}", "PMS confirmation system")

    # --- Authorization ---------------------------------------------------------
    auth_bits = []
    if folio.get("auth_code"):
        auth_bits.append(f"approval code {folio['auth_code']}")
    if folio.get("auth_amount"):
        auth_bits.append(f"${_money(folio['auth_amount']):,.2f} authorized")
    avs_value = str(folio.get("avs_result") or "")
    if avs_value:
        adverse_avs = "no match" in avs_value.lower() or avs_value.strip().lower().startswith("n ")
        auth_bits.append(f"AVS: {avs_value} (adverse — not relied upon)" if adverse_avs else f"AVS: {avs_value}")
    if folio.get("cvv_result"):
        auth_bits.append(f"CVV: {folio['cvv_result']}")
    if folio.get("three_ds_status"):
        ds = str(folio["three_ds_status"])
        auth_bits.append(f"3-D Secure: {ds} (not authenticated — not relied upon)" if ds == "not_authenticated"
                         else f"3-D Secure: {ds}" + (f" (ECI {folio['three_ds_eci']})" if folio.get("three_ds_eci") else ""))
    if folio.get("entry_mode"):
        auth_bits.append(f"entry mode: {folio['entry_mode']}")
    if auth_bits:
        add(folio.get("auth_date") or folio.get("booking_date") or folio.get("check_in"),
            f"Card authorization obtained ({'; '.join(auth_bits)})", "Payment gateway / terminal")
    else:
        missing.append("authorization record")

    # --- Cancellation (cancelled / no-show branch) -----------------------------
    if stay_status in ("cancelled", "no_show"):
        if folio.get("cancellation_timestamp"):
            add(folio["cancellation_timestamp"],
                f"Reservation cancelled{(' — cancellation ' + folio['cancellation_number']) if folio.get('cancellation_number') else ''}",
                "PMS cancellation audit")
        else:
            missing.append("cancellation timestamp")
        if folio.get("check_in"):
            add(folio["check_in"], f"Guaranteed room held for arrival (scheduled check-in {folio['check_in']}); guest did not arrive" if stay_status == "no_show" else f"Scheduled stay window {folio.get('check_in')} → {folio.get('check_out')}", "PMS")

    # --- Check-in / occupancy (occupied branch) --------------------------------
    if stay_status not in ("cancelled", "no_show"):
        checkin_raw = " ".join(filter(None, [folio.get("check_in") or "", folio.get("check_in_time") or ""])).strip()
        if folio.get("check_in"):
            id_item = evidence.get("id_verification_log") or {}
            id_note = " Government photo ID verified at the desk." if id_item.get("present") else ""
            add(checkin_raw, f"Guest checked in to Room {folio.get('room_number') or '[room]'}.{id_note}", "Front desk / PMS")
            if not folio.get("check_in_time"):
                missing.append("check-in time")
        else:
            missing.append("check-in date/time")

        key_item = evidence.get("keycard_lock_audit") or {}
        key_details = key_item.get("details") or {}
        if key_details.get("first_entry"):
            add(key_details["first_entry"],
                f"Room key issued; first door entry recorded{(' (' + str(key_details['entries']) + ' entries during the stay)') if key_details.get('entries') else ''}",
                key_item.get("source") or "Door-lock system")
        elif key_item.get("present"):
            missing.append("keycard first-entry timestamp")

        # Stay summary from line items
        if line_items:
            room_lines = [i for i in line_items if i.get("category") == "Room" and i.get("type") == "Charge"]
            incidental = [i for i in line_items if i.get("type") == "Charge" and i.get("category") not in ("Room", "Tax", "Resort Fee")]
            stay_bits = []
            if nights:
                stay_bits.append(f"{nights} night(s) at ${_money(folio.get('rate_per_night')):,.2f}/night" if folio.get("rate_per_night") else f"{nights} room night(s) posted")
            if incidental:
                stay_bits.append("incidentals: " + ", ".join(
                    f"{i.get('description')} (${_money(i.get('amount')):,.2f})" for i in incidental[:5]))
            if stay_bits:
                add(folio.get("check_in"), "Stay postings — " + "; ".join(stay_bits), "Guest folio")

        if key_details.get("last_entry"):
            add(key_details["last_entry"], "Last door entry recorded", key_item.get("source") or "Door-lock system")
        checkout_raw = " ".join(filter(None, [folio.get("check_out") or "", folio.get("check_out_time") or ""])).strip()
        if folio.get("check_out"):
            add(checkout_raw, "Guest checked out", "Front desk / PMS")

    # --- Settlement --------------------------------------------------------------
    settlement_lines = [i for i in line_items if i.get("type") == "Credit" and i.get("category") != "Refund"]
    for line in settlement_lines[:4]:
        add(line.get("date"), f"Payment settled — {line.get('description')} (${_money(line.get('amount')):,.2f})", "Guest folio / batch")
    settlement_state = recon.get("settlement_state")
    if settlement_state in ("SETTLED", "SETTLED_THEN_REFUNDED") and not settlement_lines:
        events.append({"ts": "", "date_label": folio.get("check_out") or "",
                       "event": f"Folio settled to $0.00 (charges ${_money(folio.get('total_charges')):,.2f} fully paid)", "source": "Guest folio"})

    # --- Post-stay: refund / dispute ----------------------------------------------
    if _money(folio.get("refund_amount")) > 0:
        add(folio.get("refund_date"), f"Refund of ${_money(folio['refund_amount']):,.2f} issued{(' (ref ' + folio['refund_reference'] + ')') if folio.get('refund_reference') else ''}", "Processor")
    if notice.get("transaction_date") and stay_status in ("cancelled", "no_show"):
        add(notice["transaction_date"], f"Disputed charge posted (${_money(notice.get('disputed_amount')):,.2f})", "Bank notice")
    if notice.get("dispute_date"):
        add(notice["dispute_date"], f"Chargeback/dispute opened by issuer (Case {notice.get('case_id') or '[case]'})", "Bank notice")
    if notice.get("response_deadline"):
        add(notice["response_deadline"], "Merchant response deadline", "Bank notice")

    dated = [e for e in events if e["ts"]]
    undated = [e for e in events if not e["ts"]]
    dated.sort(key=lambda e: e["ts"])
    ordered = dated + undated

    # De-duplicate identical (date_label, event) pairs
    seen = set()
    unique: List[Dict[str, Any]] = []
    for e in ordered:
        key = (e["date_label"], e["event"])
        if key not in seen:
            seen.add(key)
            unique.append(e)

    return {"events": unique, "missing_anchors": missing, "nights": nights}
