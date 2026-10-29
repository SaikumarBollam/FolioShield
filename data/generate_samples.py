"""
Generates sample PDF and CSV dispute documents for testing and evaluation.
"""

import os
import pandas as pd
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle

def create_sample_files():
    os.makedirs("samples", exist_ok=True)
    styles = getSampleStyleSheet()

    # 1. Sample Bank Dispute Notice PDF
    notice_path = os.path.join("samples", "sample_dispute_notice_visa_10_4.pdf")
    doc = SimpleDocTemplate(notice_path, pagesize=letter, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50)
    story = []

    h1 = ParagraphStyle('H1', parent=styles['Heading1'], fontName='Helvetica-Bold', fontSize=16, leading=20, textColor=colors.HexColor("#1E3A8A"))
    body = ParagraphStyle('Body', parent=styles['Normal'], fontName='Helvetica', fontSize=10, leading=14)
    body_bold = ParagraphStyle('BodyB', parent=body, fontName='Helvetica-Bold')

    story.append(Paragraph("<b>VISA DISPUTE & CHARGEBACK NOTIFICATION</b>", h1))
    story.append(Paragraph("Acquirer Processing Division — Card Scheme Arbitration", body))
    story.append(Spacer(1, 15))

    data = [
        [Paragraph("<b>Case Number:</b>", body), Paragraph("V-DISP-89214-X", body_bold)],
        [Paragraph("<b>Acquirer Reference Number (ARN):</b>", body), Paragraph("24492156291002918274019", body)],
        [Paragraph("<b>Notice / Dispute Date:</b>", body), Paragraph("10/24/2026", body)],
        [Paragraph("<b>Response Due Date:</b>", body), Paragraph("11/07/2026", body_bold)],
        [Paragraph("<b>Merchant Name:</b>", body), Paragraph("Grand Horizon Resort & Suites", body)],
        [Paragraph("<b>Cardholder Name:</b>", body), Paragraph("Jonathan C. Davis", body_bold)],
        [Paragraph("<b>Account Number:</b>", body), Paragraph("************4821", body_bold)],
        [Paragraph("<b>Dispute Reason Code:</b>", body), Paragraph("10.4 — Other Fraud: Card-Absent Environment", body_bold)],
        [Paragraph("<b>Transaction Date:</b>", body), Paragraph("10/10/2026", body)],
        [Paragraph("<b>Disputed Amount:</b>", body), Paragraph("$1,280.50 USD", body_bold)],
        [Paragraph("<b>Original Amount:</b>", body), Paragraph("$1,280.50 USD", body)]
    ]
    t = Table(data, colWidths=[200, 312])
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F8FAFC")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story.append(t)
    story.append(Spacer(1, 15))

    story.append(Paragraph("<b>Cardholder Explanation:</b>", body_bold))
    story.append(Paragraph("'The cardholder claims they never authorized or participated in this lodging transaction and did not travel to Florida during the dates indicated. Please supply compelling evidence including signed registration and proof of stay within 14 calendar days.'", body))
    doc.build(story)

    # 2. Sample Hotel Folio PDF
    folio_path = os.path.join("samples", "sample_hotel_folio_john_davis.pdf")
    doc_f = SimpleDocTemplate(folio_path, pagesize=letter, leftMargin=50, rightMargin=50, topMargin=50, bottomMargin=50)
    story_f = []

    story_f.append(Paragraph("<b>GRAND HORIZON RESORT & SUITES</b>", h1))
    story_f.append(Paragraph("100 Ocean Avenue, Miami Beach, FL 33139 | (305) 555-0199", body))
    story_f.append(Spacer(1, 15))

    f_meta = [
        [Paragraph("<b>Guest Name:</b>", body), Paragraph("Jonathan C. Davis", body_bold), Paragraph("<b>Folio Number:</b>", body), Paragraph("FOL-2026-9812", body)],
        [Paragraph("<b>Room Number:</b>", body), Paragraph("412 (Deluxe King Oceanfront)", body), Paragraph("<b>Arrival Date:</b>", body), Paragraph("10/10/2026", body)],
        [Paragraph("<b>Payment Method:</b>", body), Paragraph("Visa ending 4821", body), Paragraph("<b>Departure Date:</b>", body), Paragraph("10/13/2026", body)],
        [Paragraph("<b>Auth Code:</b>", body), Paragraph("AP98231", body_bold), Paragraph("<b>Total Charges:</b>", body), Paragraph("$1,280.50", body_bold)]
    ]
    t_f = Table(f_meta, colWidths=[100, 156, 100, 156])
    t_f.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor("#F1F5F9")),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
    ]))
    story_f.append(t_f)
    story_f.append(Spacer(1, 15))

    story_f.append(Paragraph("<b>Itemized Guest Charges & Credits:</b>", body_bold))
    items = [
        [Paragraph("<b>Date</b>", body_bold), Paragraph("<b>Description</b>", body_bold), Paragraph("<b>Amount ($)</b>", body_bold)],
        [Paragraph("10/10/2026", body), Paragraph("Room Accommodation - Deluxe King", body), Paragraph("320.00", body)],
        [Paragraph("10/10/2026", body), Paragraph("Occupancy & Resort Tax (14.5%)", body), Paragraph("46.40", body)],
        [Paragraph("10/10/2026", body), Paragraph("Resort Amenity Fee", body), Paragraph("40.00", body)],
        [Paragraph("10/11/2026", body), Paragraph("Room Accommodation - Deluxe King", body), Paragraph("320.00", body)],
        [Paragraph("10/11/2026", body), Paragraph("Occupancy & Resort Tax (14.5%)", body), Paragraph("46.40", body)],
        [Paragraph("10/11/2026", body), Paragraph("Ocean Grill Dining Room Charge (Signed)", body), Paragraph("87.70", body)],
        [Paragraph("10/12/2026", body), Paragraph("Room Accommodation - Deluxe King", body), Paragraph("320.00", body)],
        [Paragraph("10/12/2026", body), Paragraph("Occupancy & Resort Tax (14.5%)", body), Paragraph("46.40", body)],
        [Paragraph("10/12/2026", body), Paragraph("Spa Cabana Refreshments", body), Paragraph("53.60", body)],
        [Paragraph("10/13/2026", body), Paragraph("Visa Settlement Payment (Auth: AP98231)", body), Paragraph("-1280.50", body)],
        [Paragraph("<b>Balance Due:</b>", body_bold), Paragraph("<b>Settled $0.00</b>", body_bold), Paragraph("<b>$0.00</b>", body_bold)]
    ]
    t_items = Table(items, colWidths=[100, 312, 100])
    t_items.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
    ]))
    story_f.append(t_items)
    doc_f.build(story_f)

    # 3. Sample CSV Folio
    csv_path = os.path.join("samples", "sample_hotel_folio_john_davis.csv")
    csv_data = [
        {"Date": "10/10/2026", "Description": "Room Accommodation - Deluxe King", "Charge": 320.00, "Credit": 0.0, "Reference": "RM412"},
        {"Date": "10/10/2026", "Description": "Occupancy & Resort Tax (14.5%)", "Charge": 46.40, "Credit": 0.0, "Reference": "TAX-OCC"},
        {"Date": "10/10/2026", "Description": "Resort Amenity Fee", "Charge": 40.00, "Credit": 0.0, "Reference": "RES-FEE"},
        {"Date": "10/11/2026", "Description": "Room Accommodation - Deluxe King", "Charge": 320.00, "Credit": 0.0, "Reference": "RM412"},
        {"Date": "10/11/2026", "Description": "Occupancy & Resort Tax (14.5%)", "Charge": 46.40, "Credit": 0.0, "Reference": "TAX-OCC"},
        {"Date": "10/11/2026", "Description": "Ocean Grill Dining (Signed Slip)", "Charge": 87.70, "Credit": 0.0, "Reference": "POS-9812"},
        {"Date": "10/12/2026", "Description": "Room Accommodation - Deluxe King", "Charge": 320.00, "Credit": 0.0, "Reference": "RM412"},
        {"Date": "10/12/2026", "Description": "Occupancy & Resort Tax (14.5%)", "Charge": 46.40, "Credit": 0.0, "Reference": "TAX-OCC"},
        {"Date": "10/12/2026", "Description": "Spa Cabana Refreshments", "Charge": 53.60, "Credit": 0.0, "Reference": "SPA-331"},
        {"Date": "10/13/2026", "Description": "Visa Payment Auth AP98231", "Charge": 0.0, "Credit": 1280.50, "Reference": "AUTH-AP98231"}
    ]
    pd.DataFrame(csv_data).to_csv(csv_path, index=False)
    print(f"Sample files generated in: {os.path.abspath('samples')}")

if __name__ == "__main__":
    create_sample_files()
