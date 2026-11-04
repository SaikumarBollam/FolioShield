"""
Generate a complete commercial-style evidence library for manual testing.

Creates test_artifacts/manual_testing/00_complete_evidence_library/ with one
upload-ready file for every evidence type exposed in the FolioShield UI
(20 types across Front Desk, Payment Authorization, Booking & Terms,
Incidentals, Financial Resolution, and Court/Legal groups).

All documents are synthetic hospitality business records aligned to the
primary reference case (Visa 10.4, Jonathan C. Davis, Room 412) so they can
be uploaded together for a full end-to-end exercise. They are test fixtures,
not real guest, payment, identity, or legal records.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from core.rules import SUPPORTING_DOC_GROUPS, SUPPORTING_DOC_TYPES

OUT = ROOT / "test_artifacts" / "manual_testing" / "00_complete_evidence_library"

HOTEL = "Grand Horizon Resort & Suites"
ADDRESS = "100 Ocean Avenue, Miami Beach, FL 33139"
GUEST = "Jonathan C. Davis"
CASE_ID = "V-DISP-89214-X"
ARN = "24492156291002918274019"
FOLIO = "FOL-2026-9812"
CONFIRMATION = "GH-884120"
ROOM = "412"
CHECK_IN = "2026-10-10"
CHECK_OUT = "2026-10-13"
EMAIL = "jonathan.davis@example.com"

# doc_type -> (filename, format, title, body lines / structured content)
DOC_SPECS: dict[str, dict[str, Any]] = {
    "signed_registration_card": {
        "file": "01_signed_registration_card.png", "kind": "image",
        "title": "Guest Registration Card — Signed",
        "lines": [
            f"Property: {HOTEL}",
            f"Guest: {GUEST}    Room: {ROOM}",
            f"Arrival: {CHECK_IN} 3:15 PM    Departure: {CHECK_OUT}",
            "Rate acknowledged: $320.00 per night plus taxes and resort fee.",
            "Incidental and damage charges authorized to the card on file.",
            "Guest signature on file (synthetic mark for testing).",
        ],
        "details": {"signature_type": "wet", "check_in_time": "3:15 PM"},
        "ui_details": "Court provenance: Original type = wet_original; location = Front Desk Records Cabinet.",
    },
    "id_verification_log": {
        "file": "02_id_verification_log.pdf", "kind": "pdf",
        "title": "Front Desk Identification Verification Log",
        "rows": [
            ("Guest", GUEST), ("Room / Folio", f"{ROOM} / {FOLIO}"),
            ("ID type presented", "Government-issued photo identification (driver license)"),
            ("Name match", "ID name matched registered guest name"),
            ("Verified by", "Front Desk Agent — J. Morales"),
            ("Verified at", "2026-10-10 3:15 PM"),
            ("Result", "Verified — guest checked in"),
            ("Handling note", "Verification log retained; ID copy handling follows property policy and local law."),
        ],
        "details": {"id_type": "Driver license", "verified_at": "2026-10-10 15:15"},
        "ui_details": "Court provenance: Original type = system_export; extracted by Front Desk Supervisor.",
    },
    "keycard_lock_audit": {
        "file": "03_keycard_lock_audit.csv", "kind": "lockcsv",
        "title": "Electronic Lock Audit Trail",
        "details": {"entries": 14, "first_entry": "2026-10-10 15:22", "last_entry": "2026-10-13 10:48"},
        "ui_details": "Probative details: First entry 2026-10-10 15:22; Last entry 2026-10-13 10:48. Provenance: system Onity HT28 export, Room 412 + stay-date filter.",
    },
    "guest_service_log": {
        "file": "04_guest_service_log.pdf", "kind": "pdf",
        "title": "Guest Service & Housekeeping Log Extract",
        "rows": [
            ("Guest / Room", f"{GUEST} / Room {ROOM}"),
            ("Stay", f"{CHECK_IN} to {CHECK_OUT}"),
            ("2026-10-10 18:05", "Extra towels requested — delivered 18:20. Closed."),
            ("2026-10-11 09:40", "Housekeeping service completed. No issues reported."),
            ("2026-10-12 21:15", "Spa cabana billing inquiry — explained; guest accepted charge."),
            ("Unresolved complaints at checkout", "0"),
            ("Checkout dispute noted", "None"),
        ],
        "details": {"unresolved_complaints": 0},
        "ui_details": "Probative details: Unresolved complaints = 0.",
    },
    "emv_terminal_receipt": {
        "file": "05_emv_terminal_receipt.pdf", "kind": "pdf",
        "title": "EMV Terminal Receipt — Card Present Authorization",
        "rows": [
            ("Merchant", f"{HOTEL} ({ADDRESS})"),
            ("Terminal", "Ingenico Lane/3000 — TID T-04"),
            ("Date / Time", "2026-10-10 15:17"),
            ("Card", "Visa ************4821"),
            ("Entry mode", "Chip (EMV contact)"),
            ("Authorization code", "AP98231"),
            ("Authorized amount", "$1,280.50"),
            ("Result", "Approved — chip read completed; cryptogram validated by issuer host"),
            ("Folio / Room", f"{FOLIO} / Room {ROOM}"),
        ],
        "details": {"auth_code": "AP98231", "entry_mode": "chip", "terminal_id": "T-04"},
        "ui_details": "Folio fields should show Auth Code AP98231 and Entry Mode chip.",
    },
    "avs_cvv_result": {
        "file": "06_avs_cvv_authorization_result.txt", "kind": "text",
        "title": "Payment Gateway Authorization Result",
        "lines": [
            f"Merchant: {HOTEL}",
            f"Confirmation: {CONFIRMATION}    Folio: {FOLIO}",
            "Transaction type: E-commerce / card-not-present booking authorization",
            "Card: Visa ************4821",
            "Authorization code: AP98231",
            "AVS result: Y — full match (street address and ZIP match)",
            "CVV result: Match",
            "Authorized at: 2026-09-28 14:01 UTC",
            "Outcome: Approved",
        ],
        "details": {"avs_result": "Y", "cvv_result": "Match"},
        "ui_details": "Probative details: AVS result = Y; CVV result = Match.",
    },
    "three_ds_authentication": {
        "file": "07_3ds_authentication_record.txt", "kind": "text",
        "title": "3-D Secure Authentication Record",
        "lines": [
            f"Merchant: {HOTEL}",
            f"Confirmation: {CONFIRMATION}",
            "Channel: Hotel website booking engine",
            "Card: Visa ************4821",
            "3-D Secure status: Authenticated",
            "ECI: 05",
            "CAVV: Present (issuer authentication value on file with gateway)",
            "Authenticated at: 2026-09-28 14:01 UTC",
            "Outcome: Authentication successful; authorization proceeded as AP98231.",
        ],
        "details": {"three_ds_status": "authenticated", "eci": "05"},
        "ui_details": "Folio field: 3-D Secure status / ECI = authenticated 05.",
    },
    "booking_confirmation": {
        "file": "08_booking_confirmation.eml", "kind": "eml",
        "title": "Booking Confirmation Email",
        "details": {"recipient": EMAIL, "sent_at": "2026-09-28 14:02 UTC"},
        "ui_details": "Probative details: Recipient = jonathan.davis@example.com; Sent at = 2026-09-28 14:02 UTC.",
    },
    "cancellation_policy_acceptance": {
        "file": "09_cancellation_policy_acceptance.pdf", "kind": "pdf",
        "title": "Booking Terms & Cancellation Policy Acceptance",
        "rows": [
            ("Confirmation", CONFIRMATION),
            ("Guest", GUEST),
            ("Accepted at", "2026-09-28 14:01 UTC"),
            ("Booking channel", "Hotel Website"),
            ("Rate plan", "Best Available Rate"),
            ("Policy shown", "Free cancellation until 48 hours before arrival. After that time, the first night plus tax is charged. No-show reservations are charged the first night plus tax."),
            ("Acceptance method", "Guest selected 'Agree and Complete Booking' after policy display"),
            ("Terms version", "CANCEL-POL-2026.09"),
        ],
        "details": {"accepted_at": "2026-09-28 14:01 UTC", "policy_text": "Free cancellation until 48 hours before arrival; thereafter first night plus tax."},
        "ui_details": "Probative details: Accepted at = 2026-09-28 14:01 UTC. Paste the policy text into Tab 2 policy box.",
    },
    "guest_communication_log": {
        "file": "10_guest_communication_log.pdf", "kind": "pdf",
        "title": "Guest Communication Log",
        "rows": [
            ("2026-09-28 14:02", "Booking confirmation sent to guest email."),
            ("2026-10-09 16:40", "Pre-arrival message sent with check-in and parking information."),
            ("2026-10-11 20:12", "Guest asked about spa cabana hours; concierge responded."),
            ("2026-10-13 10:55", "Checkout folio emailed to guest."),
            ("Complaints / refund requests", "None recorded before the dispute notice."),
            ("Prepared by", "Reservations / Front Office"),
        ],
        "details": {"channels": ["email"], "unresolved_dispute_before_chargeback": False},
        "ui_details": "No required numeric detail. Confirm the log shows no pre-dispute refund request for this case.",
    },
    "pos_signed_slips": {
        "file": "11_pos_signed_slips.pdf", "kind": "pdf",
        "title": "Point-of-Sale Signed Charges",
        "rows": [
            ("Slip POS-9812", "Ocean Grill — 2026-10-11 — Room 412 — $87.70 — guest signature on file"),
            ("Slip SPA-331", "Spa Cabana — 2026-10-12 — Room 412 — $53.60 — guest signature on file"),
            ("Folio posting", "Charges posted to Folio FOL-2026-9812 under the same references"),
            ("Prepared by", "Food & Beverage / Spa POS supervisors"),
        ],
        "details": {"slips": [{"reference": "POS-9812", "amount": 87.70}, {"reference": "SPA-331", "amount": 53.60}]},
        "ui_details": "Probative details UI accepts one slip at a time: enter POS-9812 / 87.70 first. The PDF lists both slips; full multi-slip detail is in library_index.json.",
    },
    "wifi_usage_log": {
        "file": "12_wifi_usage_log.csv", "kind": "wificsv",
        "title": "Guest WiFi Usage Log",
        "details": {"first_entry": "2026-10-10 15:31", "last_entry": "2026-10-13 10:20"},
        "ui_details": "Probative details: First seen 2026-10-10 15:31; Last seen 2026-10-13 10:20.",
    },
    "incident_damage_evidence": {
        "file": "13_incident_damage_evidence.pdf", "kind": "pdf",
        "title": "Incident & Damage Evidence Summary",
        "rows": [
            ("Reference case note", "Included for complete-library testing. The primary Visa 10.4 folio does not contain a damage charge."),
            ("How to use", "Use with Mastercard 4859 damage scenario or attach here only when testing the upload slot."),
            ("Report reference", "INC-2214 (damage scenario)"),
            ("Evidence described", "Housekeeping inspection notes, timestamped photographs, remediation invoice, signed registration damage clause"),
            ("Prepared by", "Housekeeping / Front Office Manager"),
        ],
        "details": {"report_id": "INC-2214", "photos": 6},
        "ui_details": "Use primarily with the Mastercard 4859 scenario. Do not treat this as a disputed charge on the Visa 10.4 folio.",
    },
    "refund_credit_receipt": {
        "file": "14_refund_credit_receipt.pdf", "kind": "pdf",
        "title": "Processor Refund / Credit Receipt",
        "rows": [
            ("Reference case note", "Included for complete-library testing. No refund was issued on the primary Visa 10.4 stay."),
            ("How to use", "Use with Visa 13.6 refund scenario (Tomas Herrera, $412.00, RF-884120-6610)."),
            ("Processor", "Payment processor portal"),
            ("Refund status", "Credit issued to original card"),
            ("Receipt purpose", "Proves the cardholder was already credited when a refund has been issued"),
        ],
        "details": {"scenario_amount": 412.00, "scenario_reference": "RF-884120-6610"},
        "ui_details": "Use primarily with Visa 13.6. In that scenario enter Refund amount = 412.00 and reference RF-884120-6610.",
    },
    "clickwrap_record": {
        "file": "15_booking_clickwrap_record.txt", "kind": "text",
        "title": "Booking Clickwrap Record",
        "lines": [
            f"Property: {HOTEL}",
            f"Confirmation: {CONFIRMATION}",
            f"Guest: {GUEST}",
            "Booking channel: Hotel Website",
            "Guest IP address: 203.0.113.42 (synthetic test address)",
            "User agent: Mozilla/5.0 (synthetic test browser)",
            "Terms version: CANCEL-POL-2026.09",
            "Terms hash (SHA-256): 9f2c4a7b1d8e4f0a9c3b5d7e2a4f6b8c0d1e3f5a7b9c2d4e6f8a0b1c3d5e7f90",
            "Acceptance timestamp: 2026-09-28 14:01 UTC",
            "Action: Guest selected 'Agree and Complete Booking' after rate, tax, and cancellation terms were displayed.",
        ],
        "details": {"ip": "203.0.113.42", "accepted_at": "2026-09-28 14:01 UTC", "terms_version": "CANCEL-POL-2026.09"},
        "ui_details": "Upload in Court/Legal group. Use with the affidavit/clickwrap review in Tab 5.",
    },
    "cctv_footage": {
        "file": "16_cctv_footage_export.png", "kind": "image",
        "title": "CCTV Export — Front Desk / Lobby",
        "lines": [
            "Camera: LOBBY-CAM-02 (synthetic still frame)",
            "Timestamp: 2026-10-10 15:14",
            f"Location: Front desk, {HOTEL}",
            "Event: Guest check-in interaction at front desk",
            "Preservation note: Export immediately; CCTV systems overwrite on retention cycle.",
        ],
        "details": {"camera": "LOBBY-CAM-02", "timestamp": "2026-10-10 15:14"},
        "ui_details": "Upload as an image exhibit. In a real case, preserve the original video export and note camera/time range.",
    },
    "suspect_id_copy": {
        "file": "17_suspect_id_copy.png", "kind": "image",
        "title": "Presented Identification — Test Image",
        "lines": [
            "SYNTHETIC TEST IMAGE — not a real identity document.",
            f"Name shown for testing: {GUEST}",
            "Document type: Government photo ID (test representation)",
            "Purpose: Fraud-report workflow testing only",
            "Handling: Store real ID copies only where lawful and required.",
        ],
        "details": {"id_type": "Driver license (synthetic)"},
        "ui_details": "Use only for workflow testing. Real ID copies require lawful handling and restricted access.",
    },
    "witness_declaration": {
        "file": "18_witness_declaration.pdf", "kind": "pdf",
        "title": "Witness Declaration — Front Desk Agent (Template)",
        "rows": [
            ("Witness", "J. Morales, Front Desk Agent"),
            ("Property", HOTEL),
            ("Guest / Room", f"{GUEST} / Room {ROOM}"),
            ("Statement", "I checked in the guest on 2026-10-10 at approximately 3:15 PM, verified government photo identification, issued room keys, and explained incidental authorization."),
            ("Status", "TEMPLATE — witness must review, complete, and sign. FolioShield also generates this template in Tab 5."),
        ],
        "details": {"witness": "J. Morales", "linked_events": ["check_in", "id_verified", "key_issued"]},
        "ui_details": "Prefer generating the declaration in Tab 5 after registering the witness. This file tests the upload slot.",
    },
    "demand_letter": {
        "file": "19_demand_letter.pdf", "kind": "pdf",
        "title": "Pre-Suit Demand Letter (Template)",
        "rows": [
            ("From", f"{HOTEL}, {ADDRESS}"),
            ("To", f"{GUEST} (address on file)"),
            ("Subject", f"Demand for payment — Folio {FOLIO}, dispute Case {CASE_ID}"),
            ("Amount demanded", "$1,280.50 USD (adjust to verified net loss before use)"),
            ("Status", "TEMPLATE — review by counsel; send by certified mail where required and record the article number."),
        ],
        "details": {"kind": "demand_letter_template"},
        "ui_details": "Prefer generating the demand letter in Tab 5 with the computed net loss and pay-by date.",
    },
    "police_report": {
        "file": "20_police_ic3_report_record.pdf", "kind": "pdf",
        "title": "Law Enforcement Report Filing Record",
        "rows": [
            ("Report type", "Police report / FBI IC3 filing record (test)"),
            ("Agency", "[Agency name to be completed at filing]"),
            ("Report number", "[Record after filing]"),
            ("Incident", f"Alleged unauthorized lodging transaction — Case {CASE_ID}, ARN {ARN}"),
            ("Amount", "$1,280.50 USD"),
            ("Status", "Filing record template — complete after an actual report is filed."),
        ],
        "details": {"kind": "filing_record_template"},
        "ui_details": "Record the actual agency and report number in Tab 5 Filings Tracker after filing.",
    },
}


def styles():
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("LibH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#1E3A8A")),
        "body": ParagraphStyle("LibBody", parent=base["Normal"], fontName="Helvetica", fontSize=9, leading=12),
        "small": ParagraphStyle("LibSmall", parent=base["Normal"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=colors.HexColor("#475569")),
        "bold": ParagraphStyle("LibBold", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=12),
    }


def styled_table(rows, widths):
    table = Table(rows, colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def build_pdf(path: Path, spec: dict[str, Any]) -> None:
    s = styles()
    story = [
        Paragraph(spec["title"].upper(), s["h1"]),
        Paragraph(f"{HOTEL} · {ADDRESS}", s["body"]),
        Paragraph("Commercial hospitality business record — synthetic test fixture for FolioShield workflow testing.", s["small"]),
        Spacer(1, 12),
    ]
    rows = [[Paragraph("<b>Item</b>", s["bold"]), Paragraph("<b>Record</b>", s["bold"])]]
    rows.append([Paragraph("Guest / Folio", s["body"]), Paragraph(f"{GUEST} / {FOLIO} (Room {ROOM})", s["body"])])
    rows.append([Paragraph("Dispute Case", s["body"]), Paragraph(f"{CASE_ID} · ARN {ARN}", s["body"])])
    for label, value in spec.get("rows", []):
        rows.append([Paragraph(str(label), s["body"]), Paragraph(str(value), s["body"])])
    story.append(styled_table(rows, [150, 360]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Prepared for chargeback evidence review. Verify all facts against source systems before submission.", s["small"]))
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48,
                            title=spec["title"], author="FolioShield Test Fixtures")
    doc.build(story)


def build_text(path: Path, spec: dict[str, Any]) -> None:
    lines = [spec["title"], "=" * len(spec["title"]), f"{HOTEL} · {ADDRESS}",
             "Commercial hospitality business record — synthetic test fixture.", "",
             f"Guest: {GUEST}", f"Folio: {FOLIO}  Room: {ROOM}", f"Case: {CASE_ID}  ARN: {ARN}", ""]
    lines.extend(spec.get("lines", []))
    lines.append("\nVerify all facts against source systems before submission.")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_eml(path: Path, spec: dict[str, Any]) -> None:
    content = f"""From: reservations@grandhorizonresort.example
