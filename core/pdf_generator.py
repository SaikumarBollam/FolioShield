"""
Three-Page PDF Dispute Evidence Packet Generator for FolioShield.
Built with ReportLab. Every value in the packet comes from the extracted documents, the reconciliation
result, or the reviewer — the generator never fabricates logs, timestamps, policies, or signatures.
Each page's content is wrapped in a shrink-to-fit frame so the packet is always exactly three pages.
"""

import io
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import KeepInFrame, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .audit_logger import AuditLogger
from .rules import SUPPORTING_DOC_TYPES
from .security import escape_markup as esc

PAGE_W, PAGE_H = letter
MARGIN_X, MARGIN_Y = 40, 50
FRAME_PAD = 6
CONTENT_W = PAGE_W - 2 * MARGIN_X - 2 * FRAME_PAD
CONTENT_H = PAGE_H - 2 * MARGIN_Y - 2 * FRAME_PAD
MAX_LINE_ITEMS = 60

GREEN, RED, AMBER = "#16A34A", "#DC2626", "#D97706"


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to inject 'Page X of N' and the running header/footer on every page.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states: List[Dict[str, Any]] = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, total_pages: int):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#64748B"))
        right = PAGE_W - MARGIN_X

        self.drawString(MARGIN_X, PAGE_H - 32, "FOLIOSHIELD — CHARGEBACK EVIDENCE PACKET")
        self.drawRightString(right, PAGE_H - 32, "CONFIDENTIAL // PREPARED FOR PROCESSOR SUBMISSION")
        self.setStrokeColor(colors.HexColor("#CBD5E1"))
        self.setLineWidth(0.75)
        self.line(MARGIN_X, PAGE_H - 38, right, PAGE_H - 38)

        self.line(MARGIN_X, 42, right, 42)
        self.setFont("Helvetica", 8)
        self.drawString(MARGIN_X, 30, "Generated with FolioShield — verify against current processor and card-network requirements before submission")
        self.drawRightString(right, 30, f"Page {self._pageNumber} of {total_pages}")
        self.restoreState()


def _cols(*fractions: float) -> List[float]:
    """Column widths as fractions of the usable content width."""
    total = sum(fractions)
    return [CONTENT_W * f / total for f in fractions]


def _fmt_money(value: Any) -> str:
    return f"${float(value or 0):,.2f}"


def _or(value: Any, placeholder: str = "Not provided") -> str:
    return placeholder if value in (None, "") else str(value)


