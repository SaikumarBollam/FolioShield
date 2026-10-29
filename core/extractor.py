"""
Document Extraction Pipeline for FolioShield.
Extracts structured transaction information from bank dispute notices and guest folios (PDF, CSV).
Uses deterministic regex and table parsers; visual records are handled by the Llama Vision hooks
in core.llm_engine. Fields that cannot be found are returned as None — values are never invented.
"""

import io
import logging
import re
from typing import Any, Dict, List, Optional

import pandas as pd

from .security import mask_card_number, sanitize_untrusted_text

logger = logging.getLogger(__name__)

_DATE = r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})'
_MONEY = r'\$?\s*([0-9][0-9,]*\.[0-9]{2})'


class ExtractionError(ValueError):
    """Raised when a document cannot be read."""


def _to_amount(raw: Any) -> float:
    """Parses '$1,234.56', '(12.00)', '-12', etc. into a float; returns 0.0 if unparseable."""
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return 0.0
    text = str(raw).strip().replace("$", "").replace(",", "")
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    try:
        value = float(text)
    except ValueError:
        return 0.0
    return -value if negative else value


def _search(pattern: str, text: str, flags: int = re.I | re.M) -> Optional[str]:
    m = re.search(pattern, text, flags)
    return m.group(1).strip() if m else None


def _find_last4(text: str) -> Optional[str]:
    """Finds a card's last 4 digits using explicit masked/ending patterns only."""
    patterns = [
        r'(?:ending(?:\s+in)?|last\s*(?:4|four)(?:\s*digits)?)[:\s#]*(\d{4})\b',
        r'[*xX•]{4,}[\s-]*(\d{4})\b',
        r'(?:Account|Card|PAN)\s*(?:Number|No\.?|#)?\s*[:#]\s*(?:[*xX•\d][\s-]?){8,15}(\d{4})\b',
    ]
    for pat in patterns:
        found = _search(pat, text)
        if found:
            return found
    return None


