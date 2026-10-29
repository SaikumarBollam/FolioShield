"""
Security & Compliance Utilities for FolioShield
PCI-DSS credit card masking, PII scrubbing, upload validation, and prompt injection defense.
"""

import re
from typing import Any, Dict
from xml.sax.saxutils import escape as _xml_escape

# Regex to detect 13-19 digit card numbers (Visa, Mastercard, Amex, Discover)
CC_REGEX = re.compile(r'\b(?:\d[ -]*?){13,19}\b')

# Regex to detect email addresses
EMAIL_REGEX = re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,7}\b')

# Regex to detect potential prompt injection attacks in unstructured documents
INJECTION_PATTERNS = [
    re.compile(r'(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above)\s+instructions', re.IGNORECASE),
    re.compile(r'system\s+prompt', re.IGNORECASE),
    re.compile(r'you\s+are\s+now\s+(?:an?\s+)?unrestricted', re.IGNORECASE),
    re.compile(r'<script.*?>.*?</script>', re.IGNORECASE | re.DOTALL),
]

# Upload limits / signatures
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB
_MAGIC_BYTES = {
    "pdf": [b"%PDF"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
}


def mask_card_number(text: str) -> str:
    """
    Masks credit card numbers in compliance with PCI-DSS:
    Leaves only the last 4 digits visible (e.g., '**** **** **** 1234').
    """
    if not isinstance(text, str):
        return text

    def replacer(match):
        digits = re.sub(r'\D', '', match.group(0))
        if 13 <= len(digits) <= 19:
            last4 = digits[-4:]
            if len(digits) == 16:
                return f"**** **** **** {last4}"
            return ('*' * (len(digits) - 4)) + last4
        return match.group(0)

    return CC_REGEX.sub(replacer, text)


def mask_pii(text: str, mask_email: bool = False) -> str:
    """
    Cleanses sensitive PII from text.
    """
    if not isinstance(text, str):
        return text

    text = mask_card_number(text)

    if mask_email:
        def email_replacer(match):
            name, _, domain = match.group(0).partition('@')
            masked_name = name[0] + "***" if len(name) > 1 else "***"
            return f"{masked_name}@{domain}"
        text = EMAIL_REGEX.sub(email_replacer, text)

    return text


def sanitize_untrusted_text(text: str) -> str:
    """
    Sanitizes raw document text to neutralize potential prompt injections
    in bank dispute notices or hotel guest notes.
    """
    if not isinstance(text, str):
        return ""

    sanitized = text
    for pattern in INJECTION_PATTERNS:
        sanitized = pattern.sub('[SANITIZED_INSTRUCTION]', sanitized)
    return sanitized


def sanitize_dict_fields(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively applies PCI-DSS card masking across dictionary values.
    """
    cleaned: Dict[str, Any] = {}
    for k, v in data.items():
        if isinstance(v, str):
            cleaned[k] = mask_card_number(v)
        elif isinstance(v, dict):
            cleaned[k] = sanitize_dict_fields(v)
        elif isinstance(v, list):
            cleaned[k] = [
                sanitize_dict_fields(item) if isinstance(item, dict)
                else (mask_card_number(item) if isinstance(item, str) else item)
                for item in v
            ]
        else:
            cleaned[k] = v
    return cleaned


def escape_markup(value: Any) -> str:
    """Escapes text for safe inclusion in ReportLab Paragraph / HTML markup."""
    return _xml_escape("" if value is None else str(value))


def validate_upload(file_bytes: bytes, filename: str) -> None:
    """
    Validates an uploaded file's size and (for binary formats) magic-byte signature.
    Raises ValueError with a user-facing message if the file is rejected.
    """
    if not file_bytes:
        raise ValueError(f"'{filename}' is empty.")
    if len(file_bytes) > MAX_UPLOAD_BYTES:
        raise ValueError(
            f"'{filename}' is {len(file_bytes) / 1_048_576:.1f} MB; "
            f"the limit is {MAX_UPLOAD_BYTES // 1_048_576} MB."
        )
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    signatures = _MAGIC_BYTES.get(ext)
    if signatures and not any(file_bytes.startswith(sig) for sig in signatures):
        raise ValueError(f"'{filename}' does not look like a valid .{ext} file.")
