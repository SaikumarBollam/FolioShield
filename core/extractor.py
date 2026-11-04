"""
Document Extraction Pipeline for FolioShield.
Extracts structured transaction information from bank dispute notices and guest folios (PDF, CSV).
Uses deterministic regex and table parsers; visual records are handled by the Llama Vision hooks
in core.llm_engine. Fields that cannot be found are returned as None — values are never invented.

Phase 1 (Collection) coverage:
  * Notice: case ID, network, reason code, amounts, dates, deadline, cardholder,
    last-4, ARN (validated as 23 digits), the cardholder's claim statement,
    dispute stage, processor, statement descriptor and merchant ID.
  * Folio (PDF/CSV): property name/address, guest, folio/confirmation numbers,
    room, stay dates + times, rate/night + rate plan, itemized lines with
    category and voucher reference preserved, totals, balance, auth detail
    (auth code, AVS/CVV, 3-D Secure/ECI, entry mode), booking channel/source,
    stay status, cancellation and refund detail.
  * Scanned (image-only) PDFs raise ExtractionError with OCR guidance; callers
    may pass OCR/vision text via parse_* on the recognized text.
"""

import io
import logging
import re
from typing import Any, Callable, Dict, List, Optional

import pandas as pd

from .security import mask_card_number, sanitize_untrusted_text

logger = logging.getLogger(__name__)

_DATE = r'(\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\d{4}-\d{2}-\d{2}|[A-Za-z]{3,9}\.?\s+\d{1,2},?\s+\d{4})'
_MONEY = r'\$?\s*([0-9][0-9,]*\.[0-9]{2})'
_TIME = r'(\d{1,2}:\d{2}\s*(?:[AaPp]\.?[Mm]\.?)?)'

# Folio line-item category keywords (first match wins).
_CATEGORY_RULES: List[tuple] = [
    (re.compile(r'refund|credit issued', re.I), "Refund"),
    (re.compile(r'payment|settlement|deposit applied', re.I), "Payment"),
    (re.compile(r'room|accommodation|lodging|night stay|suite|no-?show', re.I), "Room"),
    (re.compile(r'tax|vat|occupancy.*fee|tourism', re.I), "Tax"),
    (re.compile(r'resort|amenity|destination fee|facility fee', re.I), "Resort Fee"),
    (re.compile(r'dining|restaurant|grill|breakfast|lunch|dinner|room service|in-room dining|cafe|coffee', re.I), "Dining"),
    (re.compile(r'\bbar\b|lounge|cocktail|wine|beer|liquor|minibar|mini-bar', re.I), "Bar"),
    (re.compile(r'spa|massage|salon|cabana', re.I), "Spa"),
    (re.compile(r'valet', re.I), "Valet"),
    (re.compile(r'parking|garage', re.I), "Parking"),
    (re.compile(r'damage|smoking|cleaning fee|incident', re.I), "Damage"),
    (re.compile(r'fee|surcharge|service charge', re.I), "Fee"),
]


def categorize_line_item(description: str, item_type: str = "Charge") -> str:
    """Classifies a folio line item into a canonical category."""
    desc = description or ""
    for pattern, category in _CATEGORY_RULES:
        if pattern.search(desc):
            # Minibar reads as Bar in the keyword pass; keep it distinct.
            if category == "Bar" and re.search(r'mini\s?-?bar', desc, re.I):
                return "Minibar"
            return category
    return "Other" if item_type == "Charge" else "Payment"


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
    """Return regex group 1, or None when there is no match/group value.

    Some folio layouts make a capture group optional in practice (for
    example, a label is present but its value is blank or split by PDF text
    extraction). Never let that turn into AttributeError during upload.
    """
    if not text:
        return None
    m = re.search(pattern, text, flags)
    if not m:
        return None
    try:
        value = m.group(1)
    except (IndexError, AttributeError):
        return None
    return value.strip() if isinstance(value, str) and value.strip() else None


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


def _clean_claim(raw: Optional[str]) -> Optional[str]:
    """Normalizes a captured cardholder claim statement."""
    if not raw:
        return None
    text = re.sub(r'\s+', ' ', raw).strip().strip('\'"“”')
    # Cut trailing boilerplate that often follows the quoted statement.
    text = re.split(r'\s+(?:Please|We request|Respond|Response|Dear|Merchant:)\b', text)[0].strip()
    return text[:1000] or None


def _infer_dispute_stage(text: str, reason_code: Optional[str]) -> Optional[str]:
    """Infers the dispute lifecycle stage from notice wording / Amex inquiry codes."""
    lowered = text.lower()
    if re.search(r'second chargeback|2nd chargeback', lowered):
        return "second_chargeback"
    if re.search(r'pre-?arbitration|pre-?arb\b', lowered):
        return "pre_arbitration"
    if re.search(r'\barbitration\b', lowered):
        return "arbitration"
    if re.search(r'retrieval request|information request|inquiry|request for information|\bRFI\b', lowered):
        return "inquiry"
    if reason_code and reason_code.strip().upper().startswith("R") and re.search(r'american express|amex', lowered):
        return "inquiry"  # Amex R-codes are inquiry (RFI) reason codes
    if re.search(r'chargeback|dispute notification|dispute record', lowered):
        return "chargeback"
    return None


