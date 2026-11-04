# Scenario 4: Visa 10.4 — OTA Virtual Card (Booking.com VCC)

**Purpose:** OTA virtual-card booking where cardholder and guest legitimately differ.

## Files

- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).
- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).
- `02_guest_folio.csv` — alternative folio upload in Tab 1.
- `evidence/` — upload each file into the matching evidence slot in Tab 2.
- `scenario.json` — source data, evidence details, and expected checks.

## Test Steps

1. Upload the Visa notice and folio.
2. Verify cardholder Booking.com B.V., guest Priya Nair, channel OTA, source Booking.com, and payer relationship.
3. Upload the registration, ID, keycard, booking confirmation, and service-log evidence.
4. Draft and review the third-party-payer explanation before approval.

## Expected Results

- THIRD_PARTY_PAYER appears as informational, not NAME_MISMATCH.
- Folio identity is evaluated in OTA context; do not expect guest and cardholder names to match.
- The rebuttal should reference the OTA confirmation and virtual-card booking context.

> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.
