"""
Legal Track Engine for FolioShield (Phase 10: Court / Legal Track).

Converts a bank dispute case into a court-ready file:

  * Damages computation — folio total, amount debited, chargeback/arbitration
    fees, recoveries → net loss, rendered as a statement of loss.
  * Document generators (ReportLab, TEMPLATE-watermarked): Business Records
    Affidavit (custodian statement + system descriptions + exhibit list with
    SHA-256 hashes + signature + notary jurat blanks), Witness Declaration
    (facts from the chronology, declaration skeleton), Demand Letter
    (amount, basis, pay-by date, certified-mail block).
  * Court exhibit bundle (ZIP) + pre-filing validator.
  * Fraud report pack: Who/What/When/Where/How-much incident summary +
    narrative from the chronology + preservation checklist (CCTV!).

HONESTY GUARDRAILS: every generated legal document is a TEMPLATE for
completion by the affiant/witness/notary and review by counsel. Nothing
here is notarized, sworn, filed, or legal advice, and the documents say so.
Jurisdiction-specific requirements (venue, small-claims limits, perjury
language) must be confirmed locally.
"""

import io
import json
import os
import re
import zipfile
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .audit_logger import AuditLogger
from ._jsonl import append_jsonl, read_jsonl
from .models import LegalFilingRecord, WitnessRecord
from .security import escape_markup as esc

TEMPLATE_BANNER = "TEMPLATE — FOR COMPLETION BY THE AFFIANT/WITNESS AND REVIEW BY COUNSEL. NOT LEGAL ADVICE. NOT AN EXECUTED DOCUMENT."
_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def _safe(name: str) -> str:
    return _SAFE.sub("_", name or "case")[:80]


def _money(value: Any) -> float:
    try:
        return round(float(value or 0.0), 2)
    except (TypeError, ValueError):
        return 0.0


# ---------------------------------------------------------------------------
# Damages
# ---------------------------------------------------------------------------

def compute_damages(notice: Dict[str, Any], folio: Dict[str, Any],
                    outcomes: Optional[List[Dict[str, Any]]] = None,
                    arbitration: Optional[List[Dict[str, Any]]] = None,
                    chargeback_fee: float = 0.0) -> Dict[str, Any]:
    """
    Statement of loss: what the hotel is out, with every component sourced.
    net_loss = debited + fees − recovered (debited defaults to the disputed
    amount actually charged back).
    """
    disputed = _money(notice.get("disputed_amount"))
    folio_total = _money(folio.get("total_charges"))
    recovered = sum(_money(o.get("amount_recovered")) for o in (outcomes or []))
    arb_fees = sum(_money(a.get("fee_paid_or_liable")) for a in (arbitration or [])
                  if (a.get("action") in ("filed", "lost")))
    refunded = _money(folio.get("refund_amount"))
    net = round(disputed + _money(chargeback_fee) + arb_fees - recovered, 2)
    return {
        "folio_total": folio_total,
        "amount_disputed_debited": disputed,
        "chargeback_fee": _money(chargeback_fee),
        "arbitration_fees": round(arb_fees, 2),
        "amount_recovered": round(recovered, 2),
        "refund_already_issued": refunded,
        "net_loss": net,
        "currency": notice.get("currency") or "USD",
        "basis": (
            "Net loss = amount debited by chargeback + chargeback/arbitration fees − amounts recovered. "
            "If a refund was already issued, the underlying service charge remains the loss component; "
            "confirm double-recovery posture with counsel before pleading figures."
        ),
    }


# ---------------------------------------------------------------------------
# PDF helpers
# ---------------------------------------------------------------------------

def _styles():
    base = getSampleStyleSheet()
    body = ParagraphStyle("LegalBody", parent=base["Normal"], fontName="Helvetica", fontSize=9.5, leading=14,
                          textColor=colors.HexColor("#111827"))
    return {
        "title": ParagraphStyle("LegalTitle", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=14,
                                leading=17, alignment=1, textColor=colors.HexColor("#111827")),
        "body": body,
        "small": ParagraphStyle("LegalSmall", parent=body, fontSize=8, leading=11, textColor=colors.HexColor("#475569")),
        "banner": ParagraphStyle("LegalBanner", parent=body, fontSize=8, leading=11,
                                 textColor=colors.HexColor("#991B1B"), fontName="Helvetica-Bold", alignment=1),
    }


