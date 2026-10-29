"""
Data Models and Typed Schemas for FolioShield.
Provides standard schemas for API payloads, PMS/BMS integrations,
reconciliation results, and library usage.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


@dataclass
class FolioLineItem:
    date: Optional[str] = None
    description: str = "Hotel Charge"
    amount: float = 0.0
    type: str = "Charge"  # "Charge" or "Credit"
    reference: Optional[str] = None


@dataclass
class NoticeData:
    case_id: Optional[str] = None
    card_network: Optional[str] = "Visa"
    reason_code: Optional[str] = None
    reason_description: Optional[str] = None
    disputed_amount: float = 0.0
    original_amount: float = 0.0
    currency: str = "USD"
    transaction_date: Optional[str] = None
    dispute_date: Optional[str] = None
    response_deadline: Optional[str] = None
    cardholder_name: Optional[str] = None
    card_last_4: Optional[str] = None
    arn: Optional[str] = None
    raw_text: Optional[str] = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NoticeData":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class FolioData:
    hotel_name: Optional[str] = None
    hotel_address: Optional[str] = None
    guest_name: Optional[str] = None
    folio_number: Optional[str] = None
    room_number: Optional[str] = None
    check_in: Optional[str] = None
    check_out: Optional[str] = None
    rate_per_night: float = 0.0
    total_charges: float = 0.0
    total_payments: float = 0.0
    balance: float = 0.0
    card_last_4: Optional[str] = None
    auth_code: Optional[str] = None
    line_items: List[Dict[str, Any]] = field(default_factory=list)
    raw_text: Optional[str] = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FolioData":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class DisputePacketResponse:
    case_id: Optional[str]
    disputed_amount: float
    completeness_score: int
    completeness_assessment: str
    rebuttal_text: str
    pdf_base64: Optional[str] = None
    sha256_digest: Optional[str] = None
    discrepancies: List[Dict[str, Any]] = field(default_factory=list)
    audit_highlights: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
