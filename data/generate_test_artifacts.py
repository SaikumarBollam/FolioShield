"""
Generate upload-ready manual test artifacts for every built-in scenario.

Creates test_artifacts/manual_testing/<scenario>/ containing:
- 01_bank_dispute_notice.pdf
- 02_guest_folio.pdf
- 02_guest_folio.csv
- evidence/ files matching the scenario's supporting-document metadata
- scenario.json (source data + expected checks)
- TESTING_GUIDE.md (per-scenario click path and expected results)

The generated documents are synthetic test fixtures only.
"""

from __future__ import annotations

import csv
import json
import os
import re
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

from core.audit_logger import AuditLogger
from data.sample_scenarios import SCENARIOS

OUT_ROOT = ROOT / "test_artifacts" / "manual_testing"

SCENARIO_GUIDE: dict[str, dict[str, Any]] = {
    "visa_fraud_10_4": {
        "folder": "01_visa_10_4_false_fraud",
        "purpose": "Full occupied-stay fraud defense with a complete physical-presence chain.",
        "steps": [
            "Use Custom Document Upload, then upload 01_bank_dispute_notice.pdf and either folio PDF or CSV.",
            "Open Review & Correct Collected Fields and verify claim statement, 23-digit ARN, MID, AVS, guest email, and check-in time.",
            "In Tab 2, confirm the mathematical proofs and upload the files from evidence/ into their matching evidence slots.",
            "For POS Signed Slips, save slip reference POS-9812 and amount 87.70 in Probative details.",
            "Draft and approve the rebuttal, compile the packet, choose Chase, build the submission bundle, and download it.",
        ],
        "expected": [
            "Completeness should be strong (scenario benchmark: 96%).",
            "Folio footing, amount, settlement, card, name, and rate proofs should pass.",
            "Chronology should include 3:15 PM check-in and 15:22 first keycard entry.",
            "Packet remains exactly 3 pages and the ZIP contains the packet, exhibits, manifest, and instructions.",
        ],
    },
    "mc_cancellation_4853": {
        "folder": "02_mastercard_4853_late_cancellation",
        "purpose": "Cancelled advance-purchase reservation where timing and policy acceptance decide the case.",
        "steps": [
            "Upload the Mastercard notice and folio in Custom Document Upload mode.",
            "Verify stay_status=cancelled, rate plan, cancellation timestamp, and cancellation number CX-55210.",
            "Upload the evidence files; record policy accepted_at and exact policy text if editing details.",
            "Draft, approve, compile, and build a Fiserv submission bundle.",
        ],
        "expected": [
            "Occupancy-only requirements should not be treated as missing for a cancelled stay.",
            "Cancellation/policy evidence is central; registration/keycard absence is expected.",
            "The rebuttal summary should use the cancelled-reservation variant, not claim services were occupied/rendered.",
        ],
    },
    "amex_partial_c08": {
        "folder": "03_amex_c08_partial_incidentals",
        "purpose": "Partial dispute where exact-amount signed POS slips decide the contested lines.",
        "steps": [
            "Upload the Amex notice and folio.",
            "Confirm disputed lines are Dining $185.00 (POS-4102) and Valet $60.00 (VAL-778).",
            "Upload pos_signed_slips.pdf; in Probative details, first test only POS-4102/$185.00 and observe partial coverage.",
            "Then use the generated scenario data or add the second slip reference/amount through the SDK/test data; the supplied evidence text lists both slips.",
            "Draft, approve, compile, choose Stripe, and build the bundle.",
        ],
        "expected": [
            "Partial dispute is $245.00 of $1,095.00; $850.00 is uncontested.",
            "Disputed-scope proof passes when both marked lines total $245.00.",
            "POS requirement is dispositive and names any uncovered incidental.",
            "Exhibit D should identify slip POS-4102 $185.00 and VAL-778 $60.00 in the built-in scenario.",
        ],
    },
    "ota_virtual_card_10_4": {
        "folder": "04_visa_10_4_ota_virtual_card",
        "purpose": "OTA virtual-card booking where cardholder and guest legitimately differ.",
        "steps": [
            "Upload the Visa notice and folio.",
            "Verify cardholder Booking.com B.V., guest Priya Nair, channel OTA, source Booking.com, and payer relationship.",
            "Upload the registration, ID, keycard, booking confirmation, and service-log evidence.",
            "Draft and review the third-party-payer explanation before approval.",
        ],
        "expected": [
            "THIRD_PARTY_PAYER appears as informational, not NAME_MISMATCH.",
            "Folio identity is evaluated in OTA context; do not expect guest and cardholder names to match.",
            "The rebuttal should reference the OTA confirmation and virtual-card booking context.",
        ],
    },
    "visa_refund_issued_13_6": {
        "folder": "05_visa_13_6_refund_already_issued",
        "purpose": "Credit-not-processed dispute where the hotel already refunded the full amount.",
        "steps": [
            "Upload the Visa 13.6 notice and folio.",
            "Verify refund amount $412.00, refund date, reference RF-884120-6610, cancellation timestamp, and cancellation number.",
            "Upload policy, communications, and refund receipt evidence; record refund amount/reference in Probative details.",
            "Draft, approve, compile, and inspect the closing request.",
        ],
        "expected": [
            "Amount proof identifies the cardholder as already made whole.",
            "Settlement state is SETTLED_THEN_REFUNDED.",
            "Executive summary and closing request denial of double recovery, not a generic reversal request.",
            "Refund receipt is a dispositive exhibit.",
        ],
    },
    "mc_damage_4859": {
        "folder": "06_mastercard_4859_post_checkout_damage",
        "purpose": "Post-checkout smoking-damage addendum tied to the signed registration clause.",
        "steps": [
            "Upload the Mastercard 4859 notice and folio.",
            "Confirm only the $300.00 Smoking Damage Remediation Fee is disputed; room/tax lines are undisputed.",
            "Upload registration, terminal, keycard, ID, incident evidence, and communications files.",
            "For incident evidence, note report INC-2214 and six photos in the evidence details/notes if testing the UI fields.",
            "Draft, approve, compile, and review chronology for the October 18 addendum.",
        ],
        "expected": [
            "Partial/addendum scope totals $300.00.",
            "Transaction date is treated as post-checkout addendum, not automatically the wrong folio.",
            "Incident/damage evidence is dispositive and Exhibit labeling references INC-2214.",
            "The rebuttal ties the charge to the signed registration damage clause.",
        ],
    },
}


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_")


