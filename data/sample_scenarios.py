"""
Sample Dispute Scenarios for FolioShield Hackathon Testing.
Provides realistic hotel chargeback datasets covering Visa, Mastercard, and American Express.

Phase 1 (Collection) scenarios additionally cover the real-world cases hotels
lose on: OTA virtual-card bookings, refunds already issued, and post-checkout
damage charges. Supporting docs use the file-backed EvidenceItem shape
(present + filename + sha256 + source + verified_by).
"""

from typing import Dict, Any

SCENARIOS: Dict[str, Dict[str, Any]] = {
    "visa_fraud_10_4": {
        "title": "Scenario 1: Visa 10.4 — False Fraud Claim (Occupied Deluxe Stay)",
        "network": "Visa",
        "description": "Cardholder claims $1,280.50 transaction was unauthorized card-not-present fraud. Merchant has signed check-in agreement, EMV chip authorization, and room keycard audit trail.",
        "notice": {
            "case_id": "V-DISP-89214-X",
            "card_network": "Visa",
            "reason_code": "10.4",
            "reason_description": "Other Fraud: Card-Absent Environment",
            "disputed_amount": 1280.50,
            "original_amount": 1280.50,
            "currency": "USD",
            "transaction_date": "2026-10-10",
            "dispute_date": "2026-10-24",
            "response_deadline": "2026-11-07",
            "cardholder_name": "Jonathan C. Davis",
            "card_last_4": "4821",
            "arn": "24492156291002918274019",
            "claim_statement": "I did not authorize or participate in this lodging transaction.",
            "dispute_stage": "chargeback",
            "processor": "Chase Paymentech",
            "statement_descriptor": "GRAND HORIZON RESORT MIAMI",
            "merchant_id": "MID-884120937",
            "raw_text": """VISA CHARGEBACK DISPUTE NOTIFICATION
Acquirer Reference Number: 24492156291002918274019
Case Number: V-DISP-89214-X
Dispute Date: 10/24/2026
Response Due Date: 11/07/2026
Cardholder Name: Jonathan C. Davis
Account Number: ************4821
Dispute Reason Code: 10.4
Dispute Reason: Other Fraud - Card-Absent Environment
Transaction Date: 10/10/2026
Disputed Amount: $1,280.50 USD
Cardholder Statement: 'I did not authorize or participate in this lodging transaction.'"""
        },
        "folio": {
            "hotel_name": "Grand Horizon Resort & Suites",
            "hotel_address": "100 Ocean Avenue, Miami Beach, FL 33139",
            "guest_name": "Jonathan C. Davis",
            "folio_number": "FOL-2026-9812",
            "room_number": "412",
            "check_in": "2026-10-10",
            "check_out": "2026-10-13",
            "rate_per_night": 320.00,
            "total_charges": 1280.50,
            "total_payments": 1280.50,
            "balance": 0.0,
            "card_last_4": "4821",
            "auth_code": "AP98231",
            "merchant_id": "MID-884120937",
            "confirmation_number": "GH-884120",
            "booking_channel": "direct_web",
            "booking_source": "Hotel Website",
            "booking_date": "2026-09-28",
            "stay_status": "occupied",
            "check_in_time": "3:15 PM",
            "rate_plan": "Best Available Rate",
            "guest_email": "jonathan.davis@example.com",
            "avs_result": "Y - full match",
            "cvv_result": "Match",
            "entry_mode": "chip",
            "line_items": [
                {"date": "2026-10-10", "description": "Room Accommodation - Deluxe King", "amount": 320.00, "type": "Charge", "reference": "RM412", "category": "Room", "disputed": None},
                {"date": "2026-10-10", "description": "Occupancy & Resort Tax (14.5%)", "amount": 46.40, "type": "Charge", "reference": "TAX-OCC", "category": "Tax", "disputed": None},
                {"date": "2026-10-10", "description": "Resort Amenity Fee", "amount": 40.00, "type": "Charge", "reference": "RES-FEE", "category": "Resort Fee", "disputed": None},
                {"date": "2026-10-11", "description": "Room Accommodation - Deluxe King", "amount": 320.00, "type": "Charge", "reference": "RM412", "category": "Room", "disputed": None},
                {"date": "2026-10-11", "description": "Occupancy & Resort Tax (14.5%)", "amount": 46.40, "type": "Charge", "reference": "TAX-OCC", "category": "Tax", "disputed": None},
                {"date": "2026-10-11", "description": "Ocean Grill Dining (Signed Room Charge)", "amount": 87.70, "type": "Charge", "reference": "POS-9812", "category": "Dining", "disputed": None},
                {"date": "2026-10-12", "description": "Room Accommodation - Deluxe King", "amount": 320.00, "type": "Charge", "reference": "RM412", "category": "Room", "disputed": None},
                {"date": "2026-10-12", "description": "Occupancy & Resort Tax (14.5%)", "amount": 46.40, "type": "Charge", "reference": "TAX-OCC", "category": "Tax", "disputed": None},
                {"date": "2026-10-12", "description": "Spa Cabana Refreshments", "amount": 53.60, "type": "Charge", "reference": "SPA-331", "category": "Spa", "disputed": None},
                {"date": "2026-10-13", "description": "Visa Payment (Auth: AP98231)", "amount": 1280.50, "type": "Credit", "reference": "AUTH-AP98231", "category": "Payment", "disputed": None}
            ],
            "raw_text": "Grand Horizon Resort Folio FOL-2026-9812 Room 412 Guest: Jonathan C. Davis. Total $1,280.50 Paid."
        },
        "supporting_docs": {
            "signed_registration_card": {"present": True, "filename": "reg_card_davis_412.pdf", "sha256": "a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4", "source": "Front desk scan", "verified_by": "A. Rivera", "details": {"signature_type": "wet"}},
            "emv_terminal_receipt": {"present": True, "filename": "emv_receipt_AP98231.pdf", "sha256": "b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5", "source": "Ingenico terminal T-04", "verified_by": "A. Rivera"},
            "avs_cvv_result": {"present": True, "filename": "gateway_auth_log.csv", "sha256": "c3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6", "source": "Payment gateway", "verified_by": "A. Rivera", "details": {"avs_result": "Y", "cvv_result": "Match"}},
            "cancellation_policy_acceptance": {"present": True, "filename": "booking_acceptance_GH-884120.pdf", "sha256": "d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8", "source": "Hotel website booking engine", "verified_by": "A. Rivera", "details": {"accepted_at": "2026-09-28 14:01 UTC", "policy_text": "Free cancellation until 48 hours before arrival; thereafter first night + tax."}},
            "keycard_lock_audit": {"present": True, "filename": "onity_lock_audit_room412.csv", "sha256": "e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4", "source": "Onity lock export", "verified_by": "A. Rivera", "details": {"entries": 14, "first_entry": "2026-10-10 15:22", "last_entry": "2026-10-13 10:48"}},
            "id_verification_log": {"present": True, "filename": "id_verification_log.pdf", "sha256": "f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7", "source": "Front desk ID log", "verified_by": "A. Rivera", "details": {"id_type": "Driver license"}},
            "booking_confirmation": {"present": True, "filename": "confirmation_email_GH-884120.eml", "sha256": "a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4", "source": "PMS confirmation", "verified_by": "A. Rivera", "details": {"recipient": "jonathan.davis@example.com", "sent_at": "2026-09-28 14:02 UTC"}},
            "guest_service_log": {"present": True, "filename": "service_log_oct10-13.pdf", "sha256": "b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4", "source": "OPERA service log", "verified_by": "A. Rivera", "details": {"unresolved_complaints": 0}},
            "pos_signed_slips": {"present": True, "filename": "pos_slip_9812.pdf", "sha256": "c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4", "source": "Ocean Grill POS", "verified_by": "A. Rivera"},
            "wifi_usage_log": {
                "present": True,
                "filename": "wifi_log_room412.csv",
                "sha256": "d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5",
                "source": "Guest WiFi portal",
                "verified_by": "A. Rivera",
                "details": {
                    "entries": 8,
                    "first_entry": "2026-10-10 15:30",
                    "last_entry": "2026-10-13 10:30",
                    "first_seen": "2026-10-10 15:30",
                    "last_seen": "2026-10-13 10:30"
                }
            }
        }
    },

    "mc_cancellation_4853": {
        "title": "Scenario 2: Mastercard 4853 — Late Cancellation / Non-Refundable Rate",
        "network": "Mastercard",
        "description": "Cardholder disputes $690.00 advance purchase room rate alleging timely cancellation. Merchant records demonstrate explicit non-refundable booking terms and cancellation 2 hours prior to arrival.",
        "notice": {
            "case_id": "MC-CLM-44019-B",
            "card_network": "Mastercard",
            "reason_code": "4853",
            "reason_description": "Cardholder Dispute: Defective / Services Not Rendered",
            "disputed_amount": 690.00,
            "original_amount": 690.00,
            "currency": "USD",
            "transaction_date": "2026-09-28",
            "dispute_date": "2026-10-15",
            "response_deadline": "2026-11-01",
            "cardholder_name": "Eleanor Vance",
            "card_last_4": "9012",
            "arn": "55102948291048201948201",
            "claim_statement": "I cancelled my hotel reservation and should not have been charged.",
            "dispute_stage": "chargeback",
            "merchant_id": "MID-884120937",
            "raw_text": """MASTERCARD DISPUTE RECORD
Case Number: MC-CLM-44019-B
Dispute Reason Code: 4853
Reason: Goods / Services Not Rendered
Cardholder: Eleanor Vance
Account: ************9012
Disputed Amount: $690.00
Merchant: Grand Horizon Resort & Suites
Cardholder Statement: 'I cancelled my hotel reservation and should not have been charged.'"""
        },
        "folio": {
            "hotel_name": "Grand Horizon Resort & Suites",
            "hotel_address": "100 Ocean Avenue, Miami Beach, FL 33139",
            "guest_name": "Eleanor Vance",
            "folio_number": "RES-2026-7731",
            "room_number": "308 (Reserved)",
            "check_in": "2026-09-28",
            "check_out": "2026-09-30",
            "rate_per_night": 300.00,
            "total_charges": 690.00,
            "total_payments": 690.00,
            "balance": 0.0,
            "card_last_4": "9012",
            "auth_code": "MC77192",
            "merchant_id": "MID-884120937",
            "confirmation_number": "GH-773100",
            "booking_channel": "direct_web",
            "booking_source": "Hotel Website",
            "stay_status": "cancelled",
            "rate_plan": "Advance Purchase - Non-Refundable",
            "guest_email": "eleanor.vance@example.com",
            "cancellation_timestamp": "2026-09-28 11:42 AM",
            "cancellation_number": "CX-55210",
            "line_items": [
                {"date": "2026-09-28", "description": "Guaranteed Room - Advance Purchase (Non-Refundable)", "amount": 600.00, "type": "Charge", "reference": "RES-7731", "category": "Room", "disputed": None},
                {"date": "2026-09-28", "description": "State & Tourism Lodging Tax (15.0%)", "amount": 90.00, "type": "Charge", "reference": "TAX-LOD", "category": "Tax", "disputed": None},
                {"date": "2026-09-28", "description": "Mastercard Settlement (Auth: MC77192)", "amount": 690.00, "type": "Credit", "reference": "AUTH-MC77192", "category": "Payment", "disputed": None}
            ],
            "raw_text": "Reservation RES-2026-7731 Eleanor Vance. Non-refundable advance purchase rate. Cancelled after 48hr window."
        },
        "supporting_docs": {
            "signed_registration_card": False,
            "emv_terminal_receipt": {"present": True, "filename": "gateway_auth_MC77192.pdf", "sha256": "1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d", "source": "Payment gateway", "verified_by": "Front Office Manager"},
            "avs_cvv_result": True,
            "cancellation_policy_acceptance": {"present": True, "filename": "booking_acceptance_GH-773100.pdf", "sha256": "2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e", "source": "Hotel website booking engine", "verified_by": "Front Office Manager", "details": {"accepted_at": "2026-09-20 09:14 UTC", "policy_text": "Advance Purchase: non-refundable, no changes."}},
            "keycard_lock_audit": False,
            "id_verification_log": True,
            "booking_confirmation": {"present": True, "filename": "confirmation_email_GH-773100.eml", "sha256": "3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f", "source": "PMS confirmation", "verified_by": "Front Office Manager", "details": {"recipient": "eleanor.vance@example.com", "sent_at": "2026-09-20 09:15 UTC"}},
            "guest_communication_log": {"present": True, "filename": "guest_comms_vance.pdf", "sha256": "4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a", "source": "Reservations inbox", "verified_by": "Front Office Manager"},
            "guest_service_log": True
        }
    },

    "amex_partial_c08": {
        "title": "Scenario 3: American Express C08 — Partial Dispute (Incidentals Contest)",
        "network": "American Express",
        "description": "Cardholder acknowledges $850.00 lodging charges but contests $245.00 for dining and valet incidentals. Reconciler detects partial chargeback and highlights signed restaurant slips.",
        "notice": {
            "case_id": "AX-DISP-11928-C",
            "card_network": "American Express",
            "reason_code": "C08",
            "reason_description": "Goods / Services Not Received or Partially Received",
            "disputed_amount": 245.00,
            "original_amount": 1095.00,
            "currency": "USD",
            "transaction_date": "2026-10-02",
            "dispute_date": "2026-10-20",
            "response_deadline": "2026-11-04",
            "cardholder_name": "Marcus Aurelius Sterling",
            "card_last_4": "1008",
            "arn": "37102948291048201948201",
            "claim_statement": "I did not order or consume the restaurant dining room service billed to my folio.",
            "dispute_stage": "chargeback",
            "merchant_id": "MID-884120937",
            "raw_text": """AMERICAN EXPRESS CHARGEBACK RECORD
Dispute Case: AX-DISP-11928-C
Cardmember: Marcus Aurelius Sterling
Account: *******1008
Dispute Reason: C08
Disputed Amount: $245.00 USD
Original Charge: $1,095.00 USD
Cardmember Remarks: 'I did not order or consume the restaurant dining room service billed to my folio.'"""
        },
        "folio": {
            "hotel_name": "Grand Horizon Resort & Suites",
            "hotel_address": "100 Ocean Avenue, Miami Beach, FL 33139",
            "guest_name": "Marcus Aurelius Sterling",
            "folio_number": "FOL-2026-5542",
            "room_number": "Penthouse 12",
            "check_in": "2026-10-02",
            "check_out": "2026-10-04",
            "rate_per_night": 425.00,
            "total_charges": 1095.00,
            "total_payments": 1095.00,
            "balance": 0.0,
            "card_last_4": "1008",
            "auth_code": "AX99214",
            "merchant_id": "MID-884120937",
            "confirmation_number": "GH-554200",
            "booking_channel": "direct_phone",
            "booking_source": "Reservations Desk",
            "booking_date": "2026-09-25",
            "stay_status": "occupied",
            "check_in_time": "4:05 PM",
            "rate_plan": "Best Available Rate",
            "guest_email": "marcus.sterling@example.com",
            "avs_result": "Y - full match",
            "cvv_result": "Match",
            "entry_mode": "chip",
            "line_items": [
                {"date": "2026-10-02", "description": "Penthouse Suite Accommodations", "amount": 425.00, "type": "Charge", "reference": "RM-PH12", "category": "Room", "disputed": False},
                {"date": "2026-10-03", "description": "Penthouse Suite Accommodations", "amount": 425.00, "type": "Charge", "reference": "RM-PH12", "category": "Room", "disputed": False},
                {"date": "2026-10-03", "description": "Private Cabana Dining (Signed Slip #4102)", "amount": 185.00, "type": "Charge", "reference": "POS-4102", "category": "Dining", "disputed": True},
                {"date": "2026-10-03", "description": "Overnight Valet Parking", "amount": 60.00, "type": "Charge", "reference": "VAL-778", "category": "Valet", "disputed": True},
                {"date": "2026-10-04", "description": "Amex Settlement (Auth: AX99214)", "amount": 1095.00, "type": "Credit", "reference": "AUTH-AX99214", "category": "Payment", "disputed": None}
            ],
            "raw_text": "Folio FOL-2026-5542 Marcus Sterling. Disputed incidental: $185 dining + $60 valet = $245.00."
        },
        "supporting_docs": {
            "signed_registration_card": {"present": True, "filename": "reg_card_sterling_PH12.pdf", "sha256": "5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b", "source": "Front desk scan", "verified_by": "Night Auditor"},
            "emv_terminal_receipt": {"present": True, "filename": "emv_receipt_AX99214.pdf", "sha256": "8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5", "source": "Ingenico terminal T-07", "verified_by": "Night Auditor"},
            "avs_cvv_result": {"present": True, "filename": "gateway_auth_AX99214.csv", "sha256": "9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6", "source": "Payment gateway", "verified_by": "Night Auditor", "details": {"avs_result": "Y", "cvv_result": "Match"}},
            "cancellation_policy_acceptance": {"present": True, "filename": "booking_acceptance_GH-554200.pdf", "sha256": "0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7", "source": "Reservations Desk booking record", "verified_by": "Night Auditor", "details": {"accepted_at": "2026-09-25 10:14 UTC", "policy_text": "Free cancellation until 48 hours before arrival; thereafter first night + tax. Incidentals require a signed slip."}},
            "keycard_lock_audit": {"present": True, "filename": "saflok_audit_PH12.csv", "sha256": "6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c", "source": "Saflok lock export", "verified_by": "Night Auditor", "details": {"entries": 9, "first_entry": "2026-10-02 16:05", "last_entry": "2026-10-04 11:12"}},
            "id_verification_log": {"present": True, "filename": "id_verification_PH12.pdf", "sha256": "1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6", "source": "Front desk ID log", "verified_by": "Night Auditor", "details": {"id_type": "Driver license"}},
            "booking_confirmation": {"present": True, "filename": "confirmation_email_GH-554200.eml", "sha256": "2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8", "source": "PMS confirmation", "verified_by": "Night Auditor", "details": {"recipient": "marcus.sterling@example.com", "sent_at": "2026-09-25 10:15 UTC"}},
            "pos_signed_slips": {"present": True, "filename": "pos_slips_4102_778.pdf", "sha256": "7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d", "source": "Cabana POS + valet desk", "verified_by": "Night Auditor", "details": {"slips": [{"reference": "POS-4102", "amount": 185.00}, {"reference": "VAL-778", "amount": 60.00}]}},
            "guest_service_log": {"present": True, "filename": "service_log_oct02-04.pdf", "sha256": "3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8", "source": "OPERA service log", "verified_by": "Night Auditor", "details": {"unresolved_complaints": 0}}
        }
    },

    "ota_virtual_card_10_4": {
        "title": "Scenario 4: Visa 10.4 — OTA Virtual Card (Booking.com VCC)",
        "network": "Visa",
        "description": "Guest booked via Booking.com and paid the OTA; the hotel charged the OTA's single-use virtual card. The dispute names the OTA as cardholder while the folio names the guest — a third-party payer case, not a name mismatch error.",
        "notice": {
            "case_id": "V-DISP-90331-O",
            "card_network": "Visa",
            "reason_code": "10.4",
            "reason_description": "Other Fraud: Card-Absent Environment",
            "disputed_amount": 540.00,
            "original_amount": 540.00,
            "currency": "USD",
            "transaction_date": "2026-10-18",
            "dispute_date": "2026-10-30",
            "response_deadline": "2026-11-14",
            "cardholder_name": "Booking.com B.V.",
            "card_last_4": "7731",
            "arn": "24492156291002918877310",
            "claim_statement": "Virtual card was charged outside the agreed booking terms.",
            "dispute_stage": "chargeback",
            "merchant_id": "MID-884120937",
            "raw_text": """VISA CHARGEBACK DISPUTE NOTIFICATION
Acquirer Reference Number: 24492156291002918877310
Case Number: V-DISP-90331-O
Cardholder Name: Booking.com B.V.
Account Number: ************7731
Dispute Reason Code: 10.4
Disputed Amount: $540.00 USD
Cardholder Statement: 'Virtual card was charged outside the agreed booking terms.'"""
        },
        "folio": {
            "hotel_name": "Grand Horizon Resort & Suites",
            "hotel_address": "100 Ocean Avenue, Miami Beach, FL 33139",
            "guest_name": "Priya Nair",
            "folio_number": "FOL-2026-6107",
            "room_number": "517",
            "check_in": "2026-10-18",
            "check_out": "2026-10-20",
            "rate_per_night": 240.00,
            "total_charges": 540.00,
            "total_payments": 540.00,
            "balance": 0.0,
            "card_last_4": "7731",
            "auth_code": "VC44190",
            "merchant_id": "MID-884120937",
            "confirmation_number": "BDC-4412098",
            "booking_channel": "ota",
            "booking_source": "Booking.com",
            "booking_date": "2026-10-02",
            "stay_status": "occupied",
            "guest_email": "priya.nair@example.com",
            "payer_name": "Booking.com B.V.",
            "payer_relationship": "OTA virtual card",
            "entry_mode": "ecommerce",
            "line_items": [
                {"date": "2026-10-18", "description": "Room Accommodation - Queen", "amount": 240.00, "type": "Charge", "reference": "RM517", "category": "Room", "disputed": None},
                {"date": "2026-10-18", "description": "Occupancy & Resort Tax (12.5%)", "amount": 30.00, "type": "Charge", "reference": "TAX-OCC", "category": "Tax", "disputed": None},
                {"date": "2026-10-19", "description": "Room Accommodation - Queen", "amount": 240.00, "type": "Charge", "reference": "RM517", "category": "Room", "disputed": None},
                {"date": "2026-10-19", "description": "Occupancy & Resort Tax (12.5%)", "amount": 30.00, "type": "Charge", "reference": "TAX-OCC", "category": "Tax", "disputed": None},
                {"date": "2026-10-20", "description": "Visa Virtual Card Payment (Auth: VC44190)", "amount": 540.00, "type": "Credit", "reference": "AUTH-VC44190", "category": "Payment", "disputed": None}
            ],
            "raw_text": "Booking.com reservation BDC-4412098 guest Priya Nair. Paid by OTA virtual card."
        },
        "supporting_docs": {
            "signed_registration_card": {"present": True, "filename": "reg_card_nair_517.pdf", "sha256": "8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e", "source": "Front desk scan", "verified_by": "A. Rivera"},
            "id_verification_log": True,
            "keycard_lock_audit": {"present": True, "filename": "keycard_audit_nair_517.csv", "sha256": "7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f", "source": "VingCard lock export", "verified_by": "A. Rivera", "details": {"entries": 6, "first_entry": "2026-10-18 16:10", "last_entry": "2026-10-20 11:05"}},
            "booking_confirmation": {"present": True, "filename": "bookingcom_confirmation_BDC-4412098.pdf", "sha256": "9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f", "source": "Booking.com extranet", "verified_by": "A. Rivera", "details": {"recipient": "priya.nair@example.com", "sent_at": "2026-10-02 11:30 UTC", "vcc_terms": "Single-use, stay dates only, max $540.00"}},
            "guest_service_log": True
        }
    },

    "visa_refund_issued_13_6": {
        "title": "Scenario 5: Visa 13.6 — Credit Not Processed (Refund Already Issued)",
        "network": "Visa",
        "description": "Guest cancelled inside the free-cancellation window and the hotel refunded $412.00, but the cardholder disputed before the credit posted. The winning exhibit is the refund credit receipt.",
        "notice": {
            "case_id": "V-DISP-87712-R",
            "card_network": "Visa",
            "reason_code": "13.6",
            "reason_description": "Credit Not Processed",
            "disputed_amount": 412.00,
            "original_amount": 412.00,
            "currency": "USD",
            "transaction_date": "2026-09-30",
            "dispute_date": "2026-10-22",
            "response_deadline": "2026-11-10",
            "cardholder_name": "Tomas Herrera",
            "card_last_4": "2210",
            "arn": "24492156291002918722100",
            "claim_statement": "I cancelled within the free cancellation window and never received my refund.",
            "dispute_stage": "chargeback",
            "merchant_id": "MID-884120937",
            "raw_text": """VISA CHARGEBACK DISPUTE NOTIFICATION
Acquirer Reference Number: 24492156291002918722100
Case Number: V-DISP-87712-R
Cardholder Name: Tomas Herrera
Account Number: ************2210
Dispute Reason Code: 13.6
Disputed Amount: $412.00 USD
Cardholder Statement: 'I cancelled within the free cancellation window and never received my refund.'"""
        },
        "folio": {
            "hotel_name": "Grand Horizon Resort & Suites",
            "hotel_address": "100 Ocean Avenue, Miami Beach, FL 33139",
            "guest_name": "Tomas Herrera",
            "folio_number": "RES-2026-6610",
            "room_number": "— (Cancelled)",
            "check_in": "2026-10-05",
            "check_out": "2026-10-07",
            "rate_per_night": 180.00,
            "total_charges": 412.00,
            "total_payments": 412.00,
            "balance": 0.0,
            "card_last_4": "2210",
            "auth_code": "VH22100",
            "merchant_id": "MID-884120937",
            "confirmation_number": "GH-661000",
            "booking_channel": "direct_web",
            "booking_source": "Hotel Website",
            "stay_status": "cancelled",
            "rate_plan": "Flexible - Free Cancellation 48h",
            "guest_email": "tomas.herrera@example.com",
            "cancellation_timestamp": "2026-10-01 10:05 AM",
            "cancellation_number": "CX-66101",
            "refund_amount": 412.00,
            "refund_date": "2026-10-02",
            "refund_reference": "RF-884120-6610",
            "line_items": [
                {"date": "2026-09-30", "description": "Prepaid Room Deposit - Flexible Rate", "amount": 412.00, "type": "Charge", "reference": "DEP-6610", "category": "Room", "disputed": None},
                {"date": "2026-09-30", "description": "Visa Payment (Auth: VH22100)", "amount": 412.00, "type": "Credit", "reference": "AUTH-VH22100", "category": "Payment", "disputed": None},
                {"date": "2026-10-02", "description": "Refund Issued - Cancellation CX-66101", "amount": 412.00, "type": "Credit", "reference": "RF-884120-6610", "category": "Refund", "disputed": None}
            ],
            "raw_text": "Reservation RES-2026-6610 Tomas Herrera. Cancelled 2026-10-01 inside window; refund RF-884120-6610 issued 2026-10-02."
        },
        "supporting_docs": {
            "cancellation_policy_acceptance": {"present": True, "filename": "booking_acceptance_GH-661000.pdf", "sha256": "0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a", "source": "Hotel website booking engine", "verified_by": "Revenue Manager", "details": {"accepted_at": "2026-09-25 08:40 UTC", "policy_text": "Free cancellation until 48 hours before arrival."}},
            "booking_confirmation": {"present": True, "filename": "confirmation_email_GH-661000.eml", "sha256": "3d4e5f6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6a7b8c9d0e1f2a3b4c5d6e", "source": "PMS confirmation", "verified_by": "Revenue Manager", "details": {"recipient": "tomas.herrera@example.com", "sent_at": "2026-09-25 08:45 UTC"}},
            "guest_communication_log": {"present": True, "filename": "guest_comms_herrera.pdf", "sha256": "1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b", "source": "Reservations inbox", "verified_by": "Revenue Manager"},
            "refund_credit_receipt": {"present": True, "filename": "refund_receipt_RF-884120-6610.pdf", "sha256": "2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c", "source": "Processor portal", "verified_by": "Revenue Manager", "details": {"amount": 412.00, "date": "2026-10-02"}}
        }
    },

    "mc_damage_4859": {
        "title": "Scenario 6: Mastercard 4859 — Post-Checkout Damage Addendum",
        "network": "Mastercard",
        "description": "Guest completed a stay, then disputed a $300.00 post-checkout smoking/damage charge billed two days after departure. Defense rests on the signed registration damage clause, photos, and the incident report.",
        "notice": {
            "case_id": "MC-CLM-51208-D",
            "card_network": "Mastercard",
            "reason_code": "4859",
            "reason_description": "No-Show / Addendum Dispute",
            "disputed_amount": 300.00,
            "original_amount": 980.00,
            "currency": "USD",
            "transaction_date": "2026-10-16",
            "dispute_date": "2026-10-28",
            "response_deadline": "2026-11-12",
            "cardholder_name": "Grace O'Malley",
            "card_last_4": "6640",
            "arn": "55102948291048201666401",
            "claim_statement": "I never authorized a $300 charge after I checked out.",
            "dispute_stage": "chargeback",
            "merchant_id": "MID-884120937",
            "raw_text": """MASTERCARD DISPUTE RECORD
Case Number: MC-CLM-51208-D
Dispute Reason Code: 4859
Cardholder: Grace O'Malley
Account: ************6640
Disputed Amount: $300.00
Cardholder Statement: 'I never authorized a $300 charge after I checked out.'"""
        },
        "folio": {
            "hotel_name": "Grand Horizon Resort & Suites",
            "hotel_address": "100 Ocean Avenue, Miami Beach, FL 33139",
            "guest_name": "Grace O'Malley",
            "folio_number": "FOL-2026-7020",
            "room_number": "629",
            "check_in": "2026-10-14",
            "check_out": "2026-10-16",
            "rate_per_night": 290.00,
            "total_charges": 980.00,
            "total_payments": 980.00,
            "balance": 0.0,
            "card_last_4": "6640",
            "auth_code": "MC90210",
            "merchant_id": "MID-884120937",
            "confirmation_number": "GH-702000",
            "booking_channel": "direct_web",
            "booking_source": "Hotel Website",
            "stay_status": "occupied",
            "guest_email": "grace.omalley@example.com",
            "entry_mode": "chip",
            "line_items": [
                {"date": "2026-10-14", "description": "Room Accommodation - King", "amount": 290.00, "type": "Charge", "reference": "RM629", "category": "Room", "disputed": False},
                {"date": "2026-10-15", "description": "Room Accommodation - King", "amount": 290.00, "type": "Charge", "reference": "RM629", "category": "Room", "disputed": False},
                {"date": "2026-10-16", "description": "Occupancy & Resort Tax", "amount": 100.00, "type": "Charge", "reference": "TAX-OCC", "category": "Tax", "disputed": False},
                {"date": "2026-10-18", "description": "Smoking Damage Remediation Fee", "amount": 300.00, "type": "Charge", "reference": "INC-2214", "category": "Damage", "disputed": True},
                {"date": "2026-10-16", "description": "Mastercard Settlement (Auth: MC90210)", "amount": 680.00, "type": "Credit", "reference": "AUTH-MC90210", "category": "Payment", "disputed": None},
                {"date": "2026-10-18", "description": "Mastercard Addendum (Auth: MC90277)", "amount": 300.00, "type": "Credit", "reference": "AUTH-MC90277", "category": "Payment", "disputed": None}
            ],
            "raw_text": "Folio FOL-2026-7020 Grace O'Malley room 629. Post-checkout smoking damage fee INC-2214 billed 2026-10-18."
        },
        "supporting_docs": {
            "signed_registration_card": {"present": True, "filename": "reg_card_omalley_629.pdf", "sha256": "3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d", "source": "Front desk scan", "verified_by": "Front Office Manager", "details": {"damage_clause_signed": True}},
            "emv_terminal_receipt": True,
            "keycard_lock_audit": {"present": True, "filename": "keycard_audit_omalley_629.csv", "sha256": "6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e", "source": "Onity lock export", "verified_by": "Front Office Manager", "details": {"entries": 11, "first_entry": "2026-10-14 15:45", "last_entry": "2026-10-16 10:30"}},
            "id_verification_log": True,
            "incident_damage_evidence": {"present": True, "filename": "incident_INC-2214_photos_report.pdf", "sha256": "4b5c6d7e8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a", "source": "Housekeeping incident report", "verified_by": "Front Office Manager", "details": {"photos": 6, "report_id": "INC-2214"}},
            "guest_communication_log": {"present": True, "filename": "guest_comms_omalley.pdf", "sha256": "5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1a2b3c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a", "source": "Front desk email", "verified_by": "Front Office Manager"}
        }
    }
}
