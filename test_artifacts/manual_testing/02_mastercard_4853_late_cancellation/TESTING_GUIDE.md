# Scenario 2: Mastercard 4853 — Late Cancellation / Non-Refundable Rate

**Purpose:** Cancelled advance-purchase reservation where timing and policy acceptance decide the case.

## Files

- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).
- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).
- `02_guest_folio.csv` — alternative folio upload in Tab 1.
- `evidence/` — upload each file into the matching evidence slot in Tab 2.
- `scenario.json` — source data, evidence details, and expected checks.

## Test Steps

1. Upload the Mastercard notice and folio in Custom Document Upload mode.
2. Verify stay_status=cancelled, rate plan, cancellation timestamp, and cancellation number CX-55210.
3. Upload the evidence files; record policy accepted_at and exact policy text if editing details.
4. Draft, approve, compile, and build a Fiserv submission bundle.

## Expected Results

- Occupancy-only requirements should not be treated as missing for a cancelled stay.
- Cancellation/policy evidence is central; registration/keycard absence is expected.
- The rebuttal summary should use the cancelled-reservation variant, not claim services were occupied/rendered.

> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.