def money(value: Any) -> str:
    return f"${float(value or 0):,.2f}"


def styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "h1": ParagraphStyle("ArtifactH1", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#1E3A8A")),
        "h2": ParagraphStyle("ArtifactH2", parent=base["Heading2"], fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=colors.HexColor("#1E3A8A")),
        "body": ParagraphStyle("ArtifactBody", parent=base["Normal"], fontName="Helvetica", fontSize=9, leading=12),
        "small": ParagraphStyle("ArtifactSmall", parent=base["Normal"], fontName="Helvetica", fontSize=7.5, leading=10, textColor=colors.HexColor("#475569")),
        "bold": ParagraphStyle("ArtifactBold", parent=base["Normal"], fontName="Helvetica-Bold", fontSize=9, leading=12),
    }


def styled_table(rows: list[list[Any]], widths: list[float], header: bool = False) -> Table:
    table = Table(rows, colWidths=widths, repeatRows=1 if header else 0)
    style = [
        ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
    ]
    if header:
        style += [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")), ("TEXTCOLOR", (0, 0), (-1, 0), colors.white)]
    table.setStyle(TableStyle(style))
    return table


def build_notice_pdf(path: Path, scenario: dict[str, Any]) -> None:
    s = styles()
    notice = scenario["notice"]
    raw_lines = [line for line in str(notice.get("raw_text") or "").splitlines() if line.strip()]
    story: list[Any] = [
        Paragraph("BANK DISPUTE NOTICE — SYNTHETIC TEST FIXTURE", s["h1"]),
        Paragraph("Generated by FolioShield for manual application testing. Not a real bank document.", s["small"]),
        Spacer(1, 12),
    ]
    fields = [
        ("Processor", notice.get("processor") or "Test Acquirer"),
        ("Case Number", notice.get("case_id")),
        ("Acquirer Reference Number (ARN)", notice.get("arn")),
        ("Merchant ID", notice.get("merchant_id")),
        ("Card Network", notice.get("card_network")),
        ("Dispute Reason Code", notice.get("reason_code")),
        ("Reason", notice.get("reason_description")),
        ("Dispute Stage", notice.get("dispute_stage")),
        ("Cardholder Name", notice.get("cardholder_name")),
        ("Account Number", f"************{notice.get('card_last_4')}" if notice.get("card_last_4") else None),
        ("Statement Descriptor", notice.get("statement_descriptor")),
        ("Transaction Date", notice.get("transaction_date")),
        ("Dispute Date", notice.get("dispute_date")),
        ("Response Due Date", notice.get("response_deadline")),
        ("Original Amount", money(notice.get("original_amount"))),
        ("Disputed Amount", f"{money(notice.get('disputed_amount'))} {notice.get('currency') or 'USD'}"),
    ]
    rows = [[Paragraph(f"<b>{label}:</b>", s["body"]), Paragraph(str(value or "Not provided"), s["body"])] for label, value in fields]
    story.append(styled_table(rows, [190, 320]))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Cardholder Statement", s["h2"]))
    story.append(Paragraph(f"“{notice.get('claim_statement') or 'No claim statement provided.'}”", s["body"]))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Extractor Source Text", s["h2"]))
    story.append(Paragraph("The lines below intentionally mirror the structured fields so the deterministic parser can be tested end-to-end.", s["small"]))
    for line in raw_lines:
        story.append(Paragraph(line.replace("&", "&amp;"), s["body"]))
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48,
                            title=f"Test Dispute Notice {notice.get('case_id')}", author="FolioShield Test Fixtures")
    doc.build(story)


