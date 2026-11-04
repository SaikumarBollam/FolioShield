# Scenario 5: Visa 13.6 — Credit Not Processed (Refund Already Issued)

**Purpose:** Credit-not-processed dispute where the hotel already refunded the full amount.

## Files

- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).
- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).
- `02_guest_folio.csv` — alternative folio upload in Tab 1.
- `evidence/` — upload each file into the matching evidence slot in Tab 2.
- `scenario.json` — source data, evidence details, and expected checks.

## Test Steps

1. Upload the Visa 13.6 notice and folio.
2. Verify refund amount $412.00, refund date, reference RF-884120-6610, cancellation timestamp, and cancellation number.
3. Upload policy, communications, and refund receipt evidence; record refund amount/reference in Probative details.
4. Draft, approve, compile, and inspect the closing request.

## Expected Results

- Amount proof identifies the cardholder as already made whole.
- Settlement state is SETTLED_THEN_REFUNDED.
- Executive summary and closing request denial of double recovery, not a generic reversal request.
- Refund receipt is a dispositive exhibit.

> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.
