# Scenario 1: Visa 10.4 — False Fraud Claim (Occupied Deluxe Stay)

**Purpose:** Full occupied-stay fraud defense with a complete physical-presence chain.

## Files

- `01_bank_dispute_notice.pdf` — upload in Tab 1 (Bank Dispute Notice).
- `02_guest_folio.pdf` — upload in Tab 1 (Guest Folio PDF).
- `02_guest_folio.csv` — alternative folio upload in Tab 1.
- `evidence/` — upload each file into the matching evidence slot in Tab 2.
- `scenario.json` — source data, evidence details, and expected checks.

## Test Steps

1. Use Custom Document Upload, then upload 01_bank_dispute_notice.pdf and either folio PDF or CSV.
2. Open Review & Correct Collected Fields and verify claim statement, 23-digit ARN, MID, AVS, guest email, and check-in time.
3. In Tab 2, confirm the mathematical proofs and upload the files from evidence/ into their matching evidence slots.
4. For POS Signed Slips, save slip reference POS-9812 and amount 87.70 in Probative details.
5. Draft and approve the rebuttal, compile the packet, choose Chase, build the submission bundle, and download it.

## Expected Results

- Completeness should be strong (scenario benchmark: 96%).
- Folio footing, amount, settlement, card, name, and rate proofs should pass.
- Chronology should include 3:15 PM check-in and 15:22 first keycard entry.
- Packet remains exactly 3 pages and the ZIP contains the packet, exhibits, manifest, and instructions.

> Important: generated evidence files have real bytes for upload testing, but their hashes intentionally differ from the demo hashes embedded in scenario.json. The application computes the actual SHA-256 on upload.
