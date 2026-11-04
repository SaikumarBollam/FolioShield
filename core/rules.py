"""
Card Network Dispute Rules & Compelling Evidence Knowledge Base.
Supports Visa, Mastercard, American Express, and Discover rules for hospitality.

Phase 1 (Collection) notes:
  * The supporting-document registry is intentionally granular: EMV chip,
    AVS, and 3-D Secure are separate defenses that win different reason codes,
    and keycard logs are separate from WiFi proof-of-use. Each doc type can be
    collected as a file-backed EvidenceItem (see core.models).
  * Reason-code coverage includes the codes hotels actually see, grouped by
    fraud / consumer / processing-error / authorization categories.
"""

from typing import Dict, Any, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Supporting evidence registry (key -> label, group, guidance)
# ---------------------------------------------------------------------------

SUPPORTING_DOC_TYPES: Dict[str, str] = {
    "signed_registration_card": "Signed Registration Card / Digital Check-in",
    "id_verification_log": "Government Photo ID Verified at Front Desk (verification log)",
    "emv_terminal_receipt": "EMV Chip / Contactless Terminal Receipt",
    "avs_cvv_result": "AVS / CVV Authorization Result",
    "three_ds_authentication": "3-D Secure Authentication Record (ECI / CAVV)",
    "keycard_lock_audit": "Electronic Keycard / Door Lock Audit Trail (Onity / Saflok)",
    "pos_signed_slips": "POS Signed Slips (restaurant / bar / spa to room)",
    "booking_confirmation": "Booking Confirmation Email (recipient + timestamp)",
    "cancellation_policy_acceptance": "Cancellation & No-Show Terms Accepted at Booking (exact text + timestamp)",
    "guest_communication_log": "Guest Communication Log (email / phone / message)",
    "guest_service_log": "Guest Service Log (no unresolved complaints)",
    "wifi_usage_log": "WiFi / Network Usage Log",
    "incident_damage_evidence": "Incident / Damage Evidence (photos, report, signed clause)",
    "refund_credit_receipt": "Refund / Credit Receipt Already Issued",
    # Phase 10: Court / Legal Track
    "clickwrap_record": "Booking Clickwrap Record (IP, timestamp, terms version)",
    "cctv_footage": "CCTV Footage Export (timestamped)",
    "suspect_id_copy": "Suspect ID Copy (fraud report; handle per local law)",
    "witness_declaration": "Witness Declaration (front desk agent)",
    "demand_letter": "Demand Letter (certified mail)",
    "police_report": "Police / IC3 Report Filing",
}

# Backwards-compatible aliases: legacy bundled checkbox keys -> the modern
# registry keys they used to attest (one legacy box covered several defenses).
LEGACY_DOC_KEY_ALIASES: Dict[str, tuple] = {
    "emv_chip_or_avs_auth": ("emv_terminal_receipt", "avs_cvv_result", "three_ds_authentication"),
    "cancellation_policy_acknowledged": ("cancellation_policy_acceptance",),
    "keycard_or_wifi_audit": ("keycard_lock_audit", "wifi_usage_log"),
    "id_verification_copy": ("id_verification_log",),
}

# Grouping + collection guidance shown in the UI evidence workspace.
SUPPORTING_DOC_GROUPS: Dict[str, Dict[str, Any]] = {
    "front_desk": {
        "label": "Front Desk Operations",
        "keys": ["signed_registration_card", "id_verification_log", "keycard_lock_audit", "guest_service_log"],
    },
    "payment_auth": {
        "label": "Payment Authorization",
        "keys": ["emv_terminal_receipt", "avs_cvv_result", "three_ds_authentication"],
    },
    "booking_terms": {
        "label": "Booking & Terms",
        "keys": ["booking_confirmation", "cancellation_policy_acceptance", "guest_communication_log"],
    },
    "incidentals_usage": {
        "label": "Incidentals & Proof of Use",
        "keys": ["pos_signed_slips", "wifi_usage_log", "incident_damage_evidence"],
    },
    "financial": {
        "label": "Financial Resolution",
        "keys": ["refund_credit_receipt"],
    },
    "legal_track": {
        "label": "Court / Legal Track (Phase 10)",
        "keys": ["clickwrap_record", "cctv_footage", "suspect_id_copy", "witness_declaration", "demand_letter", "police_report"],
    },
}

SUPPORTING_DOC_GUIDANCE: Dict[str, str] = {
    "signed_registration_card": "Wet signature or e-signature with audit trail (signer, timestamp, IP). Must show rate/terms acknowledgement.",
    "id_verification_log": "Log entry: ID type, verifying agent, date/time. Attach an ID copy only where local law permits.",
    "emv_terminal_receipt": "Chip/contactless receipt with auth code, entry mode, terminal ID (AID/cryptogram if available).",
    "avs_cvv_result": "Gateway/processor AVS + CVV response codes from the original authorization.",
    "three_ds_authentication": "3DS result with ECI and CAVV/AAV from the e-commerce authorization.",
    "keycard_lock_audit": "Lock-system export (Onity/Saflok/Dormakaba) showing key issuance and door entries for the room and stay dates.",
    "pos_signed_slips": "Signed restaurant/bar/spa checks showing room number, date/time, and guest signature for each disputed incidental.",
    "booking_confirmation": "Confirmation email as sent: recipient address, sent timestamp, confirmation number, rate and policy summary.",
    "cancellation_policy_acceptance": "Exact policy text displayed at booking plus acceptance/click timestamp and booking-flow source.",
    "guest_communication_log": "Emails, calls, and messages with the guest — especially any complaint, change, or refund discussion.",
    "guest_service_log": "Housekeeping/maintenance/service log extract showing requests and resolution (or none) during the stay.",
    "wifi_usage_log": "WiFi/network log tying a guest device/account to the room and stay dates.",
    "incident_damage_evidence": "Photos, incident report, and the signed registration clause authorizing post-checkout damage/smoking charges.",
    "refund_credit_receipt": "Processor credit receipt (amount, date, reference/ARN) for any refund already issued on this transaction.",
    "clickwrap_record": "Booking-engine record: guest IP, user agent, acceptance timestamp, terms version/hash, exact terms shown.",
    "cctv_footage": "Exported CCTV clip/stills covering check-in/lobby with burned-in timestamps. PRESERVE IMMEDIATELY — systems overwrite in days.",
    "suspect_id_copy": "Copy of the ID presented (fraud cases). Store/handle only where local law permits; note fake-ID indicators.",
    "witness_declaration": "Signed declaration from the agent who checked the guest in (generated in Tab 6, signed by the witness).",
    "demand_letter": "Pre-suit demand letter with certified-mail article number and mailing/receipt dates.",
    "police_report": "Police report or FBI IC3 filing confirmation (agency, report number, date filed).",
}