def build_folio_pdf(path: Path, scenario: dict[str, Any]) -> None:
    s = styles()
    folio = scenario["folio"]
    story: list[Any] = [
        Paragraph(str(folio.get("hotel_name") or "Test Hotel").upper(), s["h1"]),
        Paragraph(f"Address: {folio.get('hotel_address') or 'Address not provided'}", s["body"]),
        Paragraph("Guest Folio — Synthetic Test Fixture", s["small"]),
        Spacer(1, 12),
    ]
    meta = [
        ("Guest Name", folio.get("guest_name")), ("Folio Number", folio.get("folio_number")),
        ("Confirmation Number", folio.get("confirmation_number")), ("Room Number", folio.get("room_number")),
        ("Arrival Date", folio.get("check_in")), ("Check-in Time", folio.get("check_in_time")),
        ("Departure Date", folio.get("check_out")), ("Stay Status", folio.get("stay_status")),
        ("Booking Source", folio.get("booking_source") or folio.get("booking_channel")),
        ("Booking Date", folio.get("booking_date")), ("Rate Plan", folio.get("rate_plan")),
        ("Rate per Night", money(folio.get("rate_per_night"))), ("Guest Email", folio.get("guest_email")),
        ("Payer", folio.get("payer_name")), ("Merchant ID", folio.get("merchant_id")),
        ("Card", f"************{folio.get('card_last_4')}" if folio.get("card_last_4") else None),
        ("Auth Code", folio.get("auth_code")), ("AVS Result", folio.get("avs_result")),
        ("CVV Result", folio.get("cvv_result")), ("Entry Mode", folio.get("entry_mode")),
        ("Cancellation", folio.get("cancellation_timestamp")), ("Cancellation Number", folio.get("cancellation_number")),
        ("Refund", f"{money(folio.get('refund_amount'))} {folio.get('refund_date') or ''} {folio.get('refund_reference') or ''}".strip()),
    ]
    rows = []
    for i in range(0, len(meta), 2):
        pair = meta[i:i + 2]
        row: list[Any] = []
        for label, value in pair:
            row += [Paragraph(f"<b>{label}:</b>", s["body"]), Paragraph(str(value or "Not provided"), s["body"])]
        while len(row) < 4:
            row.append(Paragraph("", s["body"]))
        rows.append(row)
    story.append(styled_table(rows, [105, 150, 105, 150]))
    story.append(Spacer(1, 14))
    story.append(Paragraph("Itemized Charges and Credits", s["h2"]))
    item_rows = [[Paragraph("<b>Date</b>", s["bold"]), Paragraph("<b>Description</b>", s["bold"]), Paragraph("<b>Reference</b>", s["bold"]), Paragraph("<b>Category</b>", s["bold"]), Paragraph("<b>Amount</b>", s["bold"])]]
    for item in folio.get("line_items") or []:
        amount = float(item.get("amount") or 0)
        if item.get("type") == "Credit":
            amount = -amount
        desc = str(item.get("description") or "")
        if item.get("disputed") is True:
            desc += " [DISPUTED TEST LINE]"
        item_rows.append([
            Paragraph(str(item.get("date") or ""), s["body"]), Paragraph(desc, s["body"]),
            Paragraph(str(item.get("reference") or ""), s["body"]), Paragraph(str(item.get("category") or ""), s["body"]),
            Paragraph(f"{amount:,.2f}", s["body"]),
        ])
    story.append(styled_table(item_rows, [70, 230, 75, 65, 70], header=True))
    story.append(Spacer(1, 12))
    totals = [
        [Paragraph("<b>Total Charges:</b>", s["body"]), Paragraph(money(folio.get("total_charges")), s["body"]),
         Paragraph("<b>Total Payments:</b>", s["body"]), Paragraph(money(folio.get("total_payments")), s["body"])],
        [Paragraph("<b>Balance:</b>", s["body"]), Paragraph(money(folio.get("balance")), s["body"]),
         Paragraph("<b>Auth Code:</b>", s["body"]), Paragraph(str(folio.get("auth_code") or ""), s["body"])],
    ]
    story.append(styled_table(totals, [105, 150, 105, 150]))
    doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48,
                            title=f"Test Guest Folio {folio.get('folio_number')}", author="FolioShield Test Fixtures")
    doc.build(story)


