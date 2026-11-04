# FolioShield Manual Test Artifacts

Upload-ready synthetic fixtures for all six built-in scenarios.

## Complete Evidence Library (all 20 UI evidence types)

If you want a file for **every** evidence slot shown in Tab 2 — including Payment Authorization, Incidentals, Financial Resolution, and Court/Legal items that a single scenario may not need — use:

- `00_complete_evidence_library/README.md` — complete mapping table (UI group → evidence slot → file → values to enter).
- `00_complete_evidence_library/library_index.json` — machine-readable index for all 20 evidence types.

The library is aligned to the Visa 10.4 reference case so all slots can be exercised together. For realistic amount/reference matching, prefer each scenario folder's own `evidence/` files.

## How to use

1. Start FolioShield.
2. In the sidebar, choose **New Dispute Case** (do not use the reference-case loader when testing uploads).
3. Open a scenario folder below.
4. Upload `01_bank_dispute_notice.pdf` and either `02_guest_folio.pdf` or `02_guest_folio.csv` in Tab 1.
5. Follow that folder's `TESTING_GUIDE.md`.
6. Upload files from `evidence/` into matching Tab 2 evidence slots and enter any listed probative details.

## Scenarios

- **Scenario 1: Visa 10.4 — False Fraud Claim (Occupied Deluxe Stay)** — `01_visa_10_4_false_fraud/`
- **Scenario 2: Mastercard 4853 — Late Cancellation / Non-Refundable Rate** — `02_mastercard_4853_late_cancellation/`
- **Scenario 3: American Express C08 — Partial Dispute (Incidentals Contest)** — `03_amex_c08_partial_incidentals/`
- **Scenario 4: Visa 10.4 — OTA Virtual Card (Booking.com VCC)** — `04_visa_10_4_ota_virtual_card/`
- **Scenario 5: Visa 13.6 — Credit Not Processed (Refund Already Issued)** — `05_visa_13_6_refund_already_issued/`
- **Scenario 6: Mastercard 4859 — Post-Checkout Damage Addendum** — `06_mastercard_4859_post_checkout_damage/`

## Notes

- These are synthetic fixtures, not real bank, identity, payment, or legal documents.
- Generated evidence hashes differ from demo hashes in `scenario.json`; FolioShield computes actual hashes on upload.
- Some scenario evidence in the built-in quick-loader is metadata-only. These folders provide actual bytes specifically for upload testing.
- For the strongest end-to-end test, use Scenario 1 first, then Scenario 3 (partial slips), Scenario 5 (refund), and Scenario 4 (OTA).