# ---------------------------------------------------------------------------
# Card-network reason codes (hospitality-relevant)
# ---------------------------------------------------------------------------

DISPUTE_REASON_CODES: Dict[str, Dict[str, Any]] = {
    # ------------------------------------------------------------------ Visa
    "VISA_10.1": {
        "network": "Visa", "code": "10.1", "name": "EMV Liability Shift — Counterfeit Fraud",
        "category": "Fraud",
        "description": "Cardholder claims a counterfeit card was used in a card-present transaction.",
        "compelling_evidence_required": [
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Signed guest registration card or digital check-in acknowledgement",
        ],
        "win_strategy": "Produce the EMV chip-read receipt: a validated chip cryptogram shifts counterfeit liability to the issuer.",
    },
    "VISA_10.2": {
        "network": "Visa", "code": "10.2", "name": "EMV Liability Shift — Non-Counterfeit Fraud",
        "category": "Fraud",
        "description": "Cardholder claims a lost/stolen card was used in a card-present transaction.",
        "compelling_evidence_required": [
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Government-issued photo identification verified at front desk",
            "Signed guest registration card or digital check-in acknowledgement",
            "Electronic door lock / keycard audit trail demonstrating guest access",
        ],
        "win_strategy": "Combine the chip-read receipt with ID verification and keycard entries to show a legitimate card-present stay.",
    },
    "VISA_10.3": {
        "network": "Visa", "code": "10.3", "name": "Other Fraud: Card-Present Environment",
        "category": "Fraud",
        "description": "Cardholder denies authorizing a card-present transaction.",
        "compelling_evidence_required": [
            "Signed guest registration card or digital check-in acknowledgement",
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Government-issued photo identification verified at front desk",
            "Electronic door lock / keycard audit trail demonstrating guest access",
        ],
        "win_strategy": "Establish physical nexus: registration signature, ID check, chip read, and door entries for the same guest and dates.",
    },
    "VISA_10.4": {
        "network": "Visa", "code": "10.4", "name": "Other Fraud: Card-Absent Environment",
        "category": "Fraud",
        "description": "Cardholder claims they did not authorize or participate in the transaction.",
        "compelling_evidence_required": [
            "Signed guest registration card or digital check-in acknowledgement",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Proof that the cardholder was physically present at the property (e.g. keycard audit, ID copy)",
            "AVS (Address Verification System) and CVV2 match result at time of booking",
            "Booking confirmation sent to cardholder's verified email address",
        ],
        "win_strategy": "Establish physical nexus: Prove the cardholder or authorized guest occupied the room, utilized on-site amenities (dining, minibar, Wi-Fi), and agreed to the rates upon check-in. For eligible Visa CE 3.0 cases, also supply the two prior undisputed transactions with matching account data.",
    },
    "VISA_10.5": {
        "network": "Visa", "code": "10.5", "name": "Visa Fraud Monitoring Program",
        "category": "Fraud",
        "description": "Issuer disputes a transaction flagged under the Visa fraud monitoring program.",
        "compelling_evidence_required": [
            "Signed guest registration card or digital check-in acknowledgement",
            "Government-issued photo identification verified at front desk",
            "Electronic door lock / keycard audit trail demonstrating guest access",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
        ],
        "win_strategy": "Provide the full physical-presence chain (registration, ID, keycard, folio) to rebut the programmatic fraud flag.",
    },
    "VISA_11.1": {
        "network": "Visa", "code": "11.1", "name": "Card Recovery Bulletin",
        "category": "Authorization",
        "description": "Transaction processed on a card listed on the card recovery bulletin without authorization.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "EMV chip terminal receipt showing chip read and cryptogram validation",
        ],
        "win_strategy": "Show a valid issuer approval was obtained at the time of the transaction.",
    },
    "VISA_11.2": {
        "network": "Visa", "code": "11.2", "name": "Declined Authorization",
        "category": "Authorization",
        "description": "Transaction was settled after a declined authorization attempt.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "Authorization log showing approval amount, date, and code",
        ],
        "win_strategy": "Produce the approval code and authorization log entry that precede settlement.",
    },
    "VISA_11.3": {
        "network": "Visa", "code": "11.3", "name": "No Authorization",
        "category": "Authorization",
        "description": "No authorization was obtained for the transaction.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "Authorization log showing approval amount, date, and code",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
        ],
        "win_strategy": "Supply the missing authorization evidence (approval code, amount, timestamp) or concede if none exists.",
    },
    "VISA_12.5": {
        "network": "Visa", "code": "12.5", "name": "Incorrect Amount",
        "category": "Processing Error",
        "description": "Cardholder claims the settled amount differs from the authorized/agreed amount.",
        "compelling_evidence_required": [
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Proof of card authorization / terminal receipt with approval code",
            "Signed guest registration card or digital check-in acknowledgement",
        ],
        "win_strategy": "Reconcile authorization, folio line items, and settlement to the cent; concede and refund any true variance.",
    },
    "VISA_12.6": {
        "network": "Visa", "code": "12.6", "name": "Duplicate Processing / Paid by Other Means",
        "category": "Processing Error",
        "description": "Cardholder claims the same stay was charged twice or paid by another method.",
        "compelling_evidence_required": [
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Settlement / batch report showing a single settled transaction",
            "Proof of card authorization / terminal receipt with approval code",
        ],
        "win_strategy": "Prove only one settlement exists (batch report + folio), or refund the duplicate immediately if real.",
    },
    "VISA_13.1": {
        "network": "Visa", "code": "13.1", "name": "Merchandise / Services Not Received",
        "category": "Consumer Dispute",
        "description": "Cardholder claims accommodations or services were not provided or property was closed.",
        "compelling_evidence_required": [
            "Itemized folio showing completed stay dates and room occupancy",
            "Electronic door lock / keycard audit trail demonstrating guest access",
            "Signed check-in card or front desk registration log",
            "Receipts for incidentals incurred during stay (valet, restaurant, spa)",
            "Disclosed cancellation policy showing terms of no-show forfeiture if guest failed to arrive",
        ],
        "win_strategy": "Demonstrate full delivery of service or that a guaranteed reservation was held in accordance with industry no-show guidelines.",
    },
    "VISA_13.2": {
        "network": "Visa", "code": "13.2", "name": "Cancelled Recurring Transaction",
        "category": "Consumer Dispute",
        "description": "Cardholder claims a recurring charge continued after cancellation (e.g. parking/membership billed with the stay).",
        "compelling_evidence_required": [
            "Clear hotel cancellation policy disclosed at booking (e.g. non-refundable rate)",
            "Communication records with guest regarding disputed charges",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
        ],
        "win_strategy": "Show the charge was not recurring, or that cancellation was received only after the disputed billing date.",
    },
    "VISA_13.3": {
        "network": "Visa", "code": "13.3", "name": "Not as Described or Defective Merchandise / Services",
        "category": "Consumer Dispute",
        "description": "Cardholder claims the room/services were not as described or were defective.",
        "compelling_evidence_required": [
            "Signed registration agreement acknowledging room condition",
            "Guest service log showing no unresolved maintenance/cleanliness complaints",
            "Itemized folio indicating full stay completed without checkout dispute",
            "Communication records with guest regarding disputed charges",
        ],
        "win_strategy": "Show the stay was completed, the room matched the booked description, and no unresolved complaint was raised during the stay.",
    },
    "VISA_13.4": {
        "network": "Visa", "code": "13.4", "name": "Counterfeit Merchandise",
        "category": "Consumer Dispute",
        "description": "Cardholder claims goods purchased were counterfeit (rare in lodging; e.g. gift-shop merchandise).",
        "compelling_evidence_required": [
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Receipts for incidentals incurred during stay (valet, restaurant, spa)",
        ],
        "win_strategy": "Identify the exact merchandise line item and provide purchase/provenance records, or refund the single item.",
    },
    "VISA_13.5": {
        "network": "Visa", "code": "13.5", "name": "Misrepresentation",
        "category": "Consumer Dispute",
        "description": "Cardholder claims the terms of the booking were misrepresented.",
        "compelling_evidence_required": [
            "Booking confirmation sent to cardholder's verified email address",
            "Clear hotel cancellation policy disclosed at booking (e.g. non-refundable rate)",
            "Signed guest registration card or digital check-in acknowledgement",
        ],
        "win_strategy": "Produce the exact booking-flow terms and confirmation the cardholder accepted before purchase.",
    },
    "VISA_13.6": {
        "network": "Visa", "code": "13.6", "name": "Credit Not Processed",
        "category": "Consumer Dispute",
        "description": "Cardholder claims hotel agreed to refund or that cancellation occurred within allowable policy.",
        "compelling_evidence_required": [
            "Clear hotel cancellation policy disclosed at booking (e.g. non-refundable rate)",
            "Timestamped reservation confirmation detailing cutoff deadline",
            "Audit of cancellation timestamp showing guest cancelled late or did not notify property",
            "Communication records with guest regarding disputed charges",
        ],
        "win_strategy": "Show prominent disclosure of non-refundable terms prior to checkout, and prove cancellation occurred after the allowed window. If a refund was already issued, lead with the refund credit receipt.",
    },
    "VISA_13.7": {
        "network": "Visa", "code": "13.7", "name": "Cancelled Merchandise / Services",
        "category": "Consumer Dispute",
        "description": "Cardholder claims the reservation was cancelled but the charge was still processed.",
        "compelling_evidence_required": [
            "Audit of cancellation timestamp showing guest cancelled late or did not notify property",
            "Clear hotel cancellation policy disclosed at booking (e.g. non-refundable rate)",
            "Timestamped reservation confirmation detailing cutoff deadline",
            "Communication records with guest regarding disputed charges",
        ],
        "win_strategy": "Compare the cancellation timestamp/number against the disclosed cutoff; show the charge follows the accepted policy.",
    },

    # -------------------------------------------------------------- Mastercard
    "MC_4808": {
        "network": "Mastercard", "code": "4808", "name": "Authorization-Related Chargeback",
        "category": "Authorization",
        "description": "Authorization was declined, expired, or not obtained as required.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "Authorization log showing approval amount, date, and code",
        ],
        "win_strategy": "Produce the valid approval (code, amount, timestamp) covering the settled amount.",
    },
    "MC_4831": {
        "network": "Mastercard", "code": "4831", "name": "Transaction Amount Differs",
        "category": "Processing Error",
        "description": "Cardholder claims the settled amount differs from the agreed amount.",
        "compelling_evidence_required": [
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Signed guest registration card or digital check-in acknowledgement",
            "Proof of card authorization / terminal receipt with approval code",
        ],
        "win_strategy": "Reconcile folio, authorization, and settlement to the cent; refund any true variance.",
    },
    "MC_4834": {
        "network": "Mastercard", "code": "4834", "name": "Point of Interaction Error (incl. duplicate processing)",
        "category": "Processing Error",
        "description": "Cardholder claims a duplicate charge or other point-of-interaction error.",
        "compelling_evidence_required": [
            "Settlement / batch report showing a single settled transaction",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Proof of card authorization / terminal receipt with approval code",
        ],
        "win_strategy": "Prove a single settlement (batch report + folio), or refund the duplicate immediately if real.",
    },
    "MC_4837": {
        "network": "Mastercard", "code": "4837", "name": "No Cardholder Authorization",
        "category": "Fraud",
        "description": "Cardholder claims they never made or authorized the transaction.",
        "compelling_evidence_required": [
            "Itemized guest folio with room breakdown and incidental charges",
            "Cardholder signature on registration card or terminal receipt",
            "Evidence that room key was issued to and utilized by the registered guest",
            "Government-issued photo identification verified at front desk",
            "3D Secure / EMV chip terminal cryptogram or secure authentication data",
        ],
        "win_strategy": "Provide incontrovertible proof that the cardholder accepted the room keys and registered their signature at front desk.",
    },
    "MC_4849": {
        "network": "Mastercard", "code": "4849", "name": "Questionable Merchant Activity",
        "category": "Fraud",
        "description": "Issuer disputes a transaction under questionable-merchant-activity rules.",
        "compelling_evidence_required": [
            "Signed guest registration card or digital check-in acknowledgement",
            "Government-issued photo identification verified at front desk",
            "Itemized guest folio with room breakdown and incidental charges",
        ],
        "win_strategy": "Provide the full physical-presence chain (registration, ID, folio) to rebut the programmatic flag.",
    },
    "MC_4853": {
        "network": "Mastercard", "code": "4853", "name": "Cardholder Dispute: Defective / Services Not Rendered",
        "category": "Consumer Dispute",
        "description": "Cardholder disputes services, asserts room was uninhabitable, or disputes no-show fee.",
        "compelling_evidence_required": [
            "Signed registration agreement acknowledging room condition",
            "Itemized folio indicating full stay completed without checkout dispute",
            "Guest service log showing no unresolved maintenance/cleanliness complaints",
            "Cancellation policy explicitly acknowledged during booking checkout",
        ],
        "win_strategy": "Prove uninterrupted occupancy and that the hotel fulfilled all reservation obligations as contracted.",
    },
    "MC_4855": {
        "network": "Mastercard", "code": "4855", "name": "Goods or Services Not Provided",
        "category": "Consumer Dispute",
        "description": "Cardholder claims the room or services were not provided.",
        "compelling_evidence_required": [
            "Itemized folio showing completed stay dates and room occupancy",
            "Electronic door lock / keycard audit trail demonstrating guest access",
            "Signed check-in card or front desk registration log",
            "Disclosed cancellation policy showing terms of no-show forfeiture if guest failed to arrive",
        ],
        "win_strategy": "Demonstrate delivery of the stay, or that a guaranteed room was held under the disclosed no-show terms.",
    },
    "MC_4859": {
        "network": "Mastercard", "code": "4859", "name": "No-Show / Addendum Dispute",
        "category": "Consumer Dispute",
        "description": "Cardholder disputes a no-show fee or a post-stay addendum charge (minibar, damage).",
        "compelling_evidence_required": [
            "Disclosed cancellation policy showing terms of no-show forfeiture if guest failed to arrive",
            "Signed guest registration card or digital check-in acknowledgement",
            "Receipts for incidentals incurred during stay (valet, restaurant, spa)",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
        ],
        "win_strategy": "Tie the addendum/no-show charge to the signed registration terms and the disclosed policy, with itemized proof of use.",
    },
    "MC_4860": {
        "network": "Mastercard", "code": "4860", "name": "Credit Not Processed",
        "category": "Consumer Dispute",
        "description": "Cardholder alleges refund was promised or cancellation conformed to rules.",
        "compelling_evidence_required": [
            "Exact cancellation policy copy with highlighted timeframes",
            "Proof of booking acceptance with explicit non-refundable clickwrap/signature",
            "Folio showing no-show charge assessed strictly according to rules",
        ],
        "win_strategy": "Disprove entitlement to refund by demonstrating clear disclosure of cancellation terms. If a refund was already issued, lead with the refund credit receipt.",
    },
    "MC_4870": {
        "network": "Mastercard", "code": "4870", "name": "Chip Liability Shift",
        "category": "Fraud",
        "description": "Counterfeit fraud claim on a card-present transaction under chip liability rules.",
        "compelling_evidence_required": [
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Itemized guest folio with room breakdown and incidental charges",
        ],
        "win_strategy": "Produce the EMV chip-read receipt: a validated chip cryptogram shifts counterfeit liability to the issuer.",
    },
    "MC_4871": {
        "network": "Mastercard", "code": "4871", "name": "Chip/PIN Liability Shift — Lost/Stolen/Never Received",
        "category": "Fraud",
        "description": "Lost/stolen card claim on a card-present transaction under chip/PIN liability rules.",
        "compelling_evidence_required": [
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Government-issued photo identification verified at front desk",
            "Signed guest registration card or digital check-in acknowledgement",
        ],
        "win_strategy": "Combine chip-read evidence with ID verification and registration signature for the card-present stay.",
    },

    # ---------------------------------------------------------- American Express
    "AMEX_F29": {
        "network": "American Express", "code": "F29", "name": "Card Not Present Fraud",
        "category": "Fraud",
        "description": "Cardholder denies participating in card-not-present transaction.",
        "compelling_evidence_required": [
            "Itemized folio matched to cardholder name and billing zip code",
            "Front desk check-in log and key issuance record",
            "Incidentals signed on room account (e.g. restaurant, minibar, parking)",
            "Email confirmation sent to address matching cardholder profile",
        ],
        "win_strategy": "Provide proof of stay, matching billing details, and active folio incidentals.",
    },
    "AMEX_F30": {
        "network": "American Express", "code": "F30", "name": "EMV Counterfeit Fraud",
        "category": "Fraud",
        "description": "Cardmember claims a counterfeit card was used card-present.",
        "compelling_evidence_required": [
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Itemized folio matched to cardholder name and billing zip code",
        ],
        "win_strategy": "Produce the EMV chip-read receipt to shift counterfeit liability to the issuer.",
    },
    "AMEX_F31": {
        "network": "American Express", "code": "F31", "name": "EMV Lost/Stolen/Never Received Fraud",
        "category": "Fraud",
        "description": "Cardmember claims a lost/stolen card was used card-present.",
        "compelling_evidence_required": [
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Government-issued photo identification verified at front desk",
            "Front desk check-in log and key issuance record",
        ],
        "win_strategy": "Combine chip-read, ID verification, and key issuance records for the card-present stay.",
    },
    "AMEX_C02": {
        "network": "American Express", "code": "C02", "name": "Credit Not Processed",
        "category": "Consumer Dispute",
        "description": "Cardmember disputes cancellation charge or missing refund credit.",
        "compelling_evidence_required": [
            "Cancellation policy disclosed prior to reservation completion",
            "Proof reservation was guaranteed and held through checkout cutoff",
            "Confirmation email showing cancellation deadline",
        ],
        "win_strategy": "Validate strict adherence to American Express lodging cancellation rules. If a refund was already issued, lead with the refund credit receipt.",
    },
    "AMEX_C04": {
        "network": "American Express", "code": "C04", "name": "Goods/Services Returned or Refused",
        "category": "Consumer Dispute",
        "description": "Cardmember claims services were refused/returned (e.g. left immediately, refused the room).",
        "compelling_evidence_required": [
            "Itemized folio showing completed stay dates and room occupancy",
            "Electronic door lock / keycard audit trail demonstrating guest access",
            "Guest service log showing no unresolved maintenance/cleanliness complaints",
        ],
        "win_strategy": "Show occupancy and service delivery after the alleged refusal, with a clean service log.",
    },
    "AMEX_C05": {
        "network": "American Express", "code": "C05", "name": "Cancelled Goods/Services",
        "category": "Consumer Dispute",
        "description": "Cardmember claims the reservation was cancelled but charged anyway.",
        "compelling_evidence_required": [
            "Audit of cancellation timestamp showing guest cancelled late or did not notify property",
            "Cancellation policy disclosed prior to reservation completion",
            "Confirmation email showing cancellation deadline",
        ],
        "win_strategy": "Compare the cancellation timestamp/number against the disclosed cutoff; show the charge follows the accepted policy.",
    },
    "AMEX_C08": {
        "network": "American Express", "code": "C08", "name": "Goods / Services Not Received",
        "category": "Consumer Dispute",
        "description": "Cardmember claims room or services were not provided.",
        "compelling_evidence_required": [
            "Room occupancy records / door lock keycard entry logs",
            "Detailed guest folio with stay dates and daily room charge postings",
            "No-show policy documentation if cardmember failed to arrive",
        ],
        "win_strategy": "Prove room was prepared, held exclusively for cardmember, and either occupied or subjected to disclosed forfeiture.",
    },
    "AMEX_C14": {
        "network": "American Express", "code": "C14", "name": "Paid Through Other Means",
        "category": "Consumer Dispute",
        "description": "Cardmember claims the stay was paid by another method (cash, another card, OTA).",
        "compelling_evidence_required": [
            "Itemized folio matched to cardholder name and billing zip code",
            "Settlement / batch report showing a single settled transaction",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
        ],
        "win_strategy": "Prove a single settlement on this card and no duplicate payment by other means.",
    },
    "AMEX_C18": {
        "network": "American Express", "code": "C18", "name": "No-Show or CARDeposit Charge",
        "category": "Consumer Dispute",
        "description": "Cardmember disputes a no-show or card-deposit (guarantee) charge.",
        "compelling_evidence_required": [
            "No-show policy documentation if cardmember failed to arrive",
            "Cancellation policy disclosed prior to reservation completion",
            "Confirmation email showing cancellation deadline",
            "Proof reservation was guaranteed and held through checkout cutoff",
        ],
        "win_strategy": "Show the disclosed no-show/deposit terms, the guarantee, and that the room was held past the cutoff.",
    },
    "AMEX_P01": {
        "network": "American Express", "code": "P01", "name": "Unassigned Card Number",
        "category": "Processing Error",
        "description": "The card number was invalid/unassigned at processing.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "Itemized folio matched to cardholder name and billing zip code",
        ],
        "win_strategy": "Produce the issuer approval for the exact card number settled.",
    },
    "AMEX_P03": {
        "network": "American Express", "code": "P03", "name": "Credit Processed as Charge",
        "category": "Processing Error",
        "description": "A credit/refund was processed as a charge.",
        "compelling_evidence_required": [
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Settlement / batch report showing a single settled transaction",
        ],
        "win_strategy": "Reconcile folio and batch records; concede and correct immediately if the credit was mis-posted.",
    },
    "AMEX_P04": {
        "network": "American Express", "code": "P04", "name": "Charge Processed as Credit",
        "category": "Processing Error",
        "description": "A charge was processed as a credit.",
        "compelling_evidence_required": [
            "Itemized guest folio showing room rates, taxes, and incidental charges",
            "Settlement / batch report showing a single settled transaction",
        ],
        "win_strategy": "Reconcile folio and batch records to show the correct posting direction.",
    },
    "AMEX_P05": {
        "network": "American Express", "code": "P05", "name": "Incorrect Charge Amount",
        "category": "Processing Error",
        "description": "Cardmember claims the settled amount is incorrect.",
        "compelling_evidence_required": [
            "Itemized folio matched to cardholder name and billing zip code",
            "Proof of card authorization / terminal receipt with approval code",
        ],
        "win_strategy": "Reconcile authorization, folio line items, and settlement to the cent; refund any true variance.",
    },
    "AMEX_P07": {
        "network": "American Express", "code": "P07", "name": "Late Submission",
        "category": "Processing Error",
        "description": "The charge was submitted after the allowed submission window.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "Itemized guest folio showing room rates, taxes, and incidental charges",
        ],
        "win_strategy": "Show authorization and submission timestamps fall within the allowed window, or concede if genuinely late.",
    },
    "AMEX_P08": {
        "network": "American Express", "code": "P08", "name": "Duplicate Charge",
        "category": "Processing Error",
        "description": "Cardmember claims the same charge was submitted more than once.",
        "compelling_evidence_required": [
            "Settlement / batch report showing a single settled transaction",
            "Itemized folio matched to cardholder name and billing zip code",
        ],
        "win_strategy": "Prove a single submission (batch report + folio), or refund the duplicate immediately if real.",
    },
    "AMEX_R03": {
        "network": "American Express", "code": "R03", "name": "Insufficient Reply",
        "category": "Inquiry / RFI",
        "description": "A prior inquiry response was insufficient; documentation is requested again.",
        "compelling_evidence_required": [
            "Itemized folio matched to cardholder name and billing zip code",
            "Front desk check-in log and key issuance record",
            "Signed guest registration card or digital check-in acknowledgement",
        ],
        "win_strategy": "Treat as a full chargeback: resubmit the complete evidence chain before the new deadline.",
    },
    "AMEX_R13": {
        "network": "American Express", "code": "R13", "name": "No Reply",
        "category": "Inquiry / RFI",
        "description": "No response was received to a prior inquiry; the dispute now proceeds as a chargeback.",
        "compelling_evidence_required": [
            "Itemized folio matched to cardholder name and billing zip code",
            "Front desk check-in log and key issuance record",
            "Signed guest registration card or digital check-in acknowledgement",
        ],
        "win_strategy": "Respond immediately with the complete evidence chain; the missed inquiry usually forfeits the first round.",
    },

    # ----------------------------------------------------------------- Discover
    "DISC_UA01": {
        "network": "Discover", "code": "UA01", "name": "Fraud: Card Not Present Transaction",
        "category": "Fraud",
        "description": "Cardmember asserts unauthorized remote transaction.",
        "compelling_evidence_required": [
            "Itemized folio detailing accommodation dates",
            "Front desk registration record and identification verification",
            "Positive address and CID verification results",
        ],
        "win_strategy": "Demonstrate authorization and verified guest occupancy.",
    },
    "DISC_UA02": {
        "network": "Discover", "code": "UA02", "name": "Fraud: Card Present Transaction",
        "category": "Fraud",
        "description": "Cardmember asserts unauthorized card-present transaction.",
        "compelling_evidence_required": [
            "EMV chip terminal receipt showing chip read and cryptogram validation",
            "Front desk registration record and identification verification",
            "Itemized folio detailing accommodation dates",
        ],
        "win_strategy": "Combine chip-read evidence with registration and ID verification for the card-present stay.",
    },
    "DISC_AA": {
        "network": "Discover", "code": "AA", "name": "Does Not Recognize",
        "category": "Fraud",
        "description": "Cardmember does not recognize the transaction descriptor or amount.",
        "compelling_evidence_required": [
            "Itemized folio detailing accommodation dates",
            "Booking confirmation sent to cardholder's verified email address",
            "Front desk registration record and identification verification",
        ],
        "win_strategy": "Connect the statement descriptor to the booking confirmation and folio the cardmember received.",
    },
    "DISC_AP": {
        "network": "Discover", "code": "AP", "name": "Cancelled Recurring Transaction",
        "category": "Consumer Dispute",
        "description": "Cardmember claims a recurring charge continued after cancellation.",
        "compelling_evidence_required": [
            "Clear hotel cancellation policy disclosed at booking (e.g. non-refundable rate)",
            "Communication records with guest regarding disputed charges",
        ],
        "win_strategy": "Show the charge was not recurring, or that cancellation arrived after the disputed billing date.",
    },
    "DISC_AW": {
        "network": "Discover", "code": "AW", "name": "Altered Amount",
        "category": "Processing Error",
        "description": "Cardmember claims the amount was altered after authorization.",
        "compelling_evidence_required": [
            "Itemized folio detailing accommodation dates",
            "Proof of card authorization / terminal receipt with approval code",
        ],
        "win_strategy": "Reconcile authorization, folio, and settlement to the cent; refund any true variance.",
    },
    "DISC_DP": {
        "network": "Discover", "code": "DP", "name": "Duplicate Processing",
        "category": "Processing Error",
        "description": "Cardmember claims the same transaction was processed twice.",
        "compelling_evidence_required": [
            "Settlement / batch report showing a single settled transaction",
            "Itemized folio detailing accommodation dates",
        ],
        "win_strategy": "Prove a single settlement (batch report + folio), or refund the duplicate immediately if real.",
    },
    "DISC_IN": {
        "network": "Discover", "code": "IN", "name": "Invalid Card Number",
        "category": "Processing Error",
        "description": "The card number was invalid at processing.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "Itemized folio detailing accommodation dates",
        ],
        "win_strategy": "Produce the issuer approval for the exact card number settled.",
    },
    "DISC_LP": {
        "network": "Discover", "code": "LP", "name": "Late Presentation",
        "category": "Processing Error",
        "description": "The transaction was presented after the allowed window.",
        "compelling_evidence_required": [
            "Proof of card authorization / terminal receipt with approval code",
            "Itemized folio detailing accommodation dates",
        ],
        "win_strategy": "Show authorization and presentment timestamps fall within the allowed window, or concede if genuinely late.",
    },
    "DISC_NC": {
        "network": "Discover", "code": "NC", "name": "Not as Described / Defective",
        "category": "Consumer Dispute",
        "description": "Cardmember claims services were not as described or were defective.",
        "compelling_evidence_required": [
            "Signed registration agreement acknowledging room condition",
            "Guest service log showing no unresolved maintenance/cleanliness complaints",
            "Itemized folio detailing accommodation dates",
        ],
        "win_strategy": "Show the completed stay matched the booked description with no unresolved complaint on file.",
    },
    "DISC_NF": {
        "network": "Discover", "code": "NF", "name": "Non-Receipt of Cash from ATM",
        "category": "Consumer Dispute",
        "description": "ATM cash not received (not lodging-applicable; listed for completeness).",
        "compelling_evidence_required": [
            "Itemized folio detailing accommodation dates",
        ],
        "win_strategy": "Confirm whether any ATM transaction exists in hotel systems; usually conceded or redirected.",
    },
    "DISC_RG": {
        "network": "Discover", "code": "RG", "name": "Non-Receipt of Goods or Services",
        "category": "Consumer Dispute",
        "description": "Cardmember claims the room or services were not received.",
        "compelling_evidence_required": [
            "Itemized folio detailing accommodation dates",
            "Electronic door lock / keycard audit trail demonstrating guest access",
            "Disclosed cancellation policy showing terms of no-show forfeiture if guest failed to arrive",
        ],
        "win_strategy": "Prove occupancy, or that a guaranteed room was held under the disclosed no-show terms.",
    },
    "DISC_RM": {
        "network": "Discover", "code": "RM", "name": "Cardmember Disputes Quality of Goods or Services",
        "category": "Consumer Dispute",
        "description": "Cardmember disputes the quality of the stay or services.",
        "compelling_evidence_required": [
            "Guest service log showing no unresolved maintenance/cleanliness complaints",
            "Signed registration agreement acknowledging room condition",
            "Communication records with guest regarding disputed charges",
        ],
        "win_strategy": "Show the stay completed with complaints resolved (or none raised) and services delivered as booked.",
    },
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
        "Front Desk / Keycard Audit Log",
    ]