def build_folio_csv(path: Path, scenario: dict[str, Any]) -> None:
    folio = scenario["folio"]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["Date", "Description", "Charge", "Credit", "Reference", "Category"])
        writer.writeheader()
        for item in folio.get("line_items") or []:
            is_credit = item.get("type") == "Credit"
            writer.writerow({
                "Date": item.get("date") or "",
                "Description": item.get("description") or "",
                "Charge": 0.0 if is_credit else float(item.get("amount") or 0),
                "Credit": float(item.get("amount") or 0) if is_credit else 0.0,
                "Reference": item.get("reference") or "",
                "Category": item.get("category") or "",
            })


def build_text_evidence(path: Path, title: str, scenario: dict[str, Any], doc_type: str, item: dict[str, Any]) -> None:
    folio = scenario["folio"]
    notice = scenario["notice"]
    details = item.get("details") or {}
    lines = [
        title,
        "=" * len(title),
        "SYNTHETIC TEST EVIDENCE — generated for FolioShield manual testing.",
        "",
        f"Hotel: {folio.get('hotel_name')}",
        f"Guest: {folio.get('guest_name')}",
        f"Case ID: {notice.get('case_id')}",
        f"Folio: {folio.get('folio_number')}",
        f"Confirmation: {folio.get('confirmation_number')}",
        f"Room: {folio.get('room_number')}",
        f"Stay: {folio.get('check_in')} to {folio.get('check_out')}",
        f"Document type: {doc_type}",
        f"Source: {item.get('source') or 'Test fixture'}",
        f"Verified by: {item.get('verified_by') or 'Test fixture'}",
        "",
        "Details:",
    ]
    if details:
        for key, value in details.items():
            lines.append(f"- {key}: {json.dumps(value, default=str)}")
    else:
        lines.append("- Present in scenario; no additional structured details supplied.")
    if doc_type == "keycard_lock_audit":
        lines += ["", "Sample entries:", "- 2026-10-10 15:22 — key issued / first entry", "- Additional entries recorded during stay", "- Last entry recorded before checkout"]
    if doc_type == "pos_signed_slips":
        lines += ["", "Disputed folio lines:"]
        for line in folio.get("line_items") or []:
            if line.get("disputed") is True:
                lines.append(f"- {line.get('date')} | {line.get('description')} | {money(line.get('amount'))} | Ref {line.get('reference')}")
    if doc_type == "guest_service_log":
        lines += ["", "Unresolved complaints: see details above. Test both 0 and a positive number to see validator behavior."]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_image_evidence(path: Path, title: str, scenario: dict[str, Any], doc_type: str) -> None:
    folio = scenario["folio"]
    image = Image.new("RGB", (1200, 760), "white")
    draw = ImageDraw.Draw(image)
    try:
        title_font = ImageFont.truetype("arial.ttf", 34)
        body_font = ImageFont.truetype("arial.ttf", 24)
        small_font = ImageFont.truetype("arial.ttf", 19)
    except OSError:
        title_font = body_font = small_font = ImageFont.load_default()
    draw.rectangle((25, 25, 1175, 735), outline=(30, 58, 138), width=4)
    draw.text((55, 50), title, fill=(30, 58, 138), font=title_font)
    lines = [
        "SYNTHETIC TEST IMAGE — not a real identity or payment document.",
        f"Hotel: {folio.get('hotel_name')}",
        f"Guest: {folio.get('guest_name')}",
        f"Room: {folio.get('room_number')}  Stay: {folio.get('check_in')} to {folio.get('check_out')}",
        f"Document type: {doc_type}",
        "",
        "Signature / verification mark:",
    ]
    y = 145
    for line in lines:
        draw.text((55, y), line, fill=(17, 24, 39), font=body_font)
        y += 42
    # Fictional signature scribble; deliberately not a real person's signature.
    points = [(80, 520), (180, 470), (260, 545), (350, 455), (460, 530), (560, 475), (700, 520)]
    draw.line(points, fill=(17, 24, 39), width=4)
    draw.line((70, 565, 760, 565), fill=(100, 116, 139), width=2)
    draw.text((55, 600), "Test fixture only — verify visually in the application.", fill=(71, 85, 105), font=small_font)
    image.save(path)