def _pdf(title: str, flowables: List[Any]) -> bytes:
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, leftMargin=54, rightMargin=54, topMargin=48, bottomMargin=48,
                            title=title, author="FolioShield (template)")
    doc.build(flowables)
    return buffer.getvalue()


def _banner(s) -> List[Any]:
    return [Paragraph(TEMPLATE_BANNER, s["banner"]), Spacer(1, 10)]


def _sig_block(s, role_label: str) -> List[Any]:
    return [
        Spacer(1, 16),
        Paragraph(f"{role_label} Signature: ______________________________________ &nbsp;&nbsp; Date: ____________________", s["body"]),
        Spacer(1, 8),
        Paragraph("Printed Name / Title: ______________________________________", s["body"]),
    ]


# ---------------------------------------------------------------------------
# Generators
# ---------------------------------------------------------------------------

def generate_business_records_affidavit(notice: Dict[str, Any], folio: Dict[str, Any],
                                        manifest: Dict[str, Any],
                                        affiant: Optional[Dict[str, str]] = None) -> bytes:
    """Custodian-of-records affidavit TEMPLATE with exhibit hashes from the manifest."""
    s = _styles()
    affiant = affiant or {}
    hotel = folio.get("hotel_name") or "[HOTEL NAME]"
    files = manifest.get("files") or []
    exhibit_rows = [[Paragraph("<b>#</b>", s["body"]), Paragraph("<b>Record</b>", s["body"]),
                     Paragraph("<b>SHA-256</b>", s["body"])]]
    for i, f in enumerate(files, 1):
        exhibit_rows.append([
            Paragraph(str(i), s["body"]),
            Paragraph(esc(f.get("filename") or f.get("action") or "record"), s["body"]),
            Paragraph(f"<font face='Courier' size='7'>{esc(str(f.get('sha256') or '')[:32])}…</font>", s["body"]),
        ])
    exhibit_table = Table(exhibit_rows, colWidths=[24, 250, 220]) if files else Paragraph("[No collected records listed — attach the custody manifest.]", s["body"])
    if files:
        exhibit_table.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                                           ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#F1F5F9"))]))

    flow: List[Any] = [
        *_banner(s),
        Paragraph("BUSINESS RECORDS AFFIDAVIT", s["title"]),
        Paragraph("(Custodian of Records — Template)", s["small"]),
        Spacer(1, 12),
        Paragraph(f"State/County of ______________________________ &nbsp;&nbsp; Venue/Court: ______________________________", s["body"]),
        Spacer(1, 10),
        Paragraph(f"I, {esc(affiant.get('name') or '[AFFIANT NAME]')}, being duly sworn, declare and state:", s["body"]),
        Spacer(1, 6),
        Paragraph(f"1. I am the {esc(affiant.get('title') or '[TITLE, e.g. Front Office Manager / Custodian of Records]')} of {esc(hotel)} "
                  f"(\"[HOTEL LEGAL NAME]\"), located at {esc(folio.get('hotel_address') or '[HOTEL ADDRESS]')}, and I am a custodian of the records described below, or am otherwise qualified to authenticate them.", s["body"]),
        Paragraph("2. The records listed in paragraph 4 were made at or near the time of the events they describe, by or from information transmitted by persons with knowledge of those events, were kept in the course of regularly conducted business activity, and making them was a regular practice of that activity. [Confirm this paragraph matches your jurisdiction's business-records rule with counsel.]", s["body"]),
        Paragraph(f"3. Systems of record: Property Management System {esc(affiant.get('pms') or '[PMS NAME/VERSION, e.g. Oracle OPERA 5.6]')}; "
                  f"electronic door-lock system {esc(affiant.get('lock_system') or '[LOCK SYSTEM, e.g. Onity HT28]')}; "
                  f"payment processing via {esc(affiant.get('processor') or '[PROCESSOR/GATEWAY]')}. Electronic exports were produced from these systems in the ordinary course and hashed (SHA-256) at collection; the hash chain is recorded in the attached custody manifest (chain head: {esc(str((manifest.get('chain_head') or {}).get('head_hash') or '')[:24])}…).", s["body"]),
        Paragraph("4. Records authenticated by this affidavit (true and correct copies of the originals, or accurate exports of electronically stored information):", s["body"]),
        Spacer(1, 4),
        exhibit_table,
        Spacer(1, 8),
        Paragraph(f"5. This affidavit concerns the dispute identified as Case {esc(notice.get('case_id') or '[CASE ID]')}, ARN {esc(notice.get('arn') or '[ARN]')}, disputed amount ${_money(notice.get('disputed_amount')):,.2f} {esc(notice.get('currency') or 'USD')}.", s["body"]),
        Paragraph("I declare under penalty of perjury under the laws of ______________________________ that the foregoing is true and correct. [Perjury/declaration language varies by jurisdiction — confirm with counsel.]", s["body"]),
        *_sig_block(s, "Affiant"),
        Spacer(1, 18),
        Paragraph("<b>NOTARY JURAT (to be completed by a notary public)</b>", s["body"]),
        Paragraph("State of ____________________ &nbsp; County of ____________________<br/>"
                  "Subscribed and sworn to (or affirmed) before me on ____________________ by ______________________________________.<br/><br/>"
                  "Notary Signature: ______________________________________ &nbsp;&nbsp; [SEAL] &nbsp;&nbsp; My commission expires: ____________________", s["body"]),
        Spacer(1, 12),
        Paragraph(TEMPLATE_BANNER, s["banner"]),
    ]
    return _pdf(f"Business Records Affidavit — {notice.get('case_id') or 'case'}", flow)


