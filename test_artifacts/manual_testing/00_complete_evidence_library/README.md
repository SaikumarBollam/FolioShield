# Complete Evidence Library — Commercial Hospitality Test Records

One upload-ready file for **every evidence type shown in FolioShield Tab 2**, aligned to the primary reference case so the full evidence workspace can be exercised end to end.

**Reference case:** Visa 10.4 · Case V-DISP-89214-X · Jonathan C. Davis · Room 412 · Folio FOL-2026-9812 · 2026-10-10 to 2026-10-13 · Grand Horizon Resort & Suites.

> These are synthetic hospitality business records for software testing. They are not real guest, identity, payment, court, or law-enforcement documents. Verify every fact against source systems in a real case.

## How to use

1. Start FolioShield and choose **New Dispute Case** (or open the Visa 10.4 reference case).
2. Upload the Scenario 1 notice and folio from `../01_visa_10_4_false_fraud/`.
3. In **Tab 2 → Compelling Evidence Collection**, upload each file below into the matching slot.
4. Open **Probative details** / **Court provenance** under a slot when the 'Enter in UI' column gives values to record.
5. Review the Evidence Coverage Status, draft and approve in Tab 3, then compile Executive or Complete packet in Tab 4.

## Complete mapping (all 20 evidence types)

| # | UI Group | Evidence Slot (as shown in UI) | File to Upload | Enter in UI |
|---|---|---|---|---|
| 1 | Front Desk Operations | Signed Registration Card / Digital Check-in | `01_signed_registration_card.png` | Court provenance: Original type = wet_original; location = Front Desk Records Cabinet. |
| 2 | Front Desk Operations | Government Photo ID Verified at Front Desk (verification log) | `02_id_verification_log.pdf` | Court provenance: Original type = system_export; extracted by Front Desk Supervisor. |
| 3 | Payment Authorization | EMV Chip / Contactless Terminal Receipt | `05_emv_terminal_receipt.pdf` | Folio fields should show Auth Code AP98231 and Entry Mode chip. |
| 4 | Payment Authorization | AVS / CVV Authorization Result | `06_avs_cvv_authorization_result.txt` | Probative details: AVS result = Y; CVV result = Match. |
| 5 | Payment Authorization | 3-D Secure Authentication Record (ECI / CAVV) | `07_3ds_authentication_record.txt` | Folio field: 3-D Secure status / ECI = authenticated 05. |
| 6 | Front Desk Operations | Electronic Keycard / Door Lock Audit Trail (Onity / Saflok) | `03_keycard_lock_audit.csv` | Probative details: First entry 2026-10-10 15:22; Last entry 2026-10-13 10:48. Provenance: system Onity HT28 export, Room 412 + stay-date filter. |
| 7 | Incidentals & Proof of Use | POS Signed Slips (restaurant / bar / spa to room) | `11_pos_signed_slips.pdf` | Probative details UI accepts one slip at a time: enter POS-9812 / 87.70 first. The PDF lists both slips; full multi-slip detail is in library_index.json. |
| 8 | Booking & Terms | Booking Confirmation Email (recipient + timestamp) | `08_booking_confirmation.eml` | Probative details: Recipient = jonathan.davis@example.com; Sent at = 2026-09-28 14:02 UTC. |
| 9 | Booking & Terms | Cancellation & No-Show Terms Accepted at Booking (exact text + timestamp) | `09_cancellation_policy_acceptance.pdf` | Probative details: Accepted at = 2026-09-28 14:01 UTC. Paste the policy text into Tab 2 policy box. |
| 10 | Booking & Terms | Guest Communication Log (email / phone / message) | `10_guest_communication_log.pdf` | No required numeric detail. Confirm the log shows no pre-dispute refund request for this case. |
| 11 | Front Desk Operations | Guest Service Log (no unresolved complaints) | `04_guest_service_log.pdf` | Probative details: Unresolved complaints = 0. |
| 12 | Incidentals & Proof of Use | WiFi / Network Usage Log | `12_wifi_usage_log.csv` | Probative details: First seen 2026-10-10 15:31; Last seen 2026-10-13 10:20. |
| 13 | Incidentals & Proof of Use | Incident / Damage Evidence (photos, report, signed clause) | `13_incident_damage_evidence.pdf` | Use primarily with the Mastercard 4859 scenario. Do not treat this as a disputed charge on the Visa 10.4 folio. |
| 14 | Financial Resolution | Refund / Credit Receipt Already Issued | `14_refund_credit_receipt.pdf` | Use primarily with Visa 13.6. In that scenario enter Refund amount = 412.00 and reference RF-884120-6610. |
| 15 | Court / Legal Track (Phase 10) | Booking Clickwrap Record (IP, timestamp, terms version) | `15_booking_clickwrap_record.txt` | Upload in Court/Legal group. Use with the affidavit/clickwrap review in Tab 5. |
| 16 | Court / Legal Track (Phase 10) | CCTV Footage Export (timestamped) | `16_cctv_footage_export.png` | Upload as an image exhibit. In a real case, preserve the original video export and note camera/time range. |
| 17 | Court / Legal Track (Phase 10) | Suspect ID Copy (fraud report; handle per local law) | `17_suspect_id_copy.png` | Use only for workflow testing. Real ID copies require lawful handling and restricted access. |
| 18 | Court / Legal Track (Phase 10) | Witness Declaration (front desk agent) | `18_witness_declaration.pdf` | Prefer generating the declaration in Tab 5 after registering the witness. This file tests the upload slot. |
| 19 | Court / Legal Track (Phase 10) | Demand Letter (certified mail) | `19_demand_letter.pdf` | Prefer generating the demand letter in Tab 5 with the computed net loss and pay-by date. |
| 20 | Court / Legal Track (Phase 10) | Police / IC3 Report Filing | `20_police_ic3_report_record.pdf` | Record the actual agency and report number in Tab 5 Filings Tracker after filing. |

## Scenario-specific evidence still matters

This library proves every upload slot works. For realistic case testing, prefer each scenario folder's own `evidence/` files because amounts, names, dates, and references match that dispute. In particular:

- **Amex C08:** use Scenario 3 slips POS-4102 ($185.00) and VAL-778 ($60.00) for exact-amount binding.
- **Visa 13.6:** use Scenario 5 refund receipt data ($412.00, RF-884120-6610).
- **Mastercard 4859:** use Scenario 6 incident evidence (INC-2214).
- **Court/Legal slots:** prefer generating the affidavit, declaration, and demand letter in Tab 5 for the active case; the library files test the upload slots.

## File formats

PDF business records, PNG image records, CSV lock/WiFi logs, TXT gateway records, and an EML booking confirmation are included so every accepted upload type in the UI can be exercised.
