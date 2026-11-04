# Scenario 3: American Express C08 — Partial Dispute (Incidentals Contest)

**Purpose:** Partial dispute where exact-amount signed POS slips decide the contested lines.

## Files

- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).
- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).
- `02_guest_folio.csv` — alternative folio upload in Tab 1.
- `evidence/` — upload each file into the matching evidence slot in Tab 2.
- `scenario.json` — source data, evidence details, and expected checks.

## Test Steps

1. Upload the Amex notice and folio.
2. Confirm disputed lines are Dining $185.00 (POS-4102) and Valet $60.00 (VAL-778).
3. Upload pos_signed_slips.pdf; in Probative details, first test only POS-4102/$185.00 and observe partial coverage.
4. Then use the generated scenario data or add the second slip reference/amount through the SDK/test data; the supplied evidence text lists both slips.
5. Draft, approve, compile, choose Stripe, and build the bundle.

## Expected Results

- Partial dispute is $245.00 of $1,095.00; $850.00 is uncontested.
- Disputed-scope proof passes when both marked lines total $245.00.
- POS requirement is dispositive and names any uncovered incidental.
- Exhibit D should identify slip POS-4102 $185.00 and VAL-778 $60.00 in the built-in scenario.

> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.
