# 🛡️ FolioShield: Complete Product Consumption & Operations Playbook

Welcome to the **FolioShield Playbook**. This comprehensive manual guides hotel staff, technical operators, and software engineers on every way to consume, integrate, and operate FolioShield.

---

## 📑 Table of Contents

1. [Executive Summary & Personas](#1-executive-summary--personas)
2. [Operating Modes: UI, API, and Library SDK](#2-operating-modes-ui-api-and-library-sdk)
3. [Pathway 1: Interactive Hospitality Web Portal (No-Code)](#3-pathway-1-interactive-hospitality-web-portal-no-code)
   - Step 1: Document Intake (Notice & Folio)
   - Step 2: Multimodal Vision Inspection (Reg Cards & Receipts)
   - Step 3: Review & Stay Data Corrections
   - Step 4: Verification & Compelling Evidence Checklist
   - Step 5: AI Rebuttal Drafting & Manager Sign-Off
   - Step 6: 3-Page Evidence Packet Compilation & Download
   - Step 7: Immutable Audit History Verification
4. [Pathway 2: REST API Server (Low-Code / Webhooks)](#4-pathway-2-rest-api-server-low-code--webhooks)
   - Starting the Server
   - Endpoint Reference & cURL Recipes
   - Automated Webhook Architecture with PMS/BMS
5. [Pathway 3: Embedded Python SDK (Full-Code)](#5-pathway-3-embedded-python-sdk-full-code)
   - Direct Object Ingestion (`NoticeData` & `FolioData`)
   - Batch Processing Pipeline
   - Background Job Queue Integration (Celery / RQ)
6. [Card Network Playbook: Winning Top Hospitality Chargebacks](#6-card-network-playbook-winning-top-hospitality-chargebacks)
   - Visa 10.4 & Mastercard 4837 (Friendly Fraud / Impersonation)
   - Mastercard 4853 & Visa 13.6 (Late Cancellations / No-Shows)
   - Amex C08 (Disputed Incidentals & Dining)
7. [Environment & Deployment Guide (Testing vs. Production)](#7-environment--deployment-guide-testing-vs-production)

---

## 1. Executive Summary & Personas

FolioShield is an outside-in autonomous dispute defense engine designed specifically for hotels. It bridges the gap between bank dispute notices, Property Management Systems (PMS), and payment processor arbitration deadlines.

### Target Personas

| Role | Primary Interface | Typical Workflow |
| :--- | :--- | :--- |
| **Front Desk Agent / Night Auditor** | Web UI (Tab 1 & 2) | Uploads PDF dispute notices from mail/email and pulls folios from OPERA/Mews. Checks physical registration drawers. |
| **Front Office Manager (FOM) / General Manager (GM)** | Web UI (Tab 3 & 4) | Reviews drafted legalistic rebuttal, inputs guest context notes, provides formal manager sign-off, and downloads the 3-page PDF. |
| **Hotel Systems Integrator / IT Engineer** | REST API / Python SDK | Hooks FolioShield into existing PMS night-audit scripts, PMS webhooks, or dispute intake queue. |

---

## 2. Operating Modes: UI, API, and Library SDK

FolioShield can be consumed through three distinct pathways depending on technical infrastructure:

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              FOLIOSHIELD CORE                               │
│        Reconciliation Engine • Llama 3.3 70B • ReportLab 3-Page PDF         │
└──────────────▲──────────────────────────────▲──────────────────────────────▲┘
               │                              │                              │
    ┌──────────┴──────────┐        ┌──────────┴──────────┐        ┌──────────┴──────────┐
    │  PATHWAY 1: WEB UI  │        │  PATHWAY 2: REST API│        │  PATHWAY 3: PY SDK  │
    │  Streamlit Portal   │        │  HTTP JSON Webhooks │        │  Direct Python SDK  │
    │  (Front-Desk Staff) │        │  (BMS / PMS Server) │        │  (Custom Pipelines) │
    └─────────────────────┘        └─────────────────────┘        └─────────────────────┘
```

---

## 3. Pathway 1: Interactive Hospitality Web Portal (No-Code)

Access the live portal at `http://localhost:8501`.

### Step 1: Document Intake (Notice & Folio)
1. Navigate to **`📄 1. Upload Notice & Guest Folio`**.
2. **Left Column**: Upload the bank's dispute notice (PDF). FolioShield automatically extracts the Case ID, Network, Reason Code, Disputed Amount, Card Last-4, and Response Deadline.
3. **Right Column**: Upload the guest folio (PDF or CSV export from Oracle OPERA, Cloudbeds, Mews, etc.).
4. The system validates the files against magic-byte signatures and limits (10MB default).

### Step 2: Multimodal Vision Inspection (Reg Cards & Receipts)
1. Under **`👁️ Scanned Reg Card & Signature Check (Vision AI)`**, upload a scan or smartphone photo of:
   - Physical paper registration card with guest signature
   - Signed restaurant dining / room service chits
   - Front-desk government photo ID photocopy
2. Click **`Run Llama Vision Analysis`**. Meta Llama Vision checks for handwriting, guest signature presence, and name matches without saving unmasked PANs.

### Step 3: Review & Stay Data Corrections
1. Open the expander **`✏️ Review & Correct Stay Details`**.
2. Compare the extracted fields with the PMS.
3. If an OCR error occurred (e.g., room number misread or date offset), correct it in the form and click **`Save corrections`**. Any edits are permanently logged in the audit trail.

### Step 4: Verification & Compelling Evidence Checklist
1. Navigate to **`🔍 2. Stay & Billing Verification`**.
2. Review the **Dispute Reason Explanation** and the **🏨 Hotel Defense Playbook (How to Win)**.
3. Inspect **Stay & Billing Match Highlights**: FolioShield verifies whether the disputed amount matches the folio charges, or flags partial chargebacks and uncollected open balances.
4. Review the **3. Front Desk Proof Checklist**:
   - Check the boxes for documents you have physically or electronically on file (`Signed Registration Card`, `EMV Chip / AVS Auth`, `Keycard Lock Logs`, `Cancellation Policy Acknowledged`, `Guest ID Copy`).
   - The **Evidence Coverage Status** updates dynamically.
5. *(Optional)* Paste the exact cancellation wording displayed to the guest at booking into the **Cancellation & booking terms on file** box.

### Step 5: AI Rebuttal Drafting & Manager Sign-Off
1. Navigate to **`✍️ 3. Dispute Response Letter`**.
2. In **Front Desk Notes / Special Guest Context**, enter qualitative operational facts:
   > *"Guest checked in at 3:15pm with agent Sarah, had dinner at Ocean Grill with a party of 4 on night 2, and concierge booked airport car service."*
3. Click **`✨ Draft Response Letter`**.
   - Meta Llama 3.3 70B (or the deterministic offline defense engine) drafts a card-network-compliant representment letter citing the exact evidence checked in Tab 2.
   - Missing evidence is marked with `[MISSING: <item>]` tags so staff never submit unsubstantiated claims.
4. Review and edit the draft directly in the editor.
5. In the sidebar, ensure your name is entered under **Reviewer name**.
6. Click **`✅ Manager Sign-Off & Approve`**. The rebuttal is locked and fingerprinted with a SHA-256 hash.

### Step 6: 3-Page Evidence Packet Compilation & Download
1. Navigate to **`📑 4. Generate Bank Evidence Packet`**.
2. Click **`🔨 Compile 3-Page Bank Evidence Packet`**.
3. ReportLab builds a guaranteed 3-page PDF scaled with shrink-to-fit frames:
   - **Page 1**: Dispute cover letter, metadata, full rebuttal statement, manager approval timestamp, and signature lines.
   - **Page 2**: Itemized folio accounting ledger, daily rates, taxes, incidentals, auth code, and reconciliation audit.
   - **Page 3**: Card network compelling evidence checklist, supporting documents index, booking cancellation policy terms, and tamper-evident SHA-256 integrity seal.
4. Click **`📥 Download Bank Dispute Packet (PDF)`**. The packet is immediately ready to upload to merchant portals (Chase Paymentech, Elavon, Stripe, Worldpay) or send via fax.

### Step 7: Immutable Audit History Verification
1. Navigate to **`🔒 5. Staff Activity & History`**.
2. Verify the SHA-256 hash chain (`verify_chain()`) confirming zero unauthorized modifications.
3. Download the `.jsonl` audit record for internal compliance.

---

## 4. Pathway 2: REST API Server (Low-Code / Webhooks)

For hotels with central IT, Building Management Systems (BMS), or custom PMS integrations, FolioShield includes a zero-dependency HTTP REST API.

### Starting the API Server
```bash
python -m core.api
```
*Runs on `http://0.0.0.0:8000` (customizable via `API_PORT` in `.env`).*

### Endpoint Quick Reference

#### 1. Service Health Check
```bash
curl http://localhost:8000/health
```

#### 2. Reconcile Dispute Notice & Folio
```bash
curl -X POST http://localhost:8000/api/v1/reconcile \
  -H "Content-Type: application/json" \
  -d '{
    "notice": {
      "case_id": "V-DISP-89214-X",
      "card_network": "Visa",
      "reason_code": "10.4",
      "disputed_amount": 1280.50,
      "card_last_4": "4821",
      "cardholder_name": "Jonathan C. Davis"
    },
    "folio": {
      "hotel_name": "Grand Horizon Resort & Suites",
      "room_number": "412",
      "check_in": "2026-10-10",
      "check_out": "2026-10-13",
      "total_charges": 1280.50,
      "total_payments": 1280.50,
      "card_last_4": "4821",
      "auth_code": "AP98231"
    },
    "supporting_docs": {
      "signed_registration_card": true,
      "emv_chip_or_avs_auth": true,
      "keycard_or_wifi_audit": true
    }
  }'
```

#### 3. Draft Llama 3.3 Rebuttal
```bash
curl -X POST http://localhost:8000/api/v1/rebuttal/draft \
  -H "Content-Type: application/json" \
  -d '{
    "notice": {"case_id": "V-DISP-89214-X", "card_network": "Visa", "reason_code": "10.4", "disputed_amount": 1280.50},
    "folio": {"hotel_name": "Grand Horizon Resort", "room_number": "412", "total_charges": 1280.50},
    "custom_notes": "Guest ordered room service and used pool cabana."
  }'
```

#### 4. End-to-End Headless Dispute Processing
Send raw dispute data and receive the rebuttal + Base64-encoded 3-page PDF evidence packet in a single call:
```bash
curl -X POST http://localhost:8000/api/v1/dispute/process \
  -H "Content-Type: application/json" \
  -d '{
    "notice": {
      "case_id": "V-DISP-89214-X",
      "card_network": "Visa",
      "reason_code": "10.4",
      "disputed_amount": 1280.50,
      "card_last_4": "4821",
      "cardholder_name": "Jonathan C. Davis"
    },
    "folio": {
      "hotel_name": "Grand Horizon Resort",
      "room_number": "412",
      "check_in": "2026-10-10",
      "check_out": "2026-10-13",
      "total_charges": 1280.50,
      "total_payments": 1280.50,
      "card_last_4": "4821",
      "auth_code": "AP98231",
      "line_items": [
        {"date": "2026-10-10", "description": "Room Accommodation", "amount": 320.00, "type": "Charge"},
        {"date": "2026-10-13", "description": "Visa Payment", "amount": 1280.50, "type": "Credit"}
      ]
    },
    "reviewer_name": "Automated BMS Integration"
  }'
```

---

## 5. Pathway 3: Embedded Python SDK (Full-Code)

Install or copy `core/` into your hotel backend application:

```python
from core import FolioShield, NoticeData, FolioData

# Initialize SDK client
fs = FolioShield()

# 1. Parse raw files directly from storage or S3
with open("dispute_notice.pdf", "rb") as f:
    notice = fs.extract_notice_from_pdf(f.read())

with open("guest_folio.csv", "rb") as f:
    folio = fs.extract_folio_from_csv(f.read())

# 2. Programmatically reconcile and calculate completeness score
recon = fs.reconcile(notice, folio, supporting_docs={
    "signed_registration_card": True,
    "emv_chip_or_avs_auth": True,
    "keycard_or_wifi_audit": True,
    "id_verification_copy": True
})

# 3. Draft AI Rebuttal
rebuttal = fs.draft_rebuttal(
    notice, 
    folio, 
    recon, 
    custom_instructions="Concierge verified guest identity on departure."
)

# 4. Generate 3-page PDF Packet
pdf_bytes = fs.generate_pdf_packet(
    notice,
    folio,
    recon,
    rebuttal,
    approved_by="GM Robert Vance",
    policy_text="All reservations subject to 48h cancellation notice."
)

with open(f"Evidence_Packet_{notice.case_id}.pdf", "wb") as f:
    f.write(pdf_bytes)
```

---

## 6. Card Network Playbook: Winning Top Hospitality Chargebacks

### A. Visa 10.4 & Mastercard 4837 (Fraud / Unauthorized Card Use)
- **Guest Claim**: *"I never made this booking and I did not authorize charges."*
- **Hotel Defense Strategy**: Establish **physical nexus**. Prove the cardholder or their authorized party physically registered and occupied the room.
- **Compelling Evidence to Assemble**:
  1. Signed guest registration card acknowledging room rates.
  2. Electronic keycard door lock audit showing multiple entries during stay dates.
  3. Positive EMV chip terminal or AVS/CVV authorization code.
  4. Incidental charges incurred on-site (restaurant, parking, spa).

### B. Mastercard 4853 & Visa 13.6 (Cancelled / Services Not Rendered)
- **Guest Claim**: *"I cancelled my reservation in time and should not have been charged."*
- **Hotel Defense Strategy**: Prove **adherence to disclosed cancellation cutoff**.
- **Compelling Evidence to Assemble**:
  1. Reservation confirmation email displaying cancellation terms prior to booking completion.
  2. Timestamped cancellation audit showing guest cancelled after the cutoff window (or was a no-show).
  3. Proof room was guaranteed and held off the market for the cardholder.

### C. American Express C08 (Disputed Incidentals / Partial Chargeback)
- **Guest Claim**: *"I stayed at the hotel, but I did not order the dining charges or valet parking."*
- **Hotel Defense Strategy**: Provide **itemized proof of incidental authorization**.
- **Compelling Evidence to Assemble**:
  1. Itemized folio showing room charge vs. contested incidental split.
  2. Signed restaurant / bar check containing room number and guest signature.
  3. PMS night-audit ledger proving non-disputed room charges were settled.

---

## 7. Environment & Deployment Guide (Testing vs. Production)

Configure FolioShield for production or local testing using `.env`:

```env
# -------------------------------------------------------------
# TESTING MODE (Demonstrations, QA, Staff Training)
# -------------------------------------------------------------
ENVIRONMENT=testing
LLAMA_PROVIDER=mock          # Zero API keys needed; deterministic defense
ENABLE_TEST_SCENARIOS=true   # Scenario loader enabled in UI
SHOW_DEBUG_DETAILS=true      # Displays raw OCR and parsing expanders

# -------------------------------------------------------------
# PRODUCTION DEPLOYMENT (Live Hotel Operations)
# -------------------------------------------------------------
# ENVIRONMENT=production
# LLAMA_PROVIDER=groq
# GROQ_API_KEY=gsk_your_production_key_here
# ENABLE_TEST_SCENARIOS=false # Hides mock data to prevent ledger pollution
# SHOW_DEBUG_DETAILS=false    # Clean, focused front-desk interface
# FOLIOSHIELD_MERCHANT_NAME="Grand Horizon Resort & Suites"
# HOTEL_CONTACT_EMAIL="disputes@grandhorizonresort.com"
# MAX_UPLOAD_SIZE_MB=10
# LOG_DIR=/var/log/folioshield
```

---

*FolioShield is an evidence preparation and decision-support tool. Generated dispute packets should be reviewed by authorized staff prior to submission to acquiring banks or dispute portals.*
