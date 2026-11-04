"""
Data Models and Typed Schemas for FolioShield.
Provides standard schemas for API payloads, PMS/BMS integrations,
reconciliation results, and library usage.

Phase 1 (Collection) schemas cover:
  * Bank dispute notice fields, including the cardholder's own claim statement,
    dispute lifecycle stage, processor and statement descriptor.
  * PMS / folio fields, including merchant ID, confirmation number, booking
    channel, stay status, authorization detail (AVS / CVV / 3-D Secure / entry
    mode) and refund detail.
  * File-backed evidence items (EvidenceItem) that replace bare boolean
    attestations: every supporting document can carry an attached file, its
    SHA-256 hash, source system, and verifier provenance.
"""

from dataclasses import dataclass, field, asdict
from typing import List, Optional, Dict, Any


# ---------------------------------------------------------------------------
# Line items
# ---------------------------------------------------------------------------

# Canonical folio line-item categories used for per-item evidence linking.
LINE_ITEM_CATEGORIES = (
    "Room", "Tax", "Resort Fee", "Dining", "Bar", "Spa", "Valet", "Parking",
    "Minibar", "Damage", "Fee", "Payment", "Refund", "Other",
)


@dataclass
class FolioLineItem:
    date: Optional[str] = None
    description: str = "Hotel Charge"
    amount: float = 0.0
    type: str = "Charge"  # "Charge" or "Credit"
    reference: Optional[str] = None
    category: str = "Other"
    disputed: Optional[bool] = None  # None = not assessed; True/False = per-item dispute scope


# ---------------------------------------------------------------------------
# Bank dispute notice
# ---------------------------------------------------------------------------

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
    # --- Phase 1 collection additions -------------------------------------
    claim_statement: Optional[str] = None       # cardholder's own words from the notice
    dispute_stage: Optional[str] = None         # inquiry / chargeback / pre_arbitration / second_chargeback / arbitration
    processor: Optional[str] = None             # acquirer / processor that issued the notice
    statement_descriptor: Optional[str] = None  # merchant descriptor as shown on the cardholder statement
    merchant_id: Optional[str] = None           # MID the transaction settled under (as printed on the notice)
    prior_case_id: Optional[str] = None         # linked earlier case (2nd chargeback / pre-arb chain)
    raw_text: Optional[str] = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NoticeData":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Guest folio / PMS record
# ---------------------------------------------------------------------------

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
    # --- Phase 1 collection additions -------------------------------------
    merchant_id: Optional[str] = None           # hotel MID (matches the notice / settlement)
    confirmation_number: Optional[str] = None   # PMS reservation / confirmation number
    booking_channel: Optional[str] = None       # direct_web / direct_phone / ota / gds / walk_in / corporate
    booking_source: Optional[str] = None        # e.g. "Booking.com", "Expedia", "Hotel Website"
    booking_date: Optional[str] = None          # when the reservation was created
    stay_status: Optional[str] = None           # occupied / no_show / cancelled / early_departure / day_use
    check_in_time: Optional[str] = None         # time of day (defenses often turn on the timestamp)
    check_out_time: Optional[str] = None
    rate_plan: Optional[str] = None             # e.g. "Advance Purchase - Non-Refundable", "Best Available Rate"
    num_guests: Optional[int] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None
    payer_name: Optional[str] = None            # when payer != guest (OTA VCC, corporate, family)
    payer_relationship: Optional[str] = None    # e.g. "OTA virtual card", "employer", "spouse"
    avs_result: Optional[str] = None            # AVS response (e.g. "Y - full match", "A - address only")
    cvv_result: Optional[str] = None            # CVV2/CVC2 result (match / no match / not provided)
    three_ds_status: Optional[str] = None       # authenticated / attempted / not_authenticated
    three_ds_eci: Optional[str] = None          # ECI indicator (e.g. Visa 05, MC 02)
    entry_mode: Optional[str] = None            # chip / contactless / swipe / keyed / ecommerce / recurring
    terminal_id: Optional[str] = None
    auth_amount: float = 0.0                    # amount authorized (may differ from settlement)
    auth_date: Optional[str] = None
    refund_amount: float = 0.0                  # refund already issued for this transaction, if any
    refund_date: Optional[str] = None
    refund_reference: Optional[str] = None      # refund ARN / processor credit reference
    cancellation_timestamp: Optional[str] = None
    cancellation_number: Optional[str] = None
    line_items: List[Dict[str, Any]] = field(default_factory=list)
    raw_text: Optional[str] = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FolioData":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


# ---------------------------------------------------------------------------
# Supporting evidence items (file-backed collection)
# ---------------------------------------------------------------------------