def evidence_extension(doc_type: str, original: str) -> str:
    ext = Path(original).suffix.lower()
    if ext in {".pdf", ".png", ".jpg", ".jpeg", ".csv", ".txt", ".eml"}:
        return ext
    if doc_type in {"signed_registration_card", "id_verification_log"}:
        return ".png"
    if doc_type in {"keycard_lock_audit", "wifi_usage_log", "avs_cvv_result"}:
        return ".csv" if doc_type != "avs_cvv_result" else ".txt"
    return ".txt"


def build_evidence_files(folder: Path, scenario: dict[str, Any]) -> list[dict[str, Any]]:
    evidence_dir = folder / "evidence"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    generated: list[dict[str, Any]] = []
    docs = scenario.get("supporting_docs") or {}
    for index, (doc_type, raw_item) in enumerate(docs.items(), 1):
        item = raw_item if isinstance(raw_item, dict) else {"present": bool(raw_item)}
        if not item.get("present", True):
            continue
        original = str(item.get("filename") or f"{doc_type}.txt")
        ext = evidence_extension(doc_type, original)
        filename = f"{index:02d}_{safe_name(doc_type)}{ext}"
        path = evidence_dir / filename
        title = doc_type.replace("_", " ").title()
        if ext == ".png":
            build_image_evidence(path, title, scenario, doc_type)
        elif ext == ".csv":
            # Small readable CSV for lock/wifi style fixtures.
            details = item.get("details") or {}
            with path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["timestamp", "room", "event", "source"])
                writer.writerow([details.get("first_entry", scenario["folio"].get("check_in")), scenario["folio"].get("room_number"), "first_entry", item.get("source", "test")])
                writer.writerow([details.get("last_entry", scenario["folio"].get("check_out")), scenario["folio"].get("room_number"), "last_entry", item.get("source", "test")])
        elif ext == ".pdf":
            # ReportLab evidence summary PDF; content is text-extractable.
            s = styles()
            story = [Paragraph(title.upper(), s["h1"]), Paragraph("Synthetic test evidence generated for FolioShield.", s["small"]), Spacer(1, 10)]
            details = item.get("details") or {}
            rows = [[Paragraph("<b>Field</b>", s["body"]), Paragraph("<b>Value</b>", s["body"])]]
            rows.append([Paragraph("Guest", s["body"]), Paragraph(str(scenario["folio"].get("guest_name")), s["body"])])
            rows.append([Paragraph("Case", s["body"]), Paragraph(str(scenario["notice"].get("case_id")), s["body"])])
            for k, v in details.items():
                rows.append([Paragraph(str(k), s["body"]), Paragraph(json.dumps(v, default=str), s["body"])])
            story.append(styled_table(rows, [140, 370], header=True))
            doc = SimpleDocTemplate(str(path), pagesize=letter, leftMargin=48, rightMargin=48, topMargin=48, bottomMargin=48,
                                    title=title, author="FolioShield Test Fixtures")
            doc.build(story)
        else:
            build_text_evidence(path, title, scenario, doc_type, item)
        generated.append({
            "doc_type": doc_type,
            "generated_file": f"evidence/{filename}",
            "scenario_filename": item.get("filename"),
            "scenario_sha256_note": "Scenario JSON contains demo hash metadata; generated file hash will differ and is computed by the app on upload.",
            "details_to_enter": item.get("details") or {},
        })
    return generated


