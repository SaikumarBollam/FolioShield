# Scenario 3: American Express C08 — Partial Dispute (Incidentals Contest)

**Purpose:** Partial dispute where exact-amount signed POS slips decide the contested lines.

## Files

- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).
- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).
- `02_guest_folio.csv` — alternative folio upload in Tab 1.
- `evidence/` — upload each file into the matching evidence slot in Tab 2.
- `scenario.json` — source data, evidence details, and expected checks.

## Test Steps

1. Upload the Amex notice and folio (PDF or CSV).
2. In Tab 1 → Review & Correct Collected Fields, confirm: Stay status = occupied, Room = Penthouse 12, Booking Date 2026-09-25, Rate Plan 'Best Available Rate', Guest Email marcus.sterling@example.com, AVS 'Y - full match', CVV 'Match', Entry Mode 'chip'. (The generated folio PDF prints these; verify the parser picked them up.)
3. Confirm disputed lines are Dining $185.00 (POS-4102) and Valet $60.00 (VAL-778) — the folio marks them [DISPUTED TEST LINE] and the parser scopes them automatically.
4. Upload each evidence/ file into its matching Tab 2 slot. For POS Signed Slips, the UI's Probative details form captures ONE slip — enter slip reference POS-4102 and amount 185.00 there, then note that the second slip (VAL-778, $60.00) is listed inside 08_pos_signed_slips.pdf; full two-slip coverage is proven in the built-in scenario loader / SDK path where details.slips carries both entries.
5. For Cancellation Policy Acceptance, enter Accepted at '2026-09-25 10:14 UTC' in Probative details (the exact policy text is inside 04_cancellation_policy_acceptance.txt). For Booking Confirmation, enter recipient marcus.sterling@example.com and sent-at '2026-09-25 10:15 UTC'.
6. Draft, approve, compile, choose Stripe, and build the bundle. The draft must NOT claim the reservation was cancelled — this is an occupied stay.

## Expected Results

- Partial dispute is $245.00 of $1,095.00; $850.00 is uncontested.
- Disputed-scope proof passes when both marked lines total $245.00.
- Executive summary uses the partial-dispute variant (signed slips per contested line), never the cancelled-reservation variant.
- Chronology shows booking (2026-09-25), policy acceptance, check-in, keycard entries, and settlement — with no [MISSING: booking date / policy acceptance / cancellation] anchors for this occupied stay.
- POS requirement is dispositive and names any uncovered incidental until both slips are recorded.
- Exhibit for POS slips identifies slip POS-4102 $185.00 and VAL-778 $60.00 in the built-in scenario.

> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.