def generate_witness_declaration(witness: WitnessRecord, notice: Dict[str, Any], folio: Dict[str, Any],
                                 chronology_events: List[Dict[str, Any]]) -> bytes:
    """Per-witness declaration TEMPLATE; facts pre-filled from the chronology only."""
    s = _styles()
    linked = set(witness.linked_events or [])
    fact_lines: List[str] = []
    for evt in chronology_events:
        label = (evt.get("event") or "")
        low = label.lower()
        include = (
            ("check_in" in linked and "checked in" in low)
            or ("id_verified" in linked and "id" in low)
            or ("key_issued" in linked and ("key issued" in low or "door entry" in low))
            or ("checkout" in linked and "checked out" in low)
        )
        if include:
            fact_lines.append(f"{evt.get('date_label')}: {label}")
    if not fact_lines:
        fact_lines = ["[Witness to describe, in their own words, their personal involvement: check-in, ID verification, key issuance, guest interactions.]"]

    flow: List[Any] = [
        *_banner(s),
        Paragraph("DECLARATION OF WITNESS", s["title"]),
        Paragraph("(Template — to be reviewed, completed, and signed by the witness)", s["small"]),
        Spacer(1, 12),
        Paragraph(f"I, {esc(witness.name)}, declare as follows:", s["body"]),
        Paragraph(f"1. I am employed by {esc(folio.get('hotel_name') or '[HOTEL]')} as a {esc(witness.role)}. "
                  f"I have personal knowledge of the facts stated below and could competently testify to them if called as a witness.", s["body"]),
        Paragraph(f"2. Regarding guest {esc(folio.get('guest_name') or notice.get('cardholder_name') or '[GUEST]')}, Room {esc(folio.get('room_number') or '[ROOM]')}, "
                  f"stay {esc(folio.get('check_in') or '[IN]')} to {esc(folio.get('check_out') or '[OUT]')} (Case {esc(notice.get('case_id') or '[CASE]')}):", s["body"]),
    ]
    for i, line in enumerate(fact_lines, 3):
        flow.append(Paragraph(f"{i}. {esc(line)}", s["body"]))
    flow += [
        Paragraph(f"{len(fact_lines) + 3}. [Witness: add any personal observations — guest statements, ID presented, companions, condition of room at checkout — in your own words. Delete this instruction before signing.]", s["body"]),
        Paragraph("I declare under penalty of perjury under the laws of ______________________________ that the foregoing is true and correct. Executed on ____________________ at ______________________________. [Confirm language with counsel.]", s["body"]),
        *_sig_block(s, "Witness"),
        Spacer(1, 12),
        Paragraph(TEMPLATE_BANNER, s["banner"]),
    ]
    return _pdf(f"Witness Declaration — {witness.name}", flow)