@dataclass
class EvidenceItem:
    """
    One collected piece of supporting evidence.

    `present` is the staff attestation that the document exists; `filename` /
    `sha256` prove a file was actually collected into the case. The reconciler
    scores collected files higher than bare attestations.
    """
    doc_type: str
    present: bool = False
    filename: Optional[str] = None
    sha256: Optional[str] = None
    source: Optional[str] = None          # source system, e.g. "Onity lock export", "OPERA PMS"
    verified_by: Optional[str] = None
    verified_at: Optional[str] = None
    notes: Optional[str] = None
    # Phase 6: retained-file reference so exhibits can be bundled/submitted
    size_bytes: Optional[int] = None
    mime: Optional[str] = None
    stored_ref: Optional[str] = None      # exhibit-store key (hash-based), not a path
    # Phase 10: court provenance — what kind of "original" do we hold, and
    # how were electronic records extracted (custody statement fields)
    original_type: Optional[str] = None   # wet_original / copy / scan / e_signature / system_export
    original_location: Optional[str] = None  # e.g. "Front desk file cabinet 3, Oct 2026"
    extracted_by: Optional[str] = None
    extracted_at: Optional[str] = None
    extraction_method: Optional[str] = None  # e.g. "Onity HT28 export, room+date filter, USB"
    system_name: Optional[str] = None        # e.g. "Onity HT28 v4, OPERA PMS 5.6"
    # Document-specific probative facts (recipient, timestamps, result codes…)
    details: Dict[str, Any] = field(default_factory=dict)
    # Optional vision-AI check of the collected file (advisory only; never
    # changes presence/readiness). Bound to this item's sha256 when recorded.
    vision_check: Optional[Dict[str, Any]] = None
    # Runtime retention signal set by callers holding an exhibit store:
    # True/False = whether the file bytes can actually be retrieved now;
    # None = un-annotated (legacy metadata-based behavior). Never proof by
    # itself — the store lookup is the source of truth.
    bytes_retained: Optional[bool] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EvidenceItem":
        valid_keys = {f for f in cls.__dataclass_fields__}
        filtered = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered)


def normalize_supporting_docs(
    supporting_docs: Optional[Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Normalizes the flexible `supporting_docs` input into EvidenceItem dicts.

    Accepts, per doc-type key:
      * bool                      -> attestation only
      * EvidenceItem / dict       -> full evidence record
    Unknown keys are preserved so callers can carry custom doc types.
    """
    normalized: Dict[str, Dict[str, Any]] = {}
    for key, value in (supporting_docs or {}).items():
        if isinstance(value, EvidenceItem):
            normalized[key] = value.to_dict()
        elif isinstance(value, dict):
            item = EvidenceItem.from_dict({**value, "doc_type": value.get("doc_type") or key})
            normalized[key] = item.to_dict()
        else:
            normalized[key] = EvidenceItem(doc_type=key, present=bool(value)).to_dict()
    return normalized


def supporting_doc_flags(normalized: Dict[str, Dict[str, Any]]) -> Dict[str, bool]:
    """Boolean present-flags per doc type (backward-compatible view)."""
    return {key: bool(item.get("present")) for key, item in normalized.items()}


# ---------------------------------------------------------------------------
# Pipeline response
# ---------------------------------------------------------------------------

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
    collection_gaps: List[Dict[str, Any]] = field(default_factory=list)
    evidence_items: List[Dict[str, Any]] = field(default_factory=list)
    # Phase 1 P0 approval integrity: machine processing is never human
    # approval. approval stays None until approve_dispute() is called by a
    # named human; packets generated before that are drafts.
    approval: Optional[Dict[str, Any]] = None
    human_approval_required: bool = True
    approval_fingerprint: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Phase 6: Submission & outcome tracking
# ---------------------------------------------------------------------------

SUBMISSION_STATUSES = ("prepared", "submitted", "acknowledged", "under_review",
                       "won", "lost", "partially_won", "pre_arbitration",
                       "second_chargeback", "arbitration", "withdrawn")


@dataclass
class SubmissionRecord:
    """One representment submission to an acquirer/processor portal."""
    case_id: Optional[str] = None
    arn: Optional[str] = None
    portal_id: str = "generic"
    portal_name: Optional[str] = None
    submitted_by: Optional[str] = None
    submitted_at: Optional[str] = None        # ISO timestamp
    confirmation_reference: Optional[str] = None
    bundle_sha256: Optional[str] = None
    packet_sha256: Optional[str] = None
    approval_fingerprint: Optional[str] = None
    status: str = "prepared"
    expected_decision_by: Optional[str] = None  # submitted + portal decision window
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SubmissionRecord":
        valid_keys = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


@dataclass
class OutcomeRecord:
    """Issuer decision (and escalation) for a submitted case."""
    case_id: Optional[str] = None
    decision: str = "pending"               # pending / won / lost / partially_won
    decided_at: Optional[str] = None
    amount_recovered: float = 0.0
    next_stage: Optional[str] = None        # pre_arbitration / second_chargeback / arbitration / closed
    next_deadline: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OutcomeRecord":
        valid_keys = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


# ---------------------------------------------------------------------------
# Phase 10: Court / Legal Track
# ---------------------------------------------------------------------------

@dataclass
class WitnessRecord:
    """A staff witness (typically the check-in agent) for declarations."""
    name: str
    role: str = "Front Desk Agent"
    contact: Optional[str] = None
    linked_events: List[str] = field(default_factory=list)  # e.g. ["check_in", "id_verified", "key_issued"]
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WitnessRecord":
        valid_keys = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})


@dataclass
class LegalFilingRecord:
    """Demand-letter / court / police filing tracking for the legal track."""
    case_id: Optional[str] = None
    track: str = "civil"                    # civil / criminal
    kind: str = "demand_letter"             # demand_letter / small_claims_filing / police_report / ic3_report
    status: str = "draft"                   # draft / sent / filed / received / closed
    sent_at: Optional[str] = None
    certified_mail_article: Optional[str] = None
    return_receipt_at: Optional[str] = None
    agency_or_court: Optional[str] = None
    report_or_case_number: Optional[str] = None
    filed_at: Optional[str] = None
    hearing_at: Optional[str] = None
    pay_by_date: Optional[str] = None
    notes: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LegalFilingRecord":
        valid_keys = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in data.items() if k in valid_keys})