# ---------------------------------------------------------------------------
# Phase 3: Structured evidence requirements (the mapping source of truth)
# ---------------------------------------------------------------------------
# Each RequirementSpec binds a reason code to *specific* proof:
#   id            stable requirement id
#   label         human-readable requirement (display)
#   doc_types     registry keys that can satisfy it (any one, unless per_item)
#   criticality   dispositive (case-deciding) / required / supporting
#   validator     key into core.evidence_validators.VALIDATORS (optional)
#   applies_when  optional conditions: stay_status / channel / entry_mode /
#                 partial_only — non-matching specs are excluded, not "missing"
#   per_item      True: must be satisfied per disputed line item (exact amount)
# The prose `compelling_evidence_required` lists above remain for display and
# for codes without a curated spec (generic mapping, labelled as such).

def _spec(spec_id: str, label: str, doc_types: List[str], criticality: str = "required",
          validator: Optional[str] = None, applies_when: Optional[Dict[str, Any]] = None,
          per_item: bool = False) -> Dict[str, Any]:
    return {
        "id": spec_id, "label": label, "doc_types": list(doc_types),
        "criticality": criticality, "validator": validator,
        "applies_when": applies_when or {}, "per_item": per_item,
    }


_FOLIO = _spec("folio", "Itemized guest folio (footing proven in Phase 2)", ["__folio__"], "dispositive", "folio_footing")
_REG = _spec("registration", "Signed registration card / digital check-in", ["signed_registration_card"], "dispositive")
_ID = _spec("id_verification", "Government photo ID verified at front desk", ["id_verification_log"], "required")
_KEYCARD = _spec("keycard", "Keycard / door-lock audit trail with entries inside the stay window",
                 ["keycard_lock_audit"], "dispositive", "stay_window_overlap",
                 applies_when={"stay_status": ["occupied", "early_departure", "day_use"]})
