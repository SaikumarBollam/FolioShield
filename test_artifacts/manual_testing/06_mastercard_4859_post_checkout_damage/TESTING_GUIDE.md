# Scenario 6: Mastercard 4859 — Post-Checkout Damage Addendum

**Purpose:** Post-checkout smoking-damage addendum tied to the signed registration clause.

## Files

- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).
- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).
- `02_guest_folio.csv` — alternative folio upload in Tab 1.
- `evidence/` — upload each file into the matching evidence slot in Tab 2.
- `scenario.json` — source data, evidence details, and expected checks.

## Test Steps

1. Upload the Mastercard 4859 notice and folio.
2. Confirm only the $300.00 Smoking Damage Remediation Fee is disputed; room/tax lines are undisputed.
3. Upload registration, terminal, keycard, ID, incident evidence, and communications files.
4. For incident evidence, note report INC-2214 and six photos in the evidence details/notes if testing the UI fields.
5. Draft, approve, compile, and review chronology for the October 18 addendum.

## Expected Results

- Partial/addendum scope totals $300.00.
- Transaction date is treated as post-checkout addendum, not automatically the wrong folio.
- Incident/damage evidence is dispositive and Exhibit labeling references INC-2214.
- The rebuttal ties the charge to the signed registration damage clause.

> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.