def _infer_booking_channel(text: str) -> Optional[str]:
    """Infers booking channel from folio/confirmation wording."""
    lowered = text.lower()
    if re.search(r'booking\.com|expedia|hotels\.com|agoda|orbitz|travelocity|\bota\b|virtual card|\bvcc\b', lowered):
        return "ota"
    if re.search(r'\bgds\b|sabre|amadeus|travelport', lowered):
        return "gds"
    if re.search(r'walk-?in', lowered):
        return "walk_in"
    if re.search(r'corporate|company account|direct bill', lowered):
        return "corporate"
    if re.search(r'website|online booking|book direct|mobile app', lowered):
        return "direct_web"
    if re.search(r'phone|telephone|call center|reservations desk', lowered):
        return "direct_phone"
    return None


def _infer_stay_status(text: str, line_items: List[Dict[str, Any]]) -> Optional[str]:
    """Infers stay status; never fabricates occupancy for no-show/cancelled folios.

    An explicit ``Stay Status:`` field wins over keyword inference: folio
    boilerplate (cancellation-policy wording, refund language) must not turn
    an occupied stay into a cancelled one.
    """
    explicit = _search(r'\bStay\s*Status\s*:?\s*([A-Za-z][A-Za-z _-]*)', text)
    if explicit:
        normalized = explicit.strip().lower().replace("-", "_").replace(" ", "_")
        mapping = {
            "occupied": "occupied", "checked_in": "occupied", "checked_out": "occupied",
            "in_house": "occupied", "cancelled": "cancelled", "canceled": "cancelled",
            "no_show": "no_show", "noshow": "no_show",
            "early_departure": "early_departure", "day_use": "day_use",
        }
        if normalized in mapping:
            return mapping[normalized]
    lowered = text.lower()
    if re.search(r'no-?show', lowered):
        return "no_show"
    if re.search(r'cancelled|canceled|cancellation', lowered) and not re.search(r'checked[\s-]?in|registration', lowered):
        return "cancelled"
    if re.search(r'early departure|early check-?out|departed early', lowered):
        return "early_departure"
    if re.search(r'day use', lowered):
        return "day_use"
    if line_items:
        return "occupied"
    return None