_AVS = _spec("avs_cvv", "AVS / CVV match result from the original authorization", ["avs_cvv_result"], "required", "avs_cvv_match")
_EMV = _spec("emv", "EMV chip terminal receipt (chip read + cryptogram)", ["emv_terminal_receipt"], "dispositive",
             applies_when={"entry_mode": ["chip", "contactless", "swipe"]})
_3DS = _spec("three_ds", "3-D Secure authentication (ECI/CAVV)", ["three_ds_authentication"], "dispositive", "three_ds_authenticated",
             applies_when={"entry_mode": ["ecommerce", "keyed"]})
_BOOKING = _spec("booking_confirmation", "Booking confirmation sent to the guest/cardholder email",
                 ["booking_confirmation"], "required", "booking_recipient")
_POLICY = _spec("policy", "Cancellation / no-show policy accepted at booking (exact text + timestamp)",
                ["cancellation_policy_acceptance"], "dispositive", "policy_acceptance")
_SERVICE_LOG = _spec("service_log", "Guest service log with zero unresolved complaints",
                     ["guest_service_log"], "dispositive", "no_unresolved_complaints")
_COMMS = _spec("communications", "Guest communication log (no unresolved pre-dispute over these charges)",
               ["guest_communication_log"], "supporting")
_POS_PER_ITEM = _spec("pos_slips_per_item", "Signed POS slip for each disputed incidental (exact amount + slip reference)",
                      ["pos_signed_slips"], "dispositive", "per_item_slip_match", per_item=True)
