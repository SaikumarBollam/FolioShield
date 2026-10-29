"""
Card Network Dispute Rules & Compelling Evidence Knowledge Base.
Supports Visa, Mastercard, American Express, and Discover rules for hospitality.
"""

from typing import Dict, Any, List, Optional

DISPUTE_REASON_CODES: Dict[str, Dict[str, Any]] = {
    # Visa Reason Codes
    "VISA_10.4": {
        "network": "Visa",
        "code": "10.4",
        "name": "Other Fraud: Card-Absent Environment",
        "category": "Fraud",
        "description": "Cardholder claims they did not authorize or participate in the transaction.",
        "compelling_evidence_required": [
            "Signed guest registration card or digital check-in acknowledgement",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Proof that the cardholder was physically present at the property (e.g. keycard audit, ID copy)",
            "AVS (Address Verification System) and CVV2 match result at time of booking",
            "Booking confirmation sent to cardholder's verified email address"
        ],
        "win_strategy": "Establish physical nexus: Prove the cardholder or authorized guest occupied the room, utilized on-site amenities (dining, minibar, Wi-Fi), and agreed to the rates upon check-in."
    },
    "VISA_13.1": {
        "network": "Visa",
        "code": "13.1",
        "name": "Merchandise / Services Not Received",
        "category": "Consumer Dispute",
        "description": "Cardholder claims accommodations or services were not provided or property was closed.",
        "compelling_evidence_required": [
            "Itemized folio showing completed stay dates and room occupancy",
            "Electronic door lock / keycard audit trail demonstrating guest access",
            "Signed check-in card or front desk registration log",
            "Receipts for incidentals incurred during stay (valet, restaurant, spa)",
            "Disclosed cancellation policy showing terms of no-show forfeiture if guest failed to arrive"
        ],
        "win_strategy": "Demonstrate full delivery of service or that a guaranteed reservation was held in accordance with industry no-show guidelines."
    },
    "VISA_13.6": {
        "network": "Visa",
        "code": "13.6",
        "name": "Credit Not Processed",
        "category": "Consumer Dispute",
        "description": "Cardholder claims hotel agreed to refund or that cancellation occurred within allowable policy.",
        "compelling_evidence_required": [
            "Clear hotel cancellation policy disclosed at booking (e.g. non-refundable rate)",
            "Timestamped reservation confirmation detailing cutoff deadline",
            "Audit of cancellation timestamp showing guest cancelled late or did not notify property",
            "Communication records with guest regarding disputed charges"
        ],
        "win_strategy": "Show prominent disclosure of non-refundable terms prior to checkout, and prove cancellation occurred after the allowed window."
    },

    # Mastercard Reason Codes
    "MC_4837": {
        "network": "Mastercard",
        "code": "4837",
        "name": "No Cardholder Authorization",
        "category": "Fraud",
        "description": "Cardholder claims they never made or authorized the transaction.",
        "compelling_evidence_required": [
            "Itemized guest folio with room breakdown and incidental charges",
            "Cardholder signature on registration card or terminal receipt",
            "Evidence that room key was issued to and utilized by the registered guest",
            "Government-issued photo identification verified at front desk",
            "3D Secure / EMV chip terminal cryptogram or secure authentication data"
        ],
        "win_strategy": "Provide incontrovertible proof that the cardholder accepted the room keys and registered their signature at front desk."
    },
    "MC_4853": {
        "network": "Mastercard",
        "code": "4853",
        "name": "Cardholder Dispute: Defective / Services Not Rendered",
        "category": "Consumer Dispute",
        "description": "Cardholder disputes services, asserts room was uninhabitable, or disputes no-show fee.",
        "compelling_evidence_required": [
            "Signed registration agreement acknowledging room condition",
            "Itemized folio indicating full stay completed without checkout dispute",
            "Guest service log showing no unresolved maintenance/cleanliness complaints",
            "Cancellation policy explicitly acknowledged during booking checkout"
        ],
        "win_strategy": "Prove uninterrupted occupancy and that the hotel fulfilled all reservation obligations as contracted."
    },
    "MC_4860": {
        "network": "Mastercard",
        "code": "4860",
        "name": "Credit Not Processed",
        "category": "Consumer Dispute",
        "description": "Cardholder alleges refund was promised or cancellation conformed to rules.",
        "compelling_evidence_required": [
            "Exact cancellation policy copy with highlighted timeframes",
            "Proof of booking acceptance with explicit non-refundable clickwrap/signature",
            "Folio showing no-show charge assessed strictly according to rules"
        ],
        "win_strategy": "Disprove entitlement to refund by demonstrating clear disclosure of cancellation terms."
    },

    # American Express Reason Codes
    "AMEX_F29": {
        "network": "American Express",
        "code": "F29",
        "name": "Card Not Present Fraud",
        "category": "Fraud",
        "description": "Cardholder denies participating in card-not-present transaction.",
        "compelling_evidence_required": [
            "Itemized folio matched to cardholder name and billing zip code",
            "Front desk check-in log and key issuance record",
            "Incidentals signed on room account (e.g. restaurant, minibar, parking)",
            "Email confirmation sent to address matching cardholder profile"
        ],
        "win_strategy": "Provide proof of stay, matching billing details, and active folio incidentals."
    },
    "AMEX_C08": {
        "network": "American Express",
        "code": "C08",
        "name": "Goods / Services Not Received",
        "category": "Consumer Dispute",
        "description": "Cardmember claims room or services were not provided.",
        "compelling_evidence_required": [
            "Room occupancy records / door lock keycard entry logs",
            "Detailed guest folio with stay dates and daily room charge postings",
            "No-show policy documentation if cardmember failed to arrive"
        ],
        "win_strategy": "Prove room was prepared, held exclusively for cardmember, and either occupied or subjected to disclosed forfeiture."
    },
    "AMEX_C02": {
        "network": "American Express",
        "code": "C02",
        "name": "Credit Not Processed",
        "category": "Consumer Dispute",
        "description": "Cardmember disputes cancellation charge or missing refund credit.",
        "compelling_evidence_required": [
            "Cancellation policy disclosed prior to reservation completion",
            "Proof reservation was guaranteed and held through checkout cutoff",
            "Confirmation email showing cancellation deadline"
        ],
        "win_strategy": "Validate strict adherence to American Express lodging cancellation rules."
    },

    # Discover Reason Codes
    "DISC_UA01": {
        "network": "Discover",
        "code": "UA01",
        "name": "Fraud: Card Not Present Transaction",
        "category": "Fraud",
        "description": "Cardmember asserts unauthorized remote transaction.",
        "compelling_evidence_required": [
            "Itemized folio detailing accommodation dates",
            "Front desk registration record and identification verification",
            "Positive address and CID verification results"
        ],
        "win_strategy": "Demonstrate authorization and verified guest occupancy."
    }
}