def write_scenario(folder: Path, key: str, scenario: dict[str, Any]) -> dict[str, Any]:
    folder.mkdir(parents=True, exist_ok=True)
    build_notice_pdf(folder / "01_bank_dispute_notice.pdf", scenario)
    build_folio_pdf(folder / "02_guest_folio.pdf", scenario)
    build_folio_csv(folder / "02_guest_folio.csv", scenario)
    evidence = build_evidence_files(folder, scenario)
    payload = {
        "scenario_key": key,
        "title": scenario.get("title"),
        "description": scenario.get("description"),
        "notice": scenario.get("notice"),
        "folio": scenario.get("folio"),
        "supporting_docs": scenario.get("supporting_docs"),
        "generated_evidence": evidence,
        "guide": SCENARIO_GUIDE[key],
    }
    (folder / "scenario.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    guide = SCENARIO_GUIDE[key]
    md = [f"# {scenario.get('title')}", "", f"**Purpose:** {guide['purpose']}", "", "## Files", "", "- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).", "- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).", "- `02_guest_folio.csv` — alternative folio upload in Tab 1.", "- `evidence/` — upload each file into the matching evidence slot in Tab 2.", "- `scenario.json` — source data, evidence details, and expected checks.", "", "## Test Steps", ""]
    md += [f"{i}. {step}" for i, step in enumerate(guide["steps"], 1)]
    md += ["", "## Expected Results", ""]
    md += [f"- {item}" for item in guide["expected"]]
    md += ["", "> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.", ""]
    (folder / "TESTING_GUIDE.md").write_text("\n".join(md), encoding="utf-8")
    return payload


def main() -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    index: list[dict[str, Any]] = []
    for key, scenario in SCENARIOS.items():
        guide = SCENARIO_GUIDE[key]
        folder = OUT_ROOT / guide["folder"]
        payload = write_scenario(folder, key, scenario)
        index.append({
            "scenario_key": key,
            "folder": guide["folder"],
            "title": scenario.get("title"),
            "network": scenario.get("network"),
            "files": ["01_bank_dispute_notice.pdf", "02_guest_folio.pdf", "02_guest_folio.csv", "scenario.json", "TESTING_GUIDE.md"],
            "evidence_files": payload["generated_evidence"],
        })
    (OUT_ROOT / "INDEX.json").write_text(json.dumps(index, indent=2, default=str), encoding="utf-8")

    readme = ["# FolioShield Manual Test Artifacts", "", "Upload-ready synthetic fixtures for all six built-in scenarios.", "", "## Complete Evidence Library (all 20 UI evidence types)", "", "If you want a file for **every** evidence slot shown in Tab 2 — including Payment Authorization, Incidentals, Financial Resolution, and Court/Legal items that a single scenario may not need — use:", "", "- `00_complete_evidence_library/README.md` — complete mapping table (UI group → evidence slot → file → values to enter).", "- `00_complete_evidence_library/library_index.json` — machine-readable index for all 20 evidence types.", "", "The library is aligned to the Visa 10.4 reference case so all slots can be exercised together. For realistic amount/reference matching, prefer each scenario folder's own `evidence/` files.", "", "## How to use", "", "1. Start FolioShield.", "2. In the sidebar, choose **New Dispute Case** (do not use the reference-case loader when testing uploads).", "3. Open a scenario folder below.", "4. Upload `01_bank_dispute_notice.pdf` and either `02_guest_folio.pdf` or `02_guest_folio.csv` in Tab 1.", "5. Follow that folder's `TESTING_GUIDE.md`.", "6. Upload files from `evidence/` into matching Tab 2 evidence slots and enter any listed probative details.", "", "## Scenarios", ""]
    for item in index:
        readme.append(f"- **{item['title']}** — `{item['folder']}/`")
    readme += ["", "## Notes", "", "- These are synthetic fixtures, not real bank, identity, payment, or legal documents.", "- Generated evidence hashes differ from demo hashes in `scenario.json`; FolioShield computes actual hashes on upload.", "- Some scenario evidence in the built-in quick-loader is metadata-only. These folders provide actual bytes specifically for upload testing.", "- For the strongest end-to-end test, use Scenario 1 first, then Scenario 3 (partial slips), Scenario 5 (refund), and Scenario 4 (OTA).", ""]
    (OUT_ROOT / "README.md").write_text("\n".join(readme), encoding="utf-8")
    print(f"Generated manual test artifacts in {OUT_ROOT}")


if __name__ == "__main__":
    main()