class DocumentExtractor:
    """
    Handles extraction from Bank Dispute Notices and Hotel Guest Folios.
    """

    @staticmethod
    def pdf_first_page_to_image(file_bytes: bytes, zoom: float = 2.0) -> bytes:
        """
        Renders the first page of a PDF to PNG bytes for vision analysis.

        Uses pypdfium2 (installed with the `streamlit[pdf]` extra), falling
        back to PyMuPDF when available. Raises ExtractionError with install
        guidance when no renderer is available or the PDF has no pages —
        it never fabricates an image.
        """
        try:
            import pypdfium2 as pdfium
        except ImportError:
            pdfium = None
        if pdfium is not None:
            try:
                doc = pdfium.PdfDocument(file_bytes)
                try:
                    if len(doc) == 0:
                        raise ExtractionError("The uploaded PDF has no pages to analyze.")
                    page = doc[0]
                    try:
                        bitmap = page.render(scale=zoom)
                        try:
                            image = bitmap.to_pil()
                        finally:
                            bitmap.close()
                    finally:
                        page.close()
                finally:
                    doc.close()
                import io

                buffer = io.BytesIO()
                image.save(buffer, format="PNG")
                return buffer.getvalue()
            except ExtractionError:
                raise
            except Exception as exc:
                raise ExtractionError(
                    f"Could not render the PDF first page for vision analysis: {exc}"
                ) from exc
        try:
            import fitz  # PyMuPDF
        except ImportError as exc:
            raise ExtractionError(
                "PDF vision preview requires a PDF renderer. Install it with: "
                'pip install "streamlit[pdf]" (or pip install PyMuPDF), then retry. '
                "Image uploads (PNG/JPG) work without it."
            ) from exc
        try:
            doc = fitz.open(stream=file_bytes, filetype="pdf")
            if doc.page_count == 0:
                raise ExtractionError("The uploaded PDF has no pages to analyze.")
            page = doc.load_page(0)
            pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
            return pix.tobytes("png")
        except ExtractionError:
            raise
        except Exception as exc:
            raise ExtractionError(f"Could not render the PDF first page for vision analysis: {exc}") from exc

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

    @staticmethod
    def extract_text_with_ocr_fallback(
        file_bytes: bytes,
        ocr_text_provider: Optional[Callable[[bytes], Optional[str]]] = None,
    ) -> str:
        """
        Extracts PDF text, falling back to an OCR/vision provider for scanned notices.

        `ocr_text_provider` receives the raw PDF bytes and returns recognized text
        (e.g. from a vision model). Without a provider, the original
        ExtractionError guidance is raised unchanged.
        """
        try:
            return DocumentExtractor.extract_text_from_pdf(file_bytes)
        except ExtractionError:
            if ocr_text_provider is None:
                raise
            recognized = ocr_text_provider(file_bytes)
            if recognized and recognized.strip():
                return sanitize_untrusted_text(mask_card_number(recognized))
            raise ExtractionError(
                "Could not extract text from PDF and OCR fallback produced no text. "
                "Upload a clearer scan or a text-based PDF."
            )

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
            "claim_statement": None,
            "dispute_stage": None,
            "processor": None,
            "statement_descriptor": None,
            "merchant_id": None,
            "prior_case_id": None,
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

        currency = _search(r'\b(USD|EUR|GBP|CAD|AUD|JPY|INR|AED)\b', text)
        if currency:
            data["currency"] = currency.upper()

        data["cardholder_name"] = _search(r'^(?:Cardholder|Cardmember|Customer|Guest)(?:\s*Name)?\s*:\s*([A-Za-z][A-Za-z.\'\- ]+?)\s*$', text)
        data["card_last_4"] = _find_last4(text)

        data["transaction_date"] = _search(r'(?:Transaction|Trans\.?)\s*Date\s*[:]?\s*' + _DATE, text)
        data["dispute_date"] = _search(r'(?:Dispute|Notice)(?:\s*/\s*Dispute)?\s*Date\s*[:]?\s*' + _DATE, text)
        data["response_deadline"] = _search(r'(?:Response\s*(?:Due\s*)?(?:Deadline|Date)|Due\s*Date|Respond\s*By)\s*[:]?\s*' + _DATE, text)

        # ARN: prefer an exact 23-digit acquirer reference; keep shorter/longer
        # candidates so staff can correct them (the reconciler flags non-23-digit ARNs).
        data["arn"] = (
            _search(r'(?:\bARN\b\)?|Acquirer\s*Ref(?:\.|erence)?\s*(?:Number|No\.?)?(?:\s*\(ARN\))?)\s*[:]?\s*(\d{23})\b', text)
            or _search(r'(?:\bARN\b\)?|Acquirer\s*Ref(?:\.|erence)?\s*(?:Number|No\.?)?(?:\s*\(ARN\))?)\s*[:]?\s*(\d{15,25})\b', text)
        )

        # The cardholder's own claim — the single most important rebuttal input.
        data["claim_statement"] = _clean_claim(
            _search(r'(?:Cardholder|Cardmember|Customer)\s*(?:Statement|Claim|Remarks?|Comments?)\s*[:\-]\s*[\'"]?(.+?)[\'"]?\s*$', text)
            or _search(r'(?:Cardholder|Cardmember)\s+(?:claims?|states?|alleges?|reports?)\s+(?:that\s+)?(.+?)\s*$', text)
        )

        data["dispute_stage"] = _infer_dispute_stage(text, data["reason_code"])
        data["processor"] = _search(r'^(?:Processor|Acquirer|Issuing\s*Bank|Bank)\s*:\s*(.+)$', text)
        data["statement_descriptor"] = _search(r'(?:Statement\s*)?Descriptor\s*:\s*(.+)$', text)
        data["merchant_id"] = _search(r'(?:Merchant\s*(?:ID|Number|No\.?|#)|MID)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{4,24})', text)
        data["prior_case_id"] = _search(r'(?:Prior|Previous|Original|Related)\s*(?:Case|Dispute)\s*(?:Number|No\.?|ID|#)?\s*[:#]\s*([A-Z0-9][A-Z0-9\-_]{5,24})', text)

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
            "merchant_id": None,
            "confirmation_number": None,
            "booking_channel": None,
            "booking_source": None,
            "booking_date": None,
            "stay_status": None,
            "check_in_time": None,
            "check_out_time": None,
            "rate_plan": None,
            "num_guests": None,
            "guest_email": None,
            "guest_phone": None,
            "payer_name": None,
            "payer_relationship": None,
            "avs_result": None,
            "cvv_result": None,
            "three_ds_status": None,
            "three_ds_eci": None,
            "entry_mode": None,
            "terminal_id": None,
            "auth_amount": 0.0,
            "auth_date": None,
            "refund_amount": 0.0,
            "refund_date": None,
            "refund_reference": None,
            "cancellation_timestamp": None,
            "cancellation_number": None,
            "line_items": [],
            "raw_text": text,
        }

        folio["hotel_name"] = _search(r'^(?:Hotel|Property|Merchant)(?:\s*Name)?\s*:\s*(.+)$', text)
        if not folio["hotel_name"]:
            # Fall back to the first non-empty line if it looks like a heading (e.g. "GRAND HORIZON RESORT & SUITES")
            first_line = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
            if re.search(r'\b(hotel|resort|inn|suites|lodge)\b', first_line, re.I):
                folio["hotel_name"] = first_line.title()

        folio["hotel_address"] = _search(r'^(?:Hotel\s*)?Address\s*:\s*(.+)$', text)
        if not folio["hotel_address"] and folio["hotel_name"]:
            # Many folio headers print "Hotel Name, Street, City ST ZIP" on one line.
            m_addr = re.search(re.escape(folio["hotel_name"]) + r'\s*,\s*(.+\d{5}(?:-\d{4})?)\s*$', text, re.I | re.M)
            if m_addr:
                folio["hotel_address"] = m_addr.group(1).strip()

        # Stop the name before a following "Label:" on the same line (PDF tables often flatten into one line)
        folio["guest_name"] = _search(r'\bGuest\s*Name\s*:\s*(.+?)(?=\s+[A-Z][A-Za-z]*(?:\s+[A-Z][A-Za-z]*)?\s*:|\s*$)', text)
        folio["folio_number"] = _search(r'\b(?:Folio|Invoice)\s*(?:Number|No\.?|#|ID)\s*:?\s*([A-Z0-9][A-Z0-9\-]{3,})', text)
        folio["confirmation_number"] = _search(r'\b(?:Confirmation|Reservation|Booking)\s*(?:Number|No\.?|#|ID|Code)\s*:?\s*([A-Z0-9][A-Z0-9\-]{3,})', text)
        folio["room_number"] = _search(r'\bRoom\s*(?:Number|No\.?|#)?\s*:?\s*([A-Za-z][A-Za-z ]*\d+[A-Za-z]?|\d{1,5}[A-Za-z]?)\b', text)
        if not folio["room_number"]:
            folio["room_number"] = _search(r'\bRoom\s*:?\s*([A-Z]?\d{1,5}[A-Z]?)\b', text)
        folio["check_in"] = _search(r'\b(?:Arrival(?:\s*Date)?|Check-?\s?in(?:\s*Date)?)\s*:?\s*' + _DATE, text)
        folio["check_out"] = _search(r'\b(?:Departure(?:\s*Date)?|Check-?\s?out(?:\s*Date)?)\s*:?\s*' + _DATE, text)
        folio["check_in_time"] = _search(r'\bCheck-?\s?in\s*Time\s*:?\s*' + _TIME, text)
        folio["check_out_time"] = _search(r'\bCheck-?\s?out\s*Time\s*:?\s*' + _TIME, text)
        folio["card_last_4"] = _find_last4(text)
        folio["auth_code"] = _search(r'\b(?:Auth(?:orization)?(?:\s*Code)?|Appr(?:oval)?(?:\s*Code)?)\s*[:#]?\s*([A-Z0-9]*\d[A-Z0-9]*)\b', text)
        folio["merchant_id"] = _search(r'(?:Merchant\s*(?:ID|Number|No\.?|#)|MID)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{4,24})', text)

        rate = _search(r'(?:Rate(?:\s*per\s*Night)?|Nightly\s*Rate|Room\s*Rate)\s*[:]?\s*' + _MONEY, text)
        folio["rate_per_night"] = _to_amount(rate)
        folio["rate_plan"] = _search(r'^(?:Rate\s*Plan|Rate\s*Type|Package)\s*:\s*(.+)$', text)
        folio["booking_source"] = _search(r'^(?:Booking\s*Source|Source|Channel|Booked\s*(?:Via|Through))\s*:\s*(.+)$', text)
        folio["booking_channel"] = _infer_booking_channel(" ".join(filter(None, [folio["booking_source"], text[:2000]])))
        folio["booking_date"] = _search(r'\b(?:Booking|Reservation|Booked)\s*Date\s*:?\s*' + _DATE, text)
        guests = _search(r'\b(?:Guests?|Occupants?|Adults)\s*:?\s*(\d{1,2})\b', text)
        folio["num_guests"] = int(guests) if guests and guests.isdigit() else None
        folio["guest_email"] = _search(r'\b([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7})\b', text)
        folio["payer_name"] = _search(r'^(?:Payer|Paid\s*By|Billed\s*To|Cardholder)\s*:\s*(.+)$', text)
        if folio["payer_name"] and folio["guest_name"] and folio["payer_name"].strip().lower() != folio["guest_name"].strip().lower():
            folio["payer_relationship"] = "Third-party payer (see booking source)"

        folio["avs_result"] = _search(r'\bAVS\s*(?:Result|Response|Code)?\s*[:#]?\s*([A-Z](?:\s*[-–]\s*[A-Za-z ]+)?)', text)
        folio["cvv_result"] = _search(r'\b(?:CVV2?|CVC2?|CID)\s*(?:Result|Response)?\s*[:#]?\s*(Match|No\s*Match|Not\s*Provided|[A-Z])\b', text)
        if re.search(r'3D\s*Secure\s*[:\-]?\s*(Authenticated|Successful|Passed)', text, re.I):
            folio["three_ds_status"] = "authenticated"
        elif re.search(r'3D\s*Secure\s*[:\-]?\s*(Attempted|Liability\s*Shift)', text, re.I):
            folio["three_ds_status"] = "attempted"
        elif re.search(r'3D\s*Secure\s*[:\-]?\s*(Not\s*Authenticated|Failed|None)', text, re.I):
            folio["three_ds_status"] = "not_authenticated"
        folio["three_ds_eci"] = _search(r'\bECI\s*[:#]?\s*(\d{2})\b', text)
        entry = _search(r'\b(?:Entry\s*Mode|Card\s*Entry|POS\s*Entry)\s*[:#]?\s*(Chip|Contactless|Swipe|Keyed|E-?commerce|Recurring|Manual)', text)
        if entry:
            folio["entry_mode"] = entry.lower().replace("-", "")
        folio["terminal_id"] = _search(r'\b(?:Terminal|TID)\s*(?:ID)?\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{3,})', text)
        auth_amt = _search(r'(?:Auth(?:orized)?\s*Amount|Authorization\s*Amount)\s*[:]?\s*' + _MONEY, text)
        folio["auth_amount"] = _to_amount(auth_amt)
        folio["auth_date"] = _search(r'\bAuth(?:orization)?\s*Date\s*:?\s*' + _DATE, text)

        refund_amt = _search(r'(?:Refund(?:ed)?\s*(?:Amount)?|Credit\s*Issued)\s*[:]?\s*' + _MONEY, text)
        folio["refund_amount"] = _to_amount(refund_amt)
        folio["refund_date"] = _search(r'\bRefund\s*Date\s*:?\s*' + _DATE, text)
        folio["refund_reference"] = _search(r'\bRefund\s*(?:Reference|Ref\.?|ARN|ID)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{4,})', text)
        folio["cancellation_timestamp"] = _search(r'\bCancell(?:ation|ed)\s*(?:On|Date|Timestamp)?\s*:?\s*' + _DATE + r'(?:\s+' + _TIME + r')?', text)
        folio["cancellation_number"] = _search(r'\bCancellation\s*(?:Number|No\.?|#|Code|ID)\s*:?\s*([A-Z0-9][A-Z0-9\-]{3,})', text)

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
            is_credit = "-" in m_item.group(3) or re.search(r'payment|credit|settlement|\brefund(?:ed|s|ing)?\b', desc, re.I) and not re.search(r'non-refundable', desc, re.I)
            item_type = "Credit" if is_credit else "Charge"
            # Preserve a trailing voucher/reference token (e.g. "POS-9812", "#4102").
            ref_match = re.search(r'\b(?:Ref\.?|Voucher|Slip|Check|Auth)[:#]?\s*([A-Z0-9][A-Z0-9\-]{2,})\s*$', desc, re.I) or re.search(r'\(([A-Z0-9\-]{3,})\)\s*$', desc)
            # Explicit disputed markers from PMS/folio exports.
            is_disputed = bool(re.search(r'\[DISPUTED[^\]]*\]|\bDISPUTED\b', desc, re.I)) or None
            clean_desc = re.sub(r'\s*\[DISPUTED[^\]]*\]\s*', ' ', desc, flags=re.I).strip()
            clean_desc = re.sub(r'\s+\bDISPUTED\b\s*$', '', clean_desc, flags=re.I).strip()
            line_items.append({
                "date": m_item.group(1),
                "description": clean_desc or desc,
                "amount": amount,
                "type": item_type,
                "reference": ref_match.group(1) if ref_match else None,
                "category": categorize_line_item(clean_desc or desc, item_type),
                "disputed": is_disputed,
            })

        # Multi-line (column-flattened) folio tables: PDF text extraction often
        # puts date / description / reference / category / amount on separate
        # lines, so the single-line regex above finds nothing. Reassemble
        # records anchored on each date line: description lines (possibly
        # wrapping, e.g. a "[DISPUTED TEST LINE]" marker), then reference,
        # category, and finally the amount line.
        if not line_items:
            flat = [ln.strip() for ln in text.splitlines() if ln.strip()]
            date_re = re.compile(r'^\d{4}-\d{2}-\d{2}$|^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}$')
            amount_re = re.compile(r'^-?\$?-?[0-9][0-9,]*\.[0-9]{2}$')
            ref_re = re.compile(r'^[A-Z]{2,}[A-Z0-9]*-[A-Z0-9\-]+$|^[A-Z0-9]{4,}$')
            i = 0
            while i < len(flat):
                if not date_re.match(flat[i]):
                    i += 1
                    continue
                # Collect lines until the amount line (max 6 lines ahead).
                j = i + 1
                while j < len(flat) and j <= i + 6 and not amount_re.match(flat[j]) and not date_re.match(flat[j]):
                    j += 1
                if j >= len(flat) or not amount_re.match(flat[j]) or j == i + 1:
                    i += 1
                    continue
                middle = flat[i + 1:j]
                amount_text = flat[j]
                # Reference/category are the trailing non-description lines.
                ref_val = None
                cat_val = None
                desc_lines = list(middle)
                if len(middle) >= 3 and ref_re.match(middle[-2]):
                    ref_val = middle[-2]
                    cat_val = middle[-1]
                    desc_lines = middle[:-2]
                elif len(middle) >= 2 and ref_re.match(middle[-1]):
                    ref_val = middle[-1]
                    desc_lines = middle[:-1]
                desc = " ".join(desc_lines).strip()
                if any(skip in desc.lower() for skip in ("total", "balance", "subtotal")):
                    i = j + 1
                    continue
                # Header metadata lines (e.g. "Booking Date:" followed by a
                # rate line ending in the nightly rate) are not charges.
                if re.search(r':\s*$', desc) or re.match(
                        r'(?i)^(booking|reservation|rate plan|rate per night|guest|folio|room|arrival|departure|stay|check|merchant|auth|avs|cvv|entry|cancellation|refund|payer|confirmation)\b', desc):
                    i = j + 1
                    continue
                amount = _to_amount(amount_text.replace("-", ""))
                is_credit = "-" in amount_text or bool(re.search(r'payment|credit|settlement|\brefund(?:ed|s|ing)?\b', desc, re.I)) and not bool(re.search(r'non-refundable', desc, re.I))
                item_type = "Credit" if is_credit else "Charge"
                is_disputed = bool(re.search(r'\[DISPUTED[^\]]*\]|\bDISPUTED\b', desc, re.I)) or None
                clean_desc = re.sub(r'\s*\[DISPUTED[^\]]*\]\s*', ' ', desc, flags=re.I).strip()
                line_items.append({
                    "date": flat[i],
                    "description": clean_desc or desc,
                    "amount": amount,
                    "type": item_type,
                    "reference": ref_val,
                    "category": cat_val or categorize_line_item(clean_desc or desc, item_type),
                    "disputed": is_disputed,
                })
                i = j + 1

        folio["line_items"] = line_items
        if line_items:
            if folio["total_charges"] == 0.0:
                total_c = 0.0
                for it in line_items:
                    if it.get("type") == "Charge":
                        try:
                            total_c += float(it.get("amount") or 0.0)
                        except (ValueError, TypeError):
                            pass
                folio["total_charges"] = round(total_c, 2)
            if folio["total_payments"] == 0.0:
                total_p = 0.0
                for it in line_items:
                    if it.get("type") == "Credit":
                        try:
                            total_p += float(it.get("amount") or 0.0)
                        except (ValueError, TypeError):
                            pass
                folio["total_payments"] = round(total_p, 2)
            if folio["rate_per_night"] == 0.0:
                room_rates = [i["amount"] for i in line_items if i.get("category") == "Room"]
                if room_rates:
                    folio["rate_per_night"] = room_rates[0]
            # Stay-window fallback only for stays that actually happened.
            status = _infer_stay_status(text, line_items)
            folio["stay_status"] = status
            if status in ("occupied", "early_departure", "day_use", None):
                folio["check_in"] = folio["check_in"] or line_items[0]["date"]
                folio["check_out"] = folio["check_out"] or line_items[-1]["date"]
        else:
            folio["stay_status"] = _infer_stay_status(text, line_items)
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

        # Normalize column headers. Exact canonical names win before keyword
        # matching so a "Credit" column cannot be shadowed by another header.
        col_map: Dict[str, str] = {}
        exact = {"date": "date", "description": "description", "desc": "description",
                 "credit": "credit", "payment": "credit", "charge": "amount",
                 "amount": "amount", "debit": "amount", "reference": "reference",
                 "category": "category", "disputed": "disputed", "contested": "disputed"}
        for col in df.columns:
            canonical = exact.get(str(col).strip().lower())
            if canonical and canonical not in col_map.values():
                col_map[col] = canonical
        rules = [
            ("date", ("date",)),
            ("description", ("desc", "item", "particular")),
            ("credit", ("credit", "payment")),
            ("amount", ("amount", "charge", "debit")),
            ("reference", ("voucher", "ref", "slip", "check")),
            ("category", ("category", "dept", "department")),
        ]
        for col in df.columns:
            if col in col_map:
                continue
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
            reference = str(row.get("reference") or "").strip() or None
            if reference and reference.lower() in ("nan", "none", "0", "0.0"):
                reference = None

            is_credit_desc = bool(re.search(r'payment|credit|settlement|\brefund(?:ed|s|ing)?\b', desc, re.I)) and not bool(re.search(r'non-refundable', desc, re.I))
            is_credit = credit_val > 0 or charge_val < 0 or is_credit_desc
            is_refund = bool(re.search(r'\brefund(?:ed|s|ing)?\b', desc, re.I)) and not bool(re.search(r'non-refundable', desc, re.I))
            if is_credit:
                amt = credit_val if credit_val > 0 else abs(charge_val)
                if not is_refund:
                    total_payments += amt
            else:
                amt = charge_val
                total_charges += amt

            item_type = "Credit" if is_credit else "Charge"
            category = str(row.get("category") or "").strip() or categorize_line_item(desc, item_type)
            # Explicit disputed markers from PMS exports (e.g. a "Disputed"
            # column or a [DISPUTED] tag in the description).
            disputed_raw = str(row.get("disputed") or "").strip().lower()
            is_disputed = True if disputed_raw in ("true", "yes", "y", "1", "disputed") else (
                bool(re.search(r'\[DISPUTED[^\]]*\]|\bDISPUTED\b', desc, re.I)) or None)
            clean_desc = re.sub(r'\s*\[DISPUTED[^\]]*\]\s*', ' ', desc, flags=re.I).strip()
            line_items.append({
                "date": date_val,
                "description": clean_desc or desc,
                "amount": round(amt, 2),
                "type": item_type,
                "reference": reference,
                "category": category,
                "disputed": is_disputed,
            })

        dated = [i["date"] for i in line_items if i["date"]]
        room_rates = [i["amount"] for i in line_items if i.get("category") == "Room"]
        return {
            "hotel_name": None,
            "hotel_address": None,
            "guest_name": None,
            "folio_number": None,
            "room_number": None,
            "check_in": dated[0] if dated else None,
            "check_out": dated[-1] if dated else None,
            "rate_per_night": room_rates[0] if room_rates else 0.0,
            "total_charges": round(total_charges, 2),
            "total_payments": round(total_payments, 2),
            "balance": round(total_charges - total_payments, 2),
            "card_last_4": None,
            "auth_code": None,
            "merchant_id": None,
            "confirmation_number": None,
            "booking_channel": None,
            "booking_source": None,
            "booking_date": None,
            "stay_status": "occupied" if line_items else None,
            "check_in_time": None,
            "check_out_time": None,
            "rate_plan": None,
            "num_guests": None,
            "guest_email": None,
            "guest_phone": None,
            "payer_name": None,
            "payer_relationship": None,
            "avs_result": None,
            "cvv_result": None,
            "three_ds_status": None,
            "three_ds_eci": None,
            "entry_mode": None,
            "terminal_id": None,
            "auth_amount": 0.0,
            "auth_date": None,
            "refund_amount": 0.0,
            "refund_date": None,
            "refund_reference": None,
            "cancellation_timestamp": None,
            "cancellation_number": None,
            "line_items": line_items,
            "raw_text": f"CSV import with {len(line_items)} entries",
        }

    @classmethod
    def extract_evidence_details(cls, doc_type: str, filename: str, file_bytes: bytes) -> Dict[str, Any]:
        """
        Extracts probative evidence details from uploaded evidence files (CSV, EML, PDF, TXT).
        Only parses facts explicitly present in the file; never invents details.
        """
        details: Dict[str, Any] = {}
        fn = (filename or "").lower()

        text = ""
        if fn.endswith(".pdf"):
            try:
                text = cls.extract_text_from_pdf(file_bytes)
            except Exception:
                text = ""
        elif fn.endswith((".csv", ".txt", ".eml", ".log", ".json")):
            try:
                text = file_bytes.decode("utf-8", errors="replace")
            except Exception:
                text = ""

        # 1. Lock and WiFi logs (CSV, TXT, PDF)
        if doc_type in ("keycard_lock_audit", "wifi_usage_log"):
            ts_entries: List[str] = []
            if fn.endswith(".csv") or "," in text:
                import csv as _csv
                try:
                    reader = _csv.reader(io.StringIO(text))
                    header = next(reader, None)
                    if header:
                        ts_idx = 0
                        for idx, h in enumerate(header):
                            if any(k in h.lower() for k in ("time", "date", "ts")):
                                ts_idx = idx
                                break
                        for row in reader:
                            if row and len(row) > ts_idx:
                                val = row[ts_idx].strip()
                                if re.match(r'^\d{4}-\d{2}-\d{2}', val) or re.match(r'^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}', val):
                                    ts_entries.append(val)
                except Exception:
                    pass

            if not ts_entries and text:
                for line in text.splitlines():
                    m = re.search(r'\b(\d{4}-\d{2}-\d{2}(?:\s+\d{1,2}:\d{2}(?::\d{2})?)?)\b', line)
                    if m:
                        ts_entries.append(m.group(1).strip())

            m_first = re.search(r'(?:first_entry|first_seen|first\s*entry|first\s*seen)\s*[:=]?\s*["\']?([0-9]{4}-[0-9]{2}-[0-9]{2}[^"\'\r\n,]*)', text, re.I)
            m_last = re.search(r'(?:last_entry|last_seen|last\s*entry|last\s*seen)\s*[:=]?\s*["\']?([0-9]{4}-[0-9]{2}-[0-9]{2}[^"\'\r\n,]*)', text, re.I)

            if m_first:
                details["first_entry"] = m_first.group(1).strip()
                if doc_type == "wifi_usage_log":
                    details["first_seen"] = m_first.group(1).strip()
            elif ts_entries:
                details["first_entry"] = ts_entries[0]
                if doc_type == "wifi_usage_log":
                    details["first_seen"] = ts_entries[0]

            if m_last:
                details["last_entry"] = m_last.group(1).strip()
                if doc_type == "wifi_usage_log":
                    details["last_seen"] = m_last.group(1).strip()
            elif ts_entries:
                details["last_entry"] = ts_entries[-1]
                if doc_type == "wifi_usage_log":
                    details["last_seen"] = ts_entries[-1]

            m_entries = re.search(r'(?:entries|count)\s*[:=]?\s*(\d+)', text, re.I)
            if m_entries:
                details["entries"] = int(m_entries.group(1))
            elif ts_entries:
                details["entries"] = len(ts_entries)

        # 2. Booking confirmation (EML, TXT, PDF)
        elif doc_type == "booking_confirmation":
            m_rec = (re.search(r'(?:recipient|sent_to|sent\s*to)\s*[:=]?\s*["\']?([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', text, re.I)
                     or re.search(r'To:\s*(?:[^<\r\n]+<)?([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})', text, re.I))
            if m_rec:
                details["recipient"] = m_rec.group(1).strip()
            m_sent = (re.search(r'(?:sent_at|sent_timestamp|sent\s*at)\s*[:=]?\s*["\']?([^"\'\r\n]+)', text, re.I)
                      or re.search(r'Date:\s*([A-Za-z0-9, :+-]+)', text, re.I))
            if m_sent:
                details["sent_at"] = m_sent.group(1).strip()

        # 3. Cancellation policy acceptance (PDF, TXT)
        elif doc_type == "cancellation_policy_acceptance":
            m_acc = re.search(r'(?:accepted_at|acceptance_timestamp|clicked_at|accepted\s*at)\s*[:=]?\s*["\']?([^"\'\r\n]+)', text, re.I)
            if m_acc:
                details["accepted_at"] = m_acc.group(1).strip()
            m_pol = re.search(r'(?:policy_text|exact_text|policy\s*wording)\s*[:=]?\s*["\']?([^"\'\r\n]+)', text, re.I)
            if m_pol:
                details["policy_text"] = m_pol.group(1).strip()

        # 4. POS Signed Slips (PDF, TXT)
        elif doc_type == "pos_signed_slips":
            m_slips = re.search(r'\[\s*\{.*?"reference".*?\}\s*\]', text, re.S)
            if m_slips:
                try:
                    import json as _json
                    parsed = _json.loads(m_slips.group(0))
                    if isinstance(parsed, list) and parsed:
                        details["slips"] = parsed
                except Exception:
                    pass
            if "slips" not in details:
                m_ref = re.search(r'(?:slip_reference|slip_ref|reference)\s*[:=]?\s*["\']?([A-Za-z0-9\-]+)', text, re.I)
                m_amt = re.search(r'(?:slip\s*amount|amount)\s*[:=]?\s*["\']?\$?([0-9]+\.[0-9]{2})', text, re.I)
                if m_ref or m_amt:
                    ref_val = m_ref.group(1).strip() if m_ref else None
                    amt_val = float(m_amt.group(1)) if m_amt else None
                    if ref_val:
                        details["slip_reference"] = ref_val
                    if amt_val is not None:
                        details["amount"] = amt_val
                    details["slips"] = [{"reference": ref_val, "amount": amt_val}]

        # 5. AVS / CVV result
        elif doc_type == "avs_cvv_result":
            m_avs = re.search(r'\bAVS\s*(?:Result|Response|Code)?\s*[:=]?\s*([A-Za-z](?:\s*[-–]\s*[A-Za-z ]+)?)', text, re.I)
            if m_avs:
                details["avs_result"] = m_avs.group(1).strip()
            m_cvv = re.search(r'\b(?:CVV2?|CVC2?|CID)\s*(?:Result|Response)?\s*[:=]?\s*(Match|No\s*Match|Not\s*Provided|[A-Za-z])\b', text, re.I)
            if m_cvv:
                details["cvv_result"] = m_cvv.group(1).strip()

        # 6. Guest service log
        elif doc_type == "guest_service_log":
            m_unres = re.search(r'(?:unresolved_complaints|open_complaints|unresolved)\s*[:=]?\s*(\d+)', text, re.I)
            if m_unres:
                details["unresolved_complaints"] = int(m_unres.group(1))

        # 7. Refund credit receipt
        elif doc_type == "refund_credit_receipt":
            m_amt = re.search(r'(?:refund\s*amount|amount)\s*[:=]?\s*["\']?\$?([0-9]+\.[0-9]{2})', text, re.I)
            if m_amt:
                details["amount"] = float(m_amt.group(1))
            m_ref = re.search(r'(?:refund\s*reference|reference|ref)\s*[:=]?\s*["\']?([A-Za-z0-9\-]+)', text, re.I)
            if m_ref:
                details["reference"] = m_ref.group(1).strip()

        return details