class DocumentExtractor:
    """
    Handles extraction from Bank Dispute Notices and Hotel Guest Folios.
    """

    @staticmethod
    def extract_text_from_pdf(file_bytes: bytes) -> str:
        """
        Extracts text from a PDF (pdfplumber first, pypdf as fallback).
        Card numbers are masked and prompt-injection phrases neutralized before returning.
        Raises ExtractionError if no text could be extracted.
        """
        text = ""
        errors: List[str] = []
        try:
            import pdfplumber
            with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
                text = "\n".join(page.extract_text() or "" for page in pdf.pages)
        except Exception as e:  # pdfplumber raises a variety of parser errors
            errors.append(f"pdfplumber: {e}")

        if not text.strip():
            try:
                import pypdf
                reader = pypdf.PdfReader(io.BytesIO(file_bytes))
                text = "\n".join(page.extract_text() or "" for page in reader.pages)
            except Exception as e:
                errors.append(f"pypdf: {e}")

        if not text.strip():
            detail = "; ".join(errors) if errors else "no text layer (scanned image?)"
            raise ExtractionError(f"Could not extract text from PDF ({detail}). Try a text-based PDF or upload it as an image.")

        return sanitize_untrusted_text(mask_card_number(text))

    @classmethod
    def parse_dispute_notice(cls, text: str) -> Dict[str, Any]:
        """
        Parses key chargeback fields from bank dispute notice text.
        """
        data: Dict[str, Any] = {
            "case_id": None,
            "card_network": None,
            "reason_code": None,
            "reason_description": None,
            "disputed_amount": 0.0,
            "original_amount": 0.0,
            "currency": "USD",
            "transaction_date": None,
            "dispute_date": None,
            "response_deadline": None,
            "cardholder_name": None,
            "card_last_4": None,
            "arn": None,
            "raw_text": text,
        }

        data["case_id"] = _search(r'\b(?:Case|Dispute|Claim)\s*(?:Number|No\.?|ID|#)?\s*[:#]\s*([A-Z0-9][A-Z0-9\-_]{5,24})', text)

        if re.search(r'\b(Mastercard|Master Card)\b', text, re.I):
            data["card_network"] = "Mastercard"
        elif re.search(r'\b(American Express|Amex)\b', text, re.I):
            data["card_network"] = "American Express"
        elif re.search(r'\bDiscover\b', text, re.I):
            data["card_network"] = "Discover"
        elif re.search(r'\bVisa\b', text, re.I):
            data["card_network"] = "Visa"

        data["reason_code"] = _search(r'(?:Reason|Dispute)\s*Code\s*[:#]?\s*([A-Z]{0,4}\d{1,4}(?:\.\d{1,2})?)\b', text)
        data["reason_description"] = (
            _search(r'^(?:Dispute\s*)?Reason\s*:\s*(.+)$', text)
            or _search(r'Reason\s*Code\s*:?\s*[A-Z0-9.]+\s*[—–:-]\s*(.+)$', text)
        )

        amount = _search(r'(?:Disputed\s*Amount|Dispute\s*Amount|Amount\s*Disputed|Chargeback\s*Amount)\s*[:]?\s*' + _MONEY, text)
        if amount is None:
            amount = _search(r'\$\s*([0-9][0-9,]*\.[0-9]{2})', text)
        data["disputed_amount"] = _to_amount(amount)

        original = _search(r'(?:Original|Transaction)\s*(?:Amount|Charge)\s*[:]?\s*' + _MONEY, text)
        data["original_amount"] = _to_amount(original) if original else data["disputed_amount"]

        data["cardholder_name"] = _search(r'^(?:Cardholder|Cardmember|Customer|Guest)(?:\s*Name)?\s*:\s*([A-Za-z][A-Za-z.\'\- ]+?)\s*$', text)
        data["card_last_4"] = _find_last4(text)

        data["transaction_date"] = _search(r'(?:Transaction|Trans\.?)\s*Date\s*[:]?\s*' + _DATE, text)
        data["dispute_date"] = _search(r'(?:Dispute|Notice)(?:\s*/\s*Dispute)?\s*Date\s*[:]?\s*' + _DATE, text)
        data["response_deadline"] = _search(r'(?:Response\s*(?:Due\s*)?(?:Deadline|Date)|Due\s*Date|Respond\s*By)\s*[:]?\s*' + _DATE, text)
        data["arn"] = _search(r'(?:\bARN\b\)?|Acquirer\s*Ref(?:\.|erence)?\s*(?:Number|No\.?)?(?:\s*\(ARN\))?)\s*[:]?\s*(\d{15,25})\b', text)

        return data

    @classmethod
    def parse_folio_pdf(cls, text: str) -> Dict[str, Any]:
        """
        Parses hotel folio data from extracted PDF text.
        """
        folio: Dict[str, Any] = {
            "hotel_name": None,
            "hotel_address": None,
            "guest_name": None,
            "folio_number": None,
            "room_number": None,
            "check_in": None,
            "check_out": None,
            "rate_per_night": 0.0,
            "total_charges": 0.0,
            "total_payments": 0.0,
            "balance": 0.0,
            "card_last_4": None,
            "auth_code": None,
            "line_items": [],
            "raw_text": text,
        }

        folio["hotel_name"] = _search(r'^(?:Hotel|Property|Merchant)(?:\s*Name)?\s*:\s*(.+)$', text)
        if not folio["hotel_name"]:
            # Fall back to the first non-empty line if it looks like a heading (e.g. "GRAND HORIZON RESORT & SUITES")
            first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            if re.search(r'\b(hotel|resort|inn|suites|lodge)\b', first_line, re.I):
                folio["hotel_name"] = first_line.title()

        # Stop the name before a following "Label:" on the same line (PDF tables often flatten into one line)
        folio["guest_name"] = _search(r'\bGuest\s*Name\s*:\s*(.+?)(?=\s+[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?\s*:|\s*$)', text)
        folio["folio_number"] = _search(r'\b(?:Folio|Invoice|Reservation)\s*(?:Number|No\.?|#|ID)\s*:?\s*([A-Z0-9][A-Z0-9\-]{3,})', text)
        folio["room_number"] = _search(r'\b(?:Room\s*(?:Number|No\.?|#)|Rm\.?)\s*:?\s*([A-Z]?\d{1,5}[A-Z]?)\b', text)
        folio["check_in"] = _search(r'\b(?:Arrival(?:\s*Date)?|Check-?\s?in(?:\s*Date)?)\s*:?\s*' + _DATE, text)
        folio["check_out"] = _search(r'\b(?:Departure(?:\s*Date)?|Check-?\s?out(?:\s*Date)?)\s*:?\s*' + _DATE, text)
        folio["card_last_4"] = _find_last4(text)
        folio["auth_code"] = _search(r'\b(?:Auth(?:orization)?(?:\s*Code)?|Appr(?:oval)?(?:\s*Code)?)\s*[:#]?\s*([A-Z0-9]*\d[A-Z0-9]*)\b', text)

        charges = _search(r'(?:Total\s*Charges|Total\s*Amount|Grand\s*Total)\s*:?\s*' + _MONEY, text)
        payments = _search(r'(?:Total\s*Payments|Total\s*Credits|Amount\s*Paid)\s*:?\s*' + _MONEY, text)
        folio["total_charges"] = _to_amount(charges)
        folio["total_payments"] = _to_amount(payments)

        line_items = []
        item_re = re.compile(r'^\s*(\d{1,2}[/-]\d{1,2}(?:[/-]\d{2,4})?|\d{4}-\d{2}-\d{2})\s+(.+?)\s+(-?\$?-?[0-9][0-9,]*\.[0-9]{2})\s*$')
        for line in text.splitlines():
            m_item = item_re.match(line)
            if not m_item:
                continue
            desc = m_item.group(2).strip()
            if any(skip in desc.lower() for skip in ("total", "balance", "subtotal")):
                continue
            amount = _to_amount(m_item.group(3).replace("-", ""))
            is_credit = "-" in m_item.group(3) or re.search(r'payment|credit|settlement|refund', desc, re.I)
            line_items.append({
                "date": m_item.group(1),
                "description": desc,
                "amount": amount,
                "type": "Credit" if is_credit else "Charge",
            })

        folio["line_items"] = line_items
        if line_items:
            if folio["total_charges"] == 0.0:
                folio["total_charges"] = round(sum(i["amount"] for i in line_items if i["type"] == "Charge"), 2)
            if folio["total_payments"] == 0.0:
                folio["total_payments"] = round(sum(i["amount"] for i in line_items if i["type"] == "Credit"), 2)
            folio["check_in"] = folio["check_in"] or line_items[0]["date"]
            folio["check_out"] = folio["check_out"] or line_items[-1]["date"]
        folio["balance"] = round(folio["total_charges"] - folio["total_payments"], 2)
        return folio

    @classmethod
    def parse_folio_csv(cls, file_bytes: bytes) -> Dict[str, Any]:
        """
        Parses itemized guest folio from standard CSV export (e.g., OPERA PMS, Cloudbeds, Mews).
        Header metadata not present in the CSV (guest, room, card) is left as None for staff to complete.
        """
        try:
            df = pd.read_csv(io.BytesIO(file_bytes), encoding="utf-8-sig", dtype=str)
        except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as e:
            raise ExtractionError(f"Could not parse CSV folio: {e}") from e

        # Normalize column headers (first matching column wins for each canonical name)
        col_map: Dict[str, str] = {}
        rules = [
            ("date", ("date",)),
            ("description", ("desc", "item", "particular")),
            ("credit", ("credit", "payment")),
            ("amount", ("amount", "charge", "debit")),
            ("reference", ("voucher", "ref")),
        ]
        for col in df.columns:
            clean = str(col).strip().lower()
            for canonical, keywords in rules:
                if canonical not in col_map.values() and any(k in clean for k in keywords):
                    col_map[col] = canonical
                    break
        df = df.rename(columns=col_map)

        if "amount" not in df.columns and "credit" not in df.columns:
            raise ExtractionError("CSV folio needs an amount/charge or credit/payment column.")

        line_items = []
        total_charges = 0.0
        total_payments = 0.0

        for _, row in df.iterrows():
            desc = sanitize_untrusted_text(mask_card_number(str(row.get("description") or "Hotel Charge")))
            date_val = str(row.get("date") or "").strip() or None
            credit_val = _to_amount(row.get("credit"))
            charge_val = _to_amount(row.get("amount"))

            is_credit = credit_val > 0 or charge_val < 0 or bool(re.search(r'payment|credit|settlement|refund', desc, re.I))
            if is_credit:
                amt = credit_val if credit_val > 0 else abs(charge_val)
                total_payments += amt
            else:
                amt = charge_val
                total_charges += amt

            line_items.append({
                "date": date_val,
                "description": desc,
                "amount": round(amt, 2),
                "type": "Credit" if is_credit else "Charge",
            })

        dated = [i["date"] for i in line_items if i["date"]]
        return {
            "hotel_name": None,
            "hotel_address": None,
            "guest_name": None,
            "folio_number": None,
            "room_number": None,
            "check_in": dated[0] if dated else None,
            "check_out": dated[-1] if dated else None,
            "rate_per_night": 0.0,
            "total_charges": round(total_charges, 2),
            "total_payments": round(total_payments, 2),
            "balance": round(total_charges - total_payments, 2),
            "card_last_4": None,
            "auth_code": None,
            "line_items": line_items,
            "raw_text": f"CSV import with {len(line_items)} entries",
        }
