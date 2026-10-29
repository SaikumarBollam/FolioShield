"""
Sample Dispute Scenarios for FolioShield Hackathon Testing.
Provides realistic hotel chargeback datasets covering Visa, Mastercard, and American Express.
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
            "line_items": [
                {"date": "2026-10-10", "description": "Room Accommodation - Deluxe King", "amount": 320.00, "type": "Charge"},
                {"date": "2026-10-10", "description": "Occupancy & Resort Tax (14.5%)", "amount": 46.40, "type": "Charge"},
                {"date": "2026-10-10", "description": "Resort Amenity Fee", "amount": 40.00, "type": "Charge"},
                {"date": "2026-10-11", "description": "Room Accommodation - Deluxe King", "amount": 320.00, "type": "Charge"},
                {"date": "2026-10-11", "description": "Occupancy & Resort Tax (14.5%)", "amount": 46.40, "type": "Charge"},
                {"date": "2026-10-11", "description": "Ocean Grill Dining (Signed Room Charge)", "amount": 87.70, "type": "Charge"},
                {"date": "2026-10-12", "description": "Room Accommodation - Deluxe King", "amount": 320.00, "type": "Charge"},
                {"date": "2026-10-12", "description": "Occupancy & Resort Tax (14.5%)", "amount": 46.40, "type": "Charge"},
                {"date": "2026-10-12", "description": "Spa Cabana Refreshments", "amount": 53.60, "type": "Charge"},
                {"date": "2026-10-13", "description": "Visa Payment (Auth: AP98231)", "amount": 1280.50, "type": "Credit"}
            ],
            "raw_text": "Grand Horizon Resort Folio FOL-2026-9812 Room 412 Guest: Jonathan C. Davis. Total $1,280.50 Paid."
        },
        "supporting_docs": {
            "signed_registration_card": True,
            "emv_chip_or_avs_auth": True,
            "cancellation_policy_acknowledged": True,
            "keycard_or_wifi_audit": True,
            "id_verification_copy": True,
            "booking_confirmation": True,
            "guest_service_log": True
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
            "line_items": [
                {"date": "2026-09-28", "description": "Guaranteed Room - Advance Purchase (Non-Refundable)", "amount": 600.00, "type": "Charge"},
                {"date": "2026-09-28", "description": "State & Tourism Lodging Tax (15.0%)", "amount": 90.00, "type": "Charge"},
                {"date": "2026-09-28", "description": "Mastercard Settlement (Auth: MC77192)", "amount": 690.00, "type": "Credit"}
            ],
            "raw_text": "Reservation RES-2026-7731 Eleanor Vance. Non-refundable advance purchase rate. Cancelled after 48hr window."
        },
        "supporting_docs": {
            "signed_registration_card": False,
            "emv_chip_or_avs_auth": True,
            "cancellation_policy_acknowledged": True,
            "keycard_or_wifi_audit": False,
            "id_verification_copy": True,
            "booking_confirmation": True,
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
            "room_number": " Penthouse 12",
            "check_in": "2026-10-02",
            "check_out": "2026-10-04",
            "rate_per_night": 425.00,
            "total_charges": 1095.00,
            "total_payments": 1095.00,
            "balance": 0.0,
            "card_last_4": "1008",
            "auth_code": "AX99214",
            "line_items": [
                {"date": "2026-10-02", "description": "Penthouse Suite Accommodations", "amount": 425.00, "type": "Charge"},
                {"date": "2026-10-03", "description": "Penthouse Suite Accommodations", "amount": 425.00, "type": "Charge"},
                {"date": "2026-10-03", "description": "Private Cabana Dining (Signed Slip #4102)", "amount": 185.00, "type": "Charge"},
                {"date": "2026-10-03", "description": "Overnight Valet Parking", "amount": 60.00, "type": "Charge"},
                {"date": "2026-10-04", "description": "Amex Settlement (Auth: AX99214)", "amount": 1095.00, "type": "Credit"}
            ],
            "raw_text": "Folio FOL-2026-5542 Marcus Sterling. Disputed incidental: $185 dining + $60 valet = $245.00."
        },
        "supporting_docs": {
            "signed_registration_card": True,
            "emv_chip_or_avs_auth": True,
            "cancellation_policy_acknowledged": True,
            "keycard_or_wifi_audit": True,
            "id_verification_copy": True,
            "booking_confirmation": True,
            "guest_service_log": True
        }
    }
}