def _box(paragraph: Paragraph, background: str, border: str, border_w: float = 0.75) -> Table:
    t = Table([[paragraph]], colWidths=[CONTENT_W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
        ("BOX", (0, 0), (-1, -1), border_w, colors.HexColor(border)),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return t


def _fit_page(flowables: List[Any]) -> KeepInFrame:
    """Shrinks a page's content if necessary so it never spills onto an extra page."""
    return KeepInFrame(CONTENT_W, CONTENT_H, flowables, mode="shrink")


class EvidencePacketGenerator:
    """
    Compiles a 3-page dispute rebuttal packet.
    """

    @staticmethod
    def _styles() -> Dict[str, ParagraphStyle]:
        base = getSampleStyleSheet()
        body = ParagraphStyle("PacketBody", parent=base["Normal"], fontName="Helvetica", fontSize=8, leading=11,
                              textColor=colors.HexColor("#1E293B"))
        return {
            "title": ParagraphStyle("DocTitle", parent=base["Heading1"], fontName="Helvetica-Bold", fontSize=15,
                                    leading=18, textColor=colors.HexColor("#0F172A"), spaceAfter=3),
            "subtitle": ParagraphStyle("DocSubtitle", parent=base["Normal"], fontName="Helvetica", fontSize=9,
                                       leading=12, textColor=colors.HexColor("#475569"), spaceAfter=8),
            "section": ParagraphStyle("SectionHeading", parent=base["Heading2"], fontName="Helvetica-Bold",
                                      fontSize=10, leading=13, textColor=colors.HexColor("#1E3A8A"),
                                      spaceBefore=6, spaceAfter=4),
            "body": body,
            "bold": ParagraphStyle("PacketBodyBold", parent=body, fontName="Helvetica-Bold"),
            "rebuttal": ParagraphStyle("RebuttalBody", parent=body, fontSize=7.5, leading=10.2,
                                       textColor=colors.HexColor("#0F172A")),
            "rebuttal_head": ParagraphStyle("RebuttalHead", parent=body, fontName="Helvetica-Bold", fontSize=7.8,
                                            leading=10.5, spaceBefore=3, textColor=colors.HexColor("#1E3A8A")),
            "bullet": ParagraphStyle("RebuttalBullet", parent=body, fontSize=7.5, leading=10.2, leftIndent=10,
                                     bulletIndent=2),
        }

    @staticmethod
    def _rebuttal_flowables(text: str, s: Dict[str, ParagraphStyle]) -> List[Any]:
        """Renders the full reviewer-approved rebuttal, preserving headings and bullet lists."""
        out: List[Any] = []
        for raw_line in (text or "").splitlines():
            line = raw_line.strip()
            if not line:
                out.append(Spacer(1, 3))
                continue
            line = re.sub(r"^#+\s*", "", line).replace("**", "")
            if re.match(r"^[-*•]\s+", line):
                out.append(Paragraph(esc(re.sub(r"^[-*•]\s+", "", line)), s["bullet"], bulletText="•"))
            elif re.match(r"^\d+\.\s+[A-Z]", line) or (line.isupper() and len(line) > 3):
                out.append(Paragraph(esc(line), s["rebuttal_head"]))
            else:
                out.append(Paragraph(esc(line), s["rebuttal"]))
        return out or [Paragraph("[No rebuttal text provided]", s["rebuttal"])]

    @classmethod
    def generate_packet(
        cls,
        notice: Dict[str, Any],
        folio: Dict[str, Any],
        reconciliation: Dict[str, Any],
        rebuttal_text: str,
        audit_sha256: Optional[str] = None,
        approved_by: Optional[str] = None,
        approved_at: Optional[str] = None,
        policy_text: Optional[str] = None,
    ) -> bytes:
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(
            buffer, pagesize=letter,
            leftMargin=MARGIN_X, rightMargin=MARGIN_X, topMargin=MARGIN_Y, bottomMargin=MARGIN_Y,
            title=f"FolioShield Dispute Packet {_or(notice.get('case_id'), '')}".strip(),
            author="FolioShield",
        )
        s = cls._styles()
        body, bold = s["body"], s["bold"]

        hotel_name = _or(folio.get("hotel_name"), "Merchant")
        case_id = _or(notice.get("case_id"))
        network = _or(notice.get("card_network"), "Unknown network")
        code = _or(notice.get("reason_code"), "Unknown code")
        disp_amt = float(notice.get("disputed_amount") or 0.0)
        folio_tot = float(folio.get("total_charges") or 0.0)
        folio_paid = float(folio.get("total_payments") or 0.0)
        balance = round(folio_tot - folio_paid, 2)
        card_last4 = folio.get("card_last_4") or notice.get("card_last_4")
        masked_card = f"**** **** **** {card_last4}" if card_last4 else "Not provided"
        cardholder = folio.get("guest_name") or notice.get("cardholder_name")
        rule_meta = reconciliation.get("rule_details") or {}
        code_name = rule_meta.get("name", "Reason code not in FolioShield knowledge base")
        docs = reconciliation.get("supporting_docs") or {}

        def grid(rows: List[List[Any]], widths: List[float], background: str = "#F8FAFC") -> Table:
            t = Table(rows, colWidths=widths)
            t.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor(background)),
                ("BOX", (0, 0), (-1, -1), 0.75, colors.HexColor("#CBD5E1")),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#E2E8F0")),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ]))
            return t

        def kv(label: str, value: Any, value_style: ParagraphStyle = bold) -> List[Paragraph]:
            return [Paragraph(f"<b>{esc(label)}</b>", body), Paragraph(esc(_or(value)), value_style)]

        # =========================================================================
        # PAGE 1: COVER LETTER & FORMAL REBUTTAL STATEMENT
        # =========================================================================
        page1: List[Any] = [
            Paragraph(f"<b>{esc(hotel_name.upper())}</b> — FORMAL DISPUTE REBUTTAL", s["title"]),
            Paragraph("Submitted to the Acquirer / Processor Chargeback Department", s["subtitle"]),
            grid([
                kv("Dispute Case ID:", case_id) + kv("Card Network / Code:", f"{network} — {code}"),
                kv("Disputed Amount:", f"{_fmt_money(disp_amt)} USD") + kv("Total Folio Charges:", f"{_fmt_money(folio_tot)} USD"),
                kv("Account Number:", masked_card) + kv("Cardholder / Guest:", cardholder),
                kv("Stay Dates:", f"{_or(folio.get('check_in'))} to {_or(folio.get('check_out'))}", body)
                + kv("Response Deadline:", notice.get("response_deadline")),
            ], _cols(110, 156, 110, 156)),
            Spacer(1, 6),
            Paragraph(f"<b>Reason code:</b> {esc(network)} {esc(code)} — {esc(code_name)}", body),
            Paragraph("<b>REBUTTAL STATEMENT (reviewed and approved by merchant staff)</b>", s["section"]),
            *cls._rebuttal_flowables(rebuttal_text, s),
            Spacer(1, 8),
        ]
        sig = Table([
            [Paragraph(f"<b>Approved By:</b> {esc(_or(approved_by, 'Pending approval'))}", body),
             Paragraph(f"<b>Approved At:</b> {esc(_or(approved_at, 'Pending approval'))}", body)],
            [Paragraph("<b>Authorized Signature:</b> ______________________________", body),
             Paragraph("<b>Date:</b> ____________________", body)],
        ], colWidths=_cols(1, 1))
        sig.setStyle(TableStyle([
            ("LINEABOVE", (0, 0), (-1, 0), 0.75, colors.HexColor("#94A3B8")),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        page1.append(sig)

        # =========================================================================
        # PAGE 2: ITEMIZED TRANSACTION AUDIT & RECONCILIATION
        # =========================================================================
        page2: List[Any] = [
            Paragraph("<b>ITEMIZED FOLIO & RECONCILIATION AUDIT</b>", s["title"]),
            Paragraph("Accounting ledger as extracted from the uploaded folio, with reconciliation against the bank notice.", s["subtitle"]),
            grid([
                kv("Room Number:", folio.get("room_number")) + kv("Arrival Date:", folio.get("check_in"), body)
                + kv("Departure Date:", folio.get("check_out"), body),
                kv("Auth Code:", folio.get("auth_code")) + kv("Card Last-4:", f"**** {card_last4}" if card_last4 else None)
                + kv("Folio Balance:", _fmt_money(balance) + (" (Settled)" if abs(balance) < 0.01 else " (Open)")),
            ], _cols(90, 87, 90, 87, 90, 88), background="#F1F5F9"),
            Spacer(1, 8),
            Paragraph("<b>Itemized Transaction Log</b>", s["section"]),
        ]

        line_items = folio.get("line_items") or []
        if line_items:
            rows = [[Paragraph(f"<b>{h}</b>", bold) for h in ("Date", "Description / Voucher", "Type", "Charges ($)", "Credits ($)")]]
            total_chg = total_crd = 0.0
            for item in line_items:
                amt = float(item.get("amount") or 0.0)
                if item.get("type") == "Credit":
                    total_crd += amt
                    chg_str, crd_str = "—", _fmt_money(amt)
                else:
                    total_chg += amt
                    chg_str, crd_str = _fmt_money(amt), "—"
                if len(rows) <= MAX_LINE_ITEMS:
                    rows.append([Paragraph(esc(_or(item.get(k), "—")), body) for k in ("date", "description", "type")]
                                + [Paragraph(chg_str, body), Paragraph(crd_str, body)])
            omitted = len(line_items) - (len(rows) - 1)
            note = f"Net balance {_fmt_money(total_chg - total_crd)}" + (f" ({omitted} more items in source folio)" if omitted > 0 else "")
            rows.append([Paragraph("<b>TOTALS</b>", bold), Paragraph(f"<b>{esc(note)}</b>", bold), Paragraph("", bold),
                         Paragraph(f"<b>{_fmt_money(total_chg)}</b>", bold), Paragraph(f"<b>{_fmt_money(total_crd)}</b>", bold)])
            folio_table = Table(rows, colWidths=_cols(70, 242, 60, 80, 80), repeatRows=1)
            folio_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1E3A8A")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -2), [colors.white, colors.HexColor("#F8FAFC")]),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2E8F0")),
                ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
            ]))
            page2.append(folio_table)
        else:
            page2.append(_box(Paragraph(
                f"No itemized line items were extracted from the folio. Folio totals: charges {_fmt_money(folio_tot)}, "
                f"payments {_fmt_money(folio_paid)}. Attach the full PMS folio export.", body), "#FEF2F2", RED))
        page2.append(Spacer(1, 8))

        page2.append(Paragraph("<b>Dispute Reconciliation Audit & Mathematical Check</b>", s["section"]))
        recon_lines = [f"<font color='{GREEN}'><b>[OK] Verified:</b></font> {esc(h)}" for h in reconciliation.get("audit_highlights", [])]
        for d in reconciliation.get("discrepancies", []):
            color = RED if d.get("severity") == "critical" else AMBER
            recon_lines.append(f"<font color='{color}'><b>[!] {esc(d.get('type'))}:</b></font> {esc(d.get('message'))}")
        has_issues = any(d.get("severity") in ("critical", "warning") for d in reconciliation.get("discrepancies", []))
        page2.append(_box(
            Paragraph("<br/>".join(recon_lines) or "No mathematical or identity discrepancies detected.", body),
            "#FFFBEB" if has_issues else "#F0FDF4", AMBER if has_issues else GREEN,
        ))

        # =========================================================================
        # PAGE 3: SUPPORTING EVIDENCE ANNEX & CHAIN OF CUSTODY
        # =========================================================================
        page3: List[Any] = [
            Paragraph("<b>EVIDENCE ANNEX & CHAIN OF CUSTODY</b>", s["title"]),
            Paragraph("Card-network evidence checklist, supporting documents on file, policy disclosure, and integrity certification.", s["subtitle"]),
            Paragraph(f"<b>Compelling Evidence Checklist — {esc(network)} {esc(code)}</b> "
                      f"(coverage {int(reconciliation.get('completeness_score') or 0)}%)", s["section"]),
        ]
        chk_rows = [[Paragraph(f"<b>{h}</b>", bold) for h in ("Required Evidence Item", "Status", "Exhibit")]]
        exhibit_no = 0
        for c in reconciliation.get("evidence_checklist", []):
            present = bool(c.get("present"))
            exhibit = ""
            if present:
                # Same lettering as the rebuttal's exhibit index (A = first available item)
                exhibit = f"Exhibit {chr(65 + exhibit_no)}" if exhibit_no < 26 else "Attached"
                exhibit_no += 1
            chk_rows.append([
                Paragraph(esc(c.get("item", "Evidence Item")), body),
                Paragraph(f"<font color='{GREEN if present else RED}'><b>{esc(c.get('status'))}</b></font>", body),
                Paragraph(exhibit or "—", body),
            ])
        chk_table = Table(chk_rows, colWidths=_cols(332, 120, 80))
        chk_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#0F172A")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F8FAFC")]),
            ("TOPPADDING", (0, 0), (-1, -1), 2.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
        ]))
        page3 += [chk_table, Spacer(1, 8), Paragraph("<b>Supporting Documents Confirmed by Staff</b>", s["section"])]

        doc_rows = [[Paragraph(f"<b>{h}</b>", bold) for h in ("Document", "Status")]]
        for key, label in SUPPORTING_DOC_TYPES.items():
            on_file = bool(docs.get(key))
            doc_rows.append([
                Paragraph(esc(label), body),
                Paragraph(f"<font color='{GREEN if on_file else RED}'><b>{'On file — attach copy' if on_file else 'Not provided'}</b></font>", body),
            ])
        doc_table = Table(doc_rows, colWidths=_cols(372, 160))
        doc_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#334155")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#CBD5E1")),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        page3 += [doc_table, Spacer(1, 8), Paragraph("<b>Cancellation Policy Disclosed at Booking</b>", s["section"])]

        if policy_text and policy_text.strip():
            policy_para = f"<i>{esc(policy_text.strip())}</i>"
        elif docs.get("cancellation_policy_acknowledged"):
            policy_para = "Policy acknowledgement is on file. [Paste the exact policy text shown to the guest at booking before submission.]"
        else:
            policy_para = "No cancellation policy acknowledgement has been confirmed for this reservation."
        page3 += [_box(Paragraph(policy_para, body), "#F8FAFC", "#94A3B8", 0.5), Spacer(1, 8)]

        now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        digest = audit_sha256 or AuditLogger.calculate_sha256((rebuttal_text or "").encode("utf-8"))
        page3.append(_box(Paragraph(
            "<b>EVIDENCE INTEGRITY & CHAIN OF CUSTODY</b><br/>"
            f"Compiled: {now_utc} | Rebuttal SHA-256: <font face='Courier'>{esc(digest)}</font><br/>"
            "The undersigned authorized representative certifies that the records referenced in this packet are true copies "
            "of business records maintained in the ordinary course of hotel operations.<br/><br/>"
            "Signature: ______________________________ &nbsp;&nbsp; Name / Title: ______________________________",
            body), "#F1F5F9", "#475569", 1))

        story = [_fit_page(page1), PageBreak(), _fit_page(page2), PageBreak(), _fit_page(page3)]
        doc.build(story, canvasmaker=NumberedCanvas)
        return buffer.getvalue()