def generate_demand_letter(notice: Dict[str, Any], folio: Dict[str, Any], damages: Dict[str, Any],
                           pay_by_date: str, debtor: Optional[Dict[str, str]] = None) -> bytes:
    """Pre-suit demand letter TEMPLATE with certified-mail block."""
    s = _styles()
    debtor = debtor or {}
    hotel = folio.get("hotel_name") or "[HOTEL NAME]"
    amount = damages.get("net_loss", 0.0)
    flow: List[Any] = [
        *_banner(s),
        Paragraph(esc(hotel.upper()), s["title"]),
        Paragraph(esc(folio.get("hotel_address") or "[HOTEL ADDRESS]"), s["small"]),
        Spacer(1, 12),
        Paragraph(f"Date: {date.today().strftime('%B %d, %Y')} &nbsp;&nbsp; VIA CERTIFIED MAIL, RETURN RECEIPT REQUESTED — Article #: ______________________________", s["body"]),
        Spacer(1, 8),
        Paragraph(f"To: {esc(debtor.get('name') or notice.get('cardholder_name') or '[CARDHOLDER NAME]')}<br/>{esc(debtor.get('address') or '[MAILING ADDRESS]')}", s["body"]),
        Spacer(1, 8),
        Paragraph(f"<b>Re: Demand for payment — ${amount:,.2f} {esc(damages.get('currency') or 'USD')} (folio {esc(folio.get('folio_number') or '[FOLIO]')}, dispute Case {esc(notice.get('case_id') or '[CASE]')}, ARN {esc(notice.get('arn') or '[ARN]')})</b>", s["body"]),
        Spacer(1, 8),
        Paragraph(f"Dear {esc(debtor.get('name') or notice.get('cardholder_name') or '[NAME]')}:", s["body"]),
        Paragraph(f"This letter demands payment of ${amount:,.2f}, representing lodging charges and related amounts for the stay of "
                  f"{esc(folio.get('check_in') or '[IN]')} to {esc(folio.get('check_out') or '[OUT]')} (Room {esc(folio.get('room_number') or '[ROOM]')}) "
                  f"that were charged to your card and subsequently charged back (folio total ${damages.get('folio_total', 0.0):,.2f}; "
                  f"amount debited ${damages.get('amount_disputed_debited', 0.0):,.2f}; fees ${damages.get('chargeback_fee', 0.0) + damages.get('arbitration_fees', 0.0):,.2f}; "
                  f"recovered ${damages.get('amount_recovered', 0.0):,.2f}). Supporting records are available for inspection on request.", s["body"]),
        Paragraph(f"Please remit payment by <b>{esc(pay_by_date)}</b> to {esc(hotel)} at the address above, referencing the folio number. "
                  f"If payment (or a written dispute of this demand with supporting facts) is not received by that date, the hotel may pursue "
                  f"available remedies, which may include filing in small claims court, without further notice. [Confirm pre-suit demand requirements and wording with counsel.]", s["body"]),
        Paragraph("This letter is an attempt to collect a debt. [Include any debt-collection disclosures required in your jurisdiction, if applicable.]", s["body"]),
        *_sig_block(s, "Authorized Representative"),
        Spacer(1, 12),
        Paragraph(TEMPLATE_BANNER, s["banner"]),
    ]
    return _pdf(f"Demand Letter — {notice.get('case_id') or 'case'}", flow)


# ---------------------------------------------------------------------------
# Fraud report pack (data, rendered as text/JSON for filing)
# ---------------------------------------------------------------------------