To: {EMAIL}
Subject: Booking Confirmation {CONFIRMATION} - {HOTEL}
Date: Mon, 28 Sep 2026 14:02:00 +0000
Content-Type: text/plain; charset=utf-8

Dear {GUEST},

Thank you for booking with {HOTEL}.

Confirmation number: {CONFIRMATION}
Property: {HOTEL}, {ADDRESS}
Arrival: {CHECK_IN}
Departure: {CHECK_OUT}
Room: {ROOM}
Rate plan: Best Available Rate
Nightly rate: $320.00 plus taxes and resort fee

Cancellation policy: Free cancellation until 48 hours before arrival. After that time, the first night plus tax is charged. No-show reservations are charged the first night plus tax.

Your reservation was guaranteed with the card ending in 4821. Authorization and booking terms were presented before booking completion.

We look forward to welcoming you.

Grand Horizon Resort & Suites
Reservations Department

---
Synthetic test message generated for FolioShield workflow testing.
"""
    path.write_text(content, encoding="utf-8")


def build_image(path: Path, spec: dict[str, Any]) -> None:
    image = Image.new("RGB", (1200, 760), "white")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("arial.ttf", 32)
        body_font = ImageFont.truetype("arial.ttf", 23)
        small_font = ImageFont.truetype("arial.ttf", 18)
    except OSError:
        title_font = body_font = small_font = ImageFont.load_default()
    draw.rectangle((25, 25, 1175, 735), outline=(30, 58, 138), width=4)
    draw.text((55, 50), spec["title"], fill=(30, 58, 138), font=title_font)
    y = 130
    lines = [f"{HOTEL}", f"Guest: {GUEST}   Room: {ROOM}   Folio: {FOLIO}", f"Stay: {CHECK_IN} to {CHECK_OUT}", ""]
    lines.extend(spec.get("lines", []))
    for line in lines:
        draw.text((55, y), str(line), fill=(17, 24, 39), font=body_font)
        y += 40
    # Synthetic signature/verification mark (not a real signature).
    points = [(80, 560), (180, 510), (260, 585), (350, 495), (460, 570), (560, 515), (700, 560)]
    draw.line(points, fill=(17, 24, 39), width=4)
    draw.line((70, 605, 760, 605), fill=(100, 116, 139), width=2)
    draw.text((55, 640), "Synthetic test image — verify visually in FolioShield.", fill=(71, 85, 105), font=small_font)
    image.save(path)


def build_lock_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "room", "event_type", "key_id", "source_system"])
        entries = [
            ("2026-10-10 15:22", ROOM, "first_entry", "KEY-884120-A", "Onity HT28"),
            ("2026-10-10 19:04", ROOM, "entry", "KEY-884120-A", "Onity HT28"),
            ("2026-10-11 08:12", ROOM, "entry", "KEY-884120-A", "Onity HT28"),
            ("2026-10-11 22:31", ROOM, "entry", "KEY-884120-B", "Onity HT28"),
            ("2026-10-12 09:18", ROOM, "entry", "KEY-884120-A", "Onity HT28"),
            ("2026-10-13 10:48", ROOM, "last_entry", "KEY-884120-A", "Onity HT28"),
        ]
        writer.writerows(entries)


def build_wifi_csv(path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["timestamp", "room", "network", "device_label", "event"])
        writer.writerows([
            ("2026-10-10 15:31", ROOM, "GrandHorizon-Guest", "Guest device (synthetic)", "first_seen"),
            ("2026-10-11 20:44", ROOM, "GrandHorizon-Guest", "Guest device (synthetic)", "session"),
            ("2026-10-13 10:20", ROOM, "GrandHorizon-Guest", "Guest device (synthetic)", "last_seen"),
        ])


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    group_by_type: dict[str, str] = {}
    for group in SUPPORTING_DOC_GROUPS.values():
        for key in group["keys"]:
            group_by_type[key] = group["label"]

    for doc_type in SUPPORTING_DOC_TYPES:
        spec = DOC_SPECS[doc_type]
        path = OUT / spec["file"]
        kind = spec["kind"]
        if kind == "pdf":
            build_pdf(path, spec)
        elif kind == "text":
            build_text(path, spec)
        elif kind == "eml":
            build_eml(path, spec)
        elif kind == "image":
            build_image(path, spec)
        elif kind == "lockcsv":
            build_lock_csv(path)
        elif kind == "wificsv":
            build_wifi_csv(path)
        else:
            build_text(path, spec)
        index.append({
            "doc_type": doc_type,
            "ui_group": group_by_type.get(doc_type),
            "ui_label": SUPPORTING_DOC_TYPES[doc_type],
            "file": spec["file"],
            "details_in_file": spec.get("details") or {},
            "enter_in_ui": spec.get("ui_details"),
            "reference_case": CASE_ID,
        })

    (OUT / "library_index.json").write_text(json.dumps(index, indent=2, default=str), encoding="utf-8")

    md: list[str] = [
        "# Complete Evidence Library — Commercial Hospitality Test Records",
        "",
        "One upload-ready file for **every evidence type shown in FolioShield Tab 2**, aligned to the primary reference case so the full evidence workspace can be exercised end to end.",
        "",
        f"**Reference case:** Visa 10.4 · Case {CASE_ID} · {GUEST} · Room {ROOM} · Folio {FOLIO} · {CHECK_IN} to {CHECK_OUT} · {HOTEL}.",
        "",
        "> These are synthetic hospitality business records for software testing. They are not real guest, identity, payment, court, or law-enforcement documents. Verify every fact against source systems in a real case.",
        "",
        "## How to use",
        "",
        "1. Start FolioShield and choose **New Dispute Case** (or open the Visa 10.4 reference case).",
        "2. Upload the Scenario 1 notice and folio from `../01_visa_10_4_false_fraud/`.",
        "3. In **Tab 2 → Compelling Evidence Collection**, upload each file below into the matching slot.",
        "4. Open **Probative details** / **Court provenance** under a slot when the 'Enter in UI' column gives values to record.",
        "5. Review the Evidence Coverage Status, draft and approve in Tab 3, then compile Executive or Complete packet in Tab 4.",
        "",
        "## Complete mapping (all 20 evidence types)",
        "",
        "| # | UI Group | Evidence Slot (as shown in UI) | File to Upload | Enter in UI |",
        "|---|---|---|---|---|",
    ]
    for i, item in enumerate(index, 1):
        md.append(f"| {i} | {item['ui_group']} | {item['ui_label']} | `{item['file']}` | {item['enter_in_ui'] or '—'} |")
    md += [
        "",
        "## Scenario-specific evidence still matters",
        "",
        "This library proves every upload slot works. For realistic case testing, prefer each scenario folder's own `evidence/` files because amounts, names, dates, and references match that dispute. In particular:",
        "",
        "- **Amex C08:** use Scenario 3 slips POS-4102 ($185.00) and VAL-778 ($60.00) for exact-amount binding.",
        "- **Visa 13.6:** use Scenario 5 refund receipt data ($412.00, RF-884120-6610).",
        "- **Mastercard 4859:** use Scenario 6 incident evidence (INC-2214).",
        "- **Court/Legal slots:** prefer generating the affidavit, declaration, and demand letter in Tab 5 for the active case; the library files test the upload slots.",
        "",
        "## File formats",
        "",
        "PDF business records, PNG image records, CSV lock/WiFi logs, TXT gateway records, and an EML booking confirmation are included so every accepted upload type in the UI can be exercised.",
        "",
    ]
    (OUT / "README.md").write_text("\n".join(md), encoding="utf-8")
    print(f"Generated complete evidence library in {OUT} ({len(index)} evidence types)")


if __name__ == "__main__":
    main()