_POS_ANY = _spec("pos_slips", "Signed POS / incidental receipts for charges on the folio",
                 ["pos_signed_slips"], "supporting")
_WIFI = _spec("wifi", "WiFi / network usage log tied to the room and stay dates", ["wifi_usage_log"], "supporting", "stay_window_overlap")
_REFUND_RECEIPT = _spec("refund_receipt", "Refund / credit receipt for the refund already issued",
                        ["refund_credit_receipt"], "dispositive", "refund_receipt_match")
_DAMAGE = _spec("damage_evidence", "Incident / damage evidence (photos, report, signed clause)",
                ["incident_damage_evidence"], "dispositive")
_SETTLEMENT = _spec("settlement_proof", "Settlement / batch proof of a single settled transaction",
                    ["__settlement__"], "dispositive", "single_settlement")
_AUTH = _spec("auth_proof", "Authorization proof (approval code, amount, timestamp)", ["__auth__"], "dispositive")

EVIDENCE_REQUIREMENTS: Dict[str, List[Dict[str, Any]]] = {
    # ------------------------------------------------------------------ Visa
    "VISA_10.1": [_FOLIO, _EMV, _REG],
    "VISA_10.2": [_FOLIO, _EMV, _ID, _KEYCARD],
    "VISA_10.3": [_FOLIO, _REG, _EMV, _ID, _KEYCARD],
    "VISA_10.4": [_FOLIO, _REG, _KEYCARD, _ID, _AVS, _3DS, _BOOKING, _POS_ANY, _WIFI],
    "VISA_10.5": [_FOLIO, _REG, _ID, _KEYCARD],
    "VISA_11.1": [_AUTH, _EMV],
    "VISA_11.2": [_AUTH],
    "VISA_11.3": [_FOLIO, _AUTH],
    "VISA_12.5": [_FOLIO, _AUTH, _REG],
    "VISA_12.6": [_FOLIO, _SETTLEMENT, _AUTH],
    "VISA_13.1": [
        _FOLIO, _KEYCARD, _REG, _POS_ANY,
        {**_POLICY, "id": "policy_noshow", "label": "Disclosed no-show policy + room held / guarantee proof",
         "applies_when": {"stay_status": ["no_show", "cancelled"]}},
    ],
    "VISA_13.2": [_FOLIO, _POLICY, _COMMS],
    "VISA_13.3": [_FOLIO, _REG, _SERVICE_LOG, _COMMS],
    "VISA_13.4": [_FOLIO, _POS_ANY],
    "VISA_13.5": [_FOLIO, _BOOKING, _POLICY, _REG],
    "VISA_13.6": [_FOLIO, _POLICY, _BOOKING, _COMMS, _REFUND_RECEIPT],
    "VISA_13.7": [_FOLIO, _POLICY, _BOOKING, _COMMS],
    # -------------------------------------------------------------- Mastercard
    "MC_4808": [_AUTH],
    "MC_4831": [_FOLIO, _REG, _AUTH],
    "MC_4834": [_FOLIO, _SETTLEMENT, _AUTH],
    "MC_4837": [_FOLIO, _REG, _KEYCARD, _ID, _EMV, _3DS, _AVS],
    "MC_4849": [_FOLIO, _REG, _ID],
    "MC_4853": [_FOLIO, _SERVICE_LOG, _POLICY, _REG, _COMMS],
    "MC_4855": [
        _FOLIO, _KEYCARD, _REG,
        {**_POLICY, "id": "policy_noshow", "label": "Disclosed no-show policy + room held / guarantee proof",
         "applies_when": {"stay_status": ["no_show", "cancelled"]}},
    ],
    "MC_4859": [
        _FOLIO, _REG, _POLICY, _POS_PER_ITEM, _DAMAGE,
        {**_spec("noshow_fee", "No-show fee assessed strictly per disclosed policy", ["cancellation_policy_acceptance"],
                 "dispositive", "policy_acceptance"), "applies_when": {"stay_status": ["no_show"]}},
    ],
    "MC_4860": [_FOLIO, _POLICY, _BOOKING, _REFUND_RECEIPT],
    "MC_4870": [_FOLIO, _EMV],
    "MC_4871": [_FOLIO, _EMV, _ID, _REG],
    # ---------------------------------------------------------- American Express
    "AMEX_F29": [_FOLIO, _KEYCARD, _ID, _BOOKING, _POS_ANY],
    "AMEX_F30": [_FOLIO, _EMV],
    "AMEX_F31": [_FOLIO, _EMV, _ID, _KEYCARD],
    "AMEX_C02": [_FOLIO, _POLICY, _BOOKING, _REFUND_RECEIPT],
    "AMEX_C04": [_FOLIO, _KEYCARD, _SERVICE_LOG],
    "AMEX_C05": [_FOLIO, _POLICY, _BOOKING, _COMMS],
    "AMEX_C08": [
        _FOLIO, _KEYCARD, _REG,
        {**_POS_PER_ITEM, "label": "Signed POS slip for each disputed incidental (exact amount + slip reference)"},
        {**_POLICY, "id": "policy_noshow", "label": "No-show policy documentation (if the cardmember failed to arrive)",
         "applies_when": {"stay_status": ["no_show", "cancelled"]}},
    ],
    "AMEX_C14": [_FOLIO, _SETTLEMENT],
    "AMEX_C18": [_FOLIO, _POLICY, _BOOKING],
    "AMEX_P01": [_FOLIO, _AUTH],
    "AMEX_P03": [_FOLIO, _SETTLEMENT],
    "AMEX_P04": [_FOLIO, _SETTLEMENT],
    "AMEX_P05": [_FOLIO, _AUTH],
    "AMEX_P07": [_FOLIO, _AUTH],
    "AMEX_P08": [_FOLIO, _SETTLEMENT],
    "AMEX_R03": [_FOLIO, _REG, _KEYCARD],
    "AMEX_R13": [_FOLIO, _REG, _KEYCARD],
    # ----------------------------------------------------------------- Discover
    "DISC_UA01": [_FOLIO, _REG, _ID, _AVS],
    "DISC_UA02": [_FOLIO, _EMV, _ID, _REG],
    "DISC_AA": [_FOLIO, _BOOKING, _ID],
    "DISC_AP": [_FOLIO, _POLICY, _COMMS],
    "DISC_AW": [_FOLIO, _AUTH],
    "DISC_DP": [_FOLIO, _SETTLEMENT],
    "DISC_IN": [_FOLIO, _AUTH],
    "DISC_LP": [_FOLIO, _AUTH],
    "DISC_NC": [_FOLIO, _REG, _SERVICE_LOG],
    "DISC_NF": [_FOLIO],
    "DISC_RG": [
        _FOLIO, _KEYCARD,
        {**_POLICY, "id": "policy_noshow", "label": "Disclosed no-show policy (if the cardmember failed to arrive)",
         "applies_when": {"stay_status": ["no_show", "cancelled"]}},
    ],
    "DISC_RM": [_FOLIO, _SERVICE_LOG, _REG, _COMMS],
}

CRITICALITY_WEIGHTS: Dict[str, float] = {"dispositive": 3.0, "required": 2.0, "supporting": 1.0}

GENERIC_REQUIREMENT_SPECS: List[Dict[str, Any]] = [_FOLIO, _REG, _BOOKING, _AUTH, _KEYCARD]


_NETWORK_KEY_PREFIX = {"Visa": "VISA", "Mastercard": "MC", "American Express": "AMEX", "Discover": "DISC"}


def get_requirement_specs(network: Optional[str], code: Optional[str]) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Returns (specs, is_curated) for a dispute. Codes without a curated spec
    get the generic hospitality set with is_curated=False so callers can
    label the mapping as unverified.
    """
    rule = lookup_reason_code(network, code)
    if rule:
        key = f"{_NETWORK_KEY_PREFIX.get(rule['network'], rule['network'].upper())}_{rule['code'].upper()}"
        specs = EVIDENCE_REQUIREMENTS.get(key)
        if specs is not None:
            return specs, True
    return GENERIC_REQUIREMENT_SPECS, False