def build_fraud_report(notice: Dict[str, Any], folio: Dict[str, Any], damages: Dict[str, Any],
                       chronology_events: List[Dict[str, Any]],
                       suspect: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
    """Who/What/When/Where/How-much incident summary for police / FBI IC3."""
    suspect = suspect or {}
    return {
        "report_type": "Hotel card fraud incident summary (for police report / FBI IC3)",
        "who": {
            "registered_guest": folio.get("guest_name"),
            "cardholder_on_notice": notice.get("cardholder_name"),
            "suspect_description": suspect.get("description"),
            "id_presented": suspect.get("id_presented"),
            "id_indicators": suspect.get("id_indicators"),
            "companions_vehicle": suspect.get("companions_vehicle"),
        },
        "what": {
            "summary": notice.get("claim_statement"),
            "reason_code": f"{notice.get('card_network') or ''} {notice.get('reason_code') or ''}".strip(),
            "folio_number": folio.get("folio_number"),
            "room": folio.get("room_number"),
            "card_last_4": folio.get("card_last_4") or notice.get("card_last_4"),
        },
        "when": {
            "booking_date": folio.get("booking_date"),
            "check_in": folio.get("check_in"), "check_in_time": folio.get("check_in_time"),
            "check_out": folio.get("check_out"),
            "transaction_date": notice.get("transaction_date"),
            "dispute_date": notice.get("dispute_date"),
            "timeline": [f"{e.get('date_label')}: {e.get('event')}" for e in chronology_events],
        },
        "where": {
            "hotel": folio.get("hotel_name"), "address": folio.get("hotel_address"),
            "booking_channel": folio.get("booking_source") or folio.get("booking_channel"),
        },
        "how_much": damages,
        "preservation_checklist": [
            "CCTV: export and preserve lobby/front-desk footage NOW (systems overwrite in days) — record camera IDs and time range.",
            "Door-lock audit export with hash (already in custody manifest).",
            "Registration card original secured (note its physical location).",
            "ID copy retained only where lawful; note fake-ID indicators.",
            "All bank notices, submissions, and outcomes preserved (Phases 5–7 records).",
        ],
        "disclaimer": "Incident summary prepared by the merchant for law-enforcement filing. Verify facts before submitting to police/IC3.",
    }


# ---------------------------------------------------------------------------
# Court bundle + pre-filing validation
# ---------------------------------------------------------------------------

def validate_court_bundle(evidence_items: List[Dict[str, Any]], witnesses: List[Dict[str, Any]],
                          filings: List[Dict[str, Any]], damages: Dict[str, Any]) -> Dict[str, Any]:
    checks: List[Dict[str, Any]] = []

    def check(rule: str, ok: bool, detail: str) -> None:
        checks.append({"rule": rule, "ok": bool(ok), "detail": detail})

    by_type = {i.get("doc_type"): i for i in evidence_items}
    reg = by_type.get("signed_registration_card") or {}
    check("reg_card_provenance", bool(reg.get("original_type")),
          f"Registration card provenance recorded ({reg.get('original_type')})" if reg.get("original_type")
          else "Record whether the reg card is a wet-ink original, copy, or e-signature (Tab 2 provenance)")
    if reg.get("original_type") in ("copy", "scan"):
        check("original_location", bool(reg.get("original_location")),
              "Original location noted" if reg.get("original_location") else "Copy/scan on file — record where the ORIGINAL is kept")
    keycard = by_type.get("keycard_lock_audit") or {}
    check("log_extraction_statement", bool(keycard.get("extracted_by") and keycard.get("extraction_method")),
          "Keycard extraction statement complete" if (keycard.get("extracted_by") and keycard.get("extraction_method"))
          else "Record who extracted the door-lock log, when, and how (system + filter)")
    check("witness_assigned", len(witnesses) > 0,
          f"{len(witnesses)} witness(es) registered" if witnesses else "Register the front-desk agent witness (Tab 6)")
    demand = next((f for f in filings if f.get("kind") == "demand_letter" and f.get("status") in ("sent", "filed", "received")), None)
    check("demand_sent", demand is not None,
          f"Demand letter sent {demand.get('sent_at')}" if demand else "Send the demand letter (certified mail) before filing, where required")
    check("damages_computed", damages.get("net_loss", 0) > 0,
          f"Net loss computed: ${damages.get('net_loss', 0):,.2f}" if damages.get("net_loss", 0) > 0 else "No positive net loss computed — confirm the amount in controversy")
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def build_court_bundle(notice: Dict[str, Any], folio: Dict[str, Any],
                       packet_bytes: bytes, exhibit_files: Dict[str, bytes],
                       legal_docs: Dict[str, bytes], manifest: Dict[str, Any],
                       damages: Dict[str, Any], fraud_report: Optional[Dict[str, Any]] = None) -> Tuple[bytes, Dict[str, Any]]:
    """ZIP: packet + affidavit/declarations/demand + exhibits + damages + manifest."""
    case_id = _safe(str(notice.get("case_id") or "case"))
    buffer = io.BytesIO()
    contents: List[str] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        if packet_bytes:
            zf.writestr("00_bank_packet.pdf", packet_bytes)
            contents.append("00_bank_packet.pdf")
        for name, data in sorted(legal_docs.items()):
            arc = f"legal/{_safe(name)}"
            zf.writestr(arc, data)
            contents.append(arc)
        for letter in sorted(exhibit_files.keys()):
            arc = f"exhibits/Exhibit_{letter}"
            zf.writestr(arc, exhibit_files[letter])
            contents.append(arc)
        zf.writestr("damages_statement.json", json.dumps(damages, indent=2, default=str))
        contents.append("damages_statement.json")
        zf.writestr("custody_manifest.json", json.dumps(manifest, indent=2, default=str))
        contents.append("custody_manifest.json")
        if fraud_report:
            zf.writestr("fraud_report.json", json.dumps(fraud_report, indent=2, default=str))
            contents.append("fraud_report.json")
        zf.writestr("FILING_CHECKLIST.txt",
                    "COURT / LEGAL TRACK FILING CHECKLIST (jurisdiction-neutral — confirm locally)\n"
                    "1. Business Records Affidavit signed AND notarized (template in legal/).\n"
                    "2. Witness declaration(s) signed by the witness(es).\n"
                    "3. Original registration card located (or e-sig audit trail attached).\n"
                    "4. Demand letter sent via certified mail; wait period elapsed (if required).\n"
                    "5. Damages statement reviewed against folio/debit/fee records.\n"
                    "6. Filing fees and small-claims limit confirmed for your venue.\n"
                    "7. For fraud: police/IC3 report filed; report number recorded in FolioShield.\n"
                    f"\n{TEMPLATE_BANNER}\n")
        contents.append("FILING_CHECKLIST.txt")
    zip_bytes = buffer.getvalue()
    return zip_bytes, {
        "bundle_sha256": AuditLogger.calculate_sha256(zip_bytes),
        "size_bytes": len(zip_bytes),
        "contents": contents,
        "filename": f"{case_id}_CourtBundle.zip",
    }


class LegalRegistry:
    """Witness + filing persistence (JSONL per case, alongside submissions)."""

    def __init__(self, root: str = "data/submissions"):
        self.root = root
        os.makedirs(root, exist_ok=True)

    def _path(self, case_id: str) -> str:
        return os.path.join(self.root, f"{_safe(case_id or 'unknown')}.jsonl")

    def _append(self, case_id: str, kind: str, record: Dict[str, Any]) -> None:
        entry = {"kind": kind, "recorded_at": datetime.now(timezone.utc).isoformat(), "record": record}
        append_jsonl(self._path(case_id), entry)

    def load(self, case_id: str) -> Dict[str, Any]:
        out: Dict[str, Any] = {"witnesses": [], "filings": [], "corrupt_lines": []}
        entries, corrupt = read_jsonl(self._path(case_id))
        for entry in entries:
            if entry.get("kind") == "witness":
                out["witnesses"].append(entry.get("record") or {})
            elif entry.get("kind") == "legal_filing":
                out["filings"].append(entry.get("record") or {})
        out["corrupt_lines"] = corrupt
        return out

    def add_witness(self, case_id: str, witness: WitnessRecord) -> WitnessRecord:
        self._append(case_id, "witness", witness.to_dict())
        return witness

    def record_filing(self, case_id: str, filing: LegalFilingRecord) -> LegalFilingRecord:
        self._append(case_id, "legal_filing", filing.to_dict())
        return filing