# Supporting evidence the staff reviewer can confirm in the UI (key -> label).
SUPPORTING_DOC_TYPES: Dict[str, str] = {
    "signed_registration_card": "Signed Registration Card / Digital Check-in",
    "emv_chip_or_avs_auth": "EMV Chip Terminal / 3D Secure / AVS Authorization",
    "cancellation_policy_acknowledged": "Cancellation & No-Show Terms Acknowledged at Booking",
    "keycard_or_wifi_audit": "Electronic Keycard / RFID Lock Audit Trail",
    "id_verification_copy": "Government Photo ID Verified at Front Desk",
    "booking_confirmation": "Booking Confirmation / Guest Correspondence",
    "guest_service_log": "Guest Service Log (No Unresolved Complaints)",
}


def _normalize_code(code: str) -> str:
    return code.replace(".", "").replace(" ", "").upper()


def lookup_reason_code(network: Optional[str], code: Optional[str]) -> Optional[Dict[str, Any]]:
    """
    Looks up standard card network dispute rules by network and code.
    Example: lookup_reason_code('Visa', '10.4')
    """
    if not network or not code:
        return None

    network_u = network.strip().upper()
    code_n = _normalize_code(code)
    for rule in DISPUTE_REASON_CODES.values():
        if rule["network"].upper() == network_u and _normalize_code(rule["code"]) == code_n:
            return rule
    return None


def get_evidence_checklist_for_dispute(network: Optional[str], code: Optional[str]) -> List[str]:
    """
    Returns the required evidence checklist for the given dispute.
    """
    rule = lookup_reason_code(network, code)
    if rule:
        return rule["compelling_evidence_required"]
    
    # Default hospitality evidence checklist
    return [
        "Itemized Guest Folio / Billing Statement",
        "Signed Registration Card or Digital Check-in Record",
        "Reservation Confirmation Email with Disclosed Policies",
        "Proof of Card Authorization / Terminal Receipt",
        "Front Desk / Keycard Audit Log"
    ]
