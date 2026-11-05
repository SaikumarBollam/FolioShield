# FolioShield — 7-Scene Enterprise SaaS Product Demo Storyboard

- **Product**: FolioShield v1.2 (`https://github.com/SaikumarBollam/FolioShield`)
- **Inspected Branch & Baseline**: `feature/enterprise-readiness` (PR #2 commit `8380d79`, merged via `35c072a` into `main` `2faf4db` `v1.2.0`; **260 automated tests passing**)
- **Output Format**: `1920×1080` (`16:9`), `30 FPS` Constant Frame Rate, `H.264` (`libx264` High Profile) + `AAC` 48 kHz Stereo, **180.000 seconds (`5,400` frames)**
- **Dataset**: 100% synthetic hotel transaction fixtures (`test_artifacts/manual_testing/01_visa_10_4_false_fraud/` — Case `V-DISP-89214-X`, Folio `FOL-2026-9812`, Room `412`, `$1,280.50 USD`, synthetic card ending `4821`)
- **Governance & Honesty Guardrails**:
  - 100% live application execution captured from running Streamlit server (`app.py`) — zero mockups or fabricated UI.
  - Clearly distinguishes implemented capabilities from planned roadmap items.
  - Explicitly states that FolioShield prepares validated PDF packets and ZIP bundles for **staff upload to acquirer portals** (no automatic bank submission) and claims **no** PCI-DSS, SOC 2, GDPR, or regulatory certifications.

---

## Scene-by-Scene Timeline Summary (180.00s / 5,400 Frames @ 30 FPS)

| Scene | Timecode | Duration | Frame Range | Primary Workflow & Application Module |
| :--- | :--- | :--- | :--- | :--- |
| **Scene 1** | `00:00 – 00:26` | `26.0s` | `0000 – 0779` | Branded Intro + Outside-In Document Intake & Field Review (`Tab 1`, `core/extractor.py`) |
| **Scene 2** | `00:26 – 00:52` | `26.0s` | `0780 – 1559` | Deterministic Financial Reconciliation & 10 Mathematical Proofs (`Tab 2`, `core/reconciler.py`) |
| **Scene 3** | `00:52 – 01:20` | `28.0s` | `1560 – 2399` | Compelling Evidence Bulk ZIP Import, SHA-256 Custody & Validators (`Tab 2`, `core/evidence_validators.py`, `core/exhibit_store.py`) |
| **Scene 4** | `01:20 – 01:46` | `26.0s` | `2400 – 3179` | AI-Assisted Rebuttal Generation, Source-Fact Guardrails & `[MISSING]` Detection (`Tab 3`, `core/llm_engine.py`) |
| **Scene 5** | `01:46 – 02:08` | `22.0s` | `3180 – 3839` | Submission Readiness Gate, Segregation of Duties & Canonical v2 Human Sign-Off (`Tab 3`, `core/fingerprint.py`) |
| **Scene 6** | `02:08 – 02:36` | `28.0s` | `3840 – 4679` | 3-Page PDF Evidence Packet Compilation & Chase Paymentech Submission ZIP (`Tab 4`, `core/pdf_generator.py`, `core/submission.py`) |
| **Scene 7** | `02:36 – 03:00` | `24.0s` | `4680 – 5399` | Tamper-Evident SHA-256 Audit Chain, Enterprise Integrations & Honest Roadmap (`Tab 7`, `Tab 6`, Closing Card) |

---

## Detailed 7-Scene Storyboard

### Scene 1 — Outside-In Document Intake & Extraction (`00:00 – 00:26` | `26.0s` | Frames `0–779`)
- **Visual Sequence**:
  - `00:00 – 00:04.4`: Branded FolioShield enterprise title card in official semantic design tokens (`Deep Navy #173B50`, `Muted Gold #D5B77A`, `Off-White #F5F5F0`, `Dark Canvas #13191D`), displaying the 7-stage workflow pill bar and synthetic-data disclosure.
  - `00:04.4 – 00:05.0`: `0.6s` cubic cross-dissolve into live FolioShield Streamlit application (`Tab 1: 1. Upload Notice & Guest Folio`).
  - `00:05.0 – 00:26.0`: Intake reviewer `Alex Rivera (Night Auditor)` sets sidebar reviewer attribution, uploads synthetic `Visa_10_4_Dispute_Notice_V-DISP-89214-X.pdf` (auto-extracting Visa `10.4`, `$1,280.50`, 23-digit ARN `24492156291002918274019`, card last-4 `4821`, and cardholder claim statement) and `Guest_Folio_Room412_FOL-2026-9812.csv`, then opens `Review & Correct Collected Fields` to verify and save PMS authorization metadata (`GH-884120`, `AP98231`, `AVS: Y - full match`, `CVV: Match`, `chip`), updating top-bar KPIs to `$1,280.50` Exact Match (`$0.00` variance).
- **Spoken Narration (`00:01.20 – 00:24.38`, `23.18s`)**:
  > "Hotels lose thousands each month to false card-not-present chargebacks, while stay evidence sits scattered across folios, terminals, and lock logs. FolioShield uses an outside-in, document-first workflow. With synthetic hotel data, we upload a Visa 10.4 dispute notice and guest folio CSV, then verify and save payment metadata into an audited case."
- **Capability Status**: **Implemented** (`core/extractor.py`, `core/security.py`, `app.py` Tab 1).

---

### Scene 2 — Deterministic Financial Reconciliation (`00:26 – 00:52` | `26.0s` | Frames `780–1559`)
- **Visual Sequence**:
  - `00:26.0 – 00:26.4`: Smooth `12`-frame cross-dissolve + top-bar `SCENE 02 / 07` badge transition.
  - Navigate to `Tab 2: 2. Stay & Billing Verification`.
  - Display the `Visa 10.4` dispute category, quoted cardholder claim (*"I did not authorize or participate in this lodging transaction."*), and `Hotel Defense Playbook (How to Win)`.
  - Scroll smoothly to `Mathematical Proof Panel` confirming **all 10 deterministic proofs `[PROVEN]`**: `Folio Footing` (`Σ charges $1,280.50 = credits $1,280.50; balance $0.00`), `Rate Recomputation` (`3 nights × $320.00 = $960.00` + `14.50%` tax `$139.20`), `Amount`, `Settlement`, `Duplicate Check`, `Card Last4` (`****4821`), `Guest Name` (`1.00`), `Folio Identity` (`100%`), `Transaction Date`, and `Deadline` (`3 calendar / 2 business days to 2026-11-07`).
  - Scroll to `2. Room Charges & Incidentals Breakdown` showing the 10 itemized PMS lines.
- **Spoken Narration (`00:26.80 – 00:50.30`, `23.50s`)**:
  > "In Stay and Billing Verification, FolioShield pairs Visa 10.4 defense guidance with the cardholder's exact quoted claim. Its deterministic reconciliation engine executes ten mathematical proofs, confirming folio footing to a zero balance, three nights at three hundred twenty dollars plus tax, card last-four 4821, authorization AP98231, and one hundred percent identity confidence."
- **Capability Status**: **Implemented** (`core/reconciler.py`, `core/rules.py`).

---

### Scene 3 — Evidence Validation & Content-Addressed Custody (`00:52 – 01:20` | `28.0s` | Frames `1560–2399`)
- **Visual Sequence**:
  - `00:52.0 – 00:52.4`: Smooth scene transition into `3. Compelling Evidence Collection (Files Win Cases)`.
  - Open `Bulk import — upload a ZIP of evidence files` and upload `Synthetic_Stay_Evidence_Room412.zip` containing 10 synthetic guest-stay files (`01_signed_registration_card.pdf` through `10_wifi_usage_log.csv`).
  - FolioShield routes all 10 files by slot key (`0` unmatched), computes real **SHA-256 content-addressed hashes**, and retains bytes in `ExhibitStore`.
  - Open `Probative details — POS Signed Slips (restaurant / bar / spa to room)`, bind slip reference `POS-9812` and exact amount `87.70`, and click `Save details`.
  - Inspect `Evidence coverage status` table (`Dispositive`, `Required`, and `Supporting` tiers all `Available (file collected)`) and return to top KPI cards showing **`Evidence Completeness: 100% (Strong Evidence Coverage)`**.
- **Spoken Narration (`00:52.80 – 01:17.95`, `25.15s`)**:
  > "Next, we bulk-import ten synthetic stay exhibits, including the signed registration card, EMV chip receipt, Onity keycard audit, ID log, and Wi-Fi CSV. Every file is SHA-256 hashed into content-addressed storage. Recording dining slip POS-9812 for eighty-seven dollars and seventy cents satisfies all validators, achieving one hundred percent evidence completeness."
- **Capability Status**: **Implemented** (`core/zip_import.py`, `core/exhibit_store.py`, `core/evidence_validators.py`, `core/infrastructure/storage/`).

---

### Scene 4 — AI-Assisted Rebuttal Studio & Source-Fact Guardrails (`01:20 – 01:46` | `26.0s` | Frames `2400–3179`)
- **Visual Sequence**:
  - `01:20.0 – 01:20.4`: Scene transition into `Tab 3: 3. Dispute Response Letter`.
  - Open sidebar `Inference Provider` dropdown showing supported cloud Meta Llama 3.3 70B providers (`Direct Meta API`, `Groq`, `Fireworks AI`) alongside the transparent banner `Direct Meta API key not configured — local fallback will be used`.
  - Enter verified front-desk context notes (*"Guest checked in at 3:15 PM at Terminal T-04 with wet signature and driver license verification; 14 Onity keycard entries logged for Room 412."*) and click `Draft Response Letter`.
  - Scroll through the generated **5-section representment letter** citing `Exhibits A–I`, expand `System-Verified Facts`, and show the red `Submission Readiness Gate` catching `Draft contains 1 unresolved [MISSING] marker(s)` (`- [MISSING: booking date]`) rather than inventing an unextracted booking date.
- **Spoken Narration (`01:20.80 – 01:42.62`, `21.82s`)**:
  > "In the Dispute Response Studio, FolioShield supports Meta Llama 3.3 70B via Direct Meta, Groq, or Fireworks AI, plus a deterministic local fallback active here offline. Adding verified front-desk notes drafts a five-section rebuttal citing Exhibits A through I, while flagging a missing booking date instead of fabricating unverified facts."
- **Capability Status**: **Implemented** (`core/llm_engine.py`, `core/chronology.py`, `core/rebuttal_validator.py`). Online LLM drafting requires an external provider API key; deterministic offline fallback runs out-of-the-box with zero external dependencies.

---

### Scene 5 — Submission Readiness Gate & Mandatory Human Sign-Off (`01:46 – 02:08` | `22.0s` | Frames `3180–3839`)
- **Visual Sequence**:
  - `01:46.0 – 01:46.4`: Scene transition remaining in `Tab 3`.
  - Replace `- [MISSING: booking date]` in the rebuttal editor with the verified timestamp from the Booking Confirmation exhibit (`- 2026-09-28 14:02 UTC — Direct web reservation GH-884120 booked and confirmed to jonathan.davis@example.com.`).
  - Watch `Submission Readiness Gate` immediately clear to green: **`All required collection items are present.`**
  - Demonstrate two-person segregation of duties: update sidebar Reviewer to **`Elena Vance` (`Front Office Manager`)** and click **`Manager Sign-Off & Approve`**.
  - Display the green cryptographic approval confirmation showing `Approved by Elena Vance (Front Office Manager)` bound to a **Canonical v2 SHA-256 Case Fingerprint** and audit event hash.
- **Spoken Narration (`01:46.80 – 02:06.70`, `19.90s`)**:
  > "The Submission Readiness Gate blocks sign-off until that placeholder is resolved. Once manager Elena Vance enters the confirmed September twenty-eighth booking timestamp, the gate clears. Her explicit Manager Sign-Off locks the case under a canonical SHA-256 fingerprint, ensuring automated workflows never fabricate human approval."
- **Capability Status**: **Implemented** (`core/fingerprint.py`, `core/application/dispute_service.py`). Note: current UI reviewer attribution is self-asserted text/role; enterprise human OIDC/SSO authentication is a planned roadmap capability.

---

### Scene 6 — 3-Page PDF Evidence Packet & Processor Submission Bundle (`02:08 – 02:36` | `28.0s` | Frames `3840–4679`)
- **Visual Sequence**:
  - `02:08.0 – 02:08.4`: Scene transition into `Tab 4: 4. Generate Bank Evidence Packet`.
  - Click `Compile Executive Packet (3 Pages)` and download `FolioShield_Dispute_V-DISP-89214-X.pdf`.
  - Inspect both the live inline `st.pdf` viewer (`Packet Size`, `Packet SHA-256`) and a side-by-side 3-page inspection view of the **actual compiled ReportLab PDF** (Page 1: Dispute Cover Letter & Signed Rebuttal; Page 2: Itemized Folio & Reconciliation Audit; Page 3: Evidence Annex & SHA-256 Integrity Seal).
  - Select `Chase Merchant Services (Paymentech / Chase Orbital)` in the portal profile picker, show all **9 `[PASS]` Pre-submission validation** checks, click `Build Submission Bundle (ZIP)` (auto-converting CSV and `.eml` exhibits to PDF), and download `V-DISP-89214-X_Submission.zip`.
- **Spoken Narration (`02:08.80 – 02:30.06`, `21.26s`)**:
  > "With approval locked, ReportLab compiles a three-page Bank Evidence Packet: signed rebuttal cover, itemized folio audit, and an evidence annex with a SHA-256 custody seal. Selecting Chase Paymentech passes all nine pre-submission checks and packages a validated ZIP bundle, converting CSV and email exhibits to PDF for staff portal upload."
- **Capability Status**: **Implemented** (`core/pdf_generator.py`, `core/portals.py`, `core/submission.py`). **Operational Boundary**: FolioShield builds validated packets and portal-ready ZIP bundles; **hotel staff perform the acquirer portal upload** (no automatic bank submission).

---

### Scene 7 — Tamper-Evident Audit Trail, Enterprise Readiness & Honest Roadmap (`02:36 – 03:00` | `24.0s` | Frames `4680–5399`)
- **Visual Sequence**:
  - `02:36.0 – 02:36.4`: Scene transition into `Tab 7: 7. Staff Activity & History`.
  - Display green **`Chain verified`** banner over all chronological SHA-256 hash-chained events (`notice_uploaded`, `folio_uploaded`, `fields_corrected`, `evidence_zip_imported`, `evidence_details_updated`, `rebuttal_drafted`, `rebuttal_approved`, `pdf_packet_generated`, `submission_bundle_built`), download `custody_manifest_V-DISP-89214-X.json`, and show `Case History Across Sessions`.
  - Switch to `Tab 6: Integration Management` for synthetic tenant `grand-horizon-group`, displaying tenant monitoring (`1/1 active` Connector Agent), PBKDF2-hashed API credentials, HMAC-signed webhook subscriptions, Embedded CSP diagnostics (`"oidc_status": "Requires identity-provider validation (not production-verified)"`), and WCAG 2.2 AA `Night Mode`.
  - `02:56.2 – 03:00.0`: Cross-dissolve to Closing Branded End Card summarizing **Implemented & Verified (260 Passing Tests)** vs **Planned Roadmap & Operational Boundaries**.
- **Spoken Narration (`02:36.70 – 02:56.31`, `19.61s`)**:
  > "Every step is verified in a hash-chained SHA-256 audit log with custody manifests. Enterprise-readiness adds FastAPI, SQLAlchemy, S3 storage, webhooks, and agents, while human SSO and full multi-tenancy remain planned, with no auto-submission or claimed certifications."
- **Capability Status**:
  - **Implemented**: Hash-chained JSONL `AuditLogger` + cross-session `audit_index`, FastAPI `core/api_asgi.py`, SQLAlchemy 2.0 + Alembic initial migration, Local/S3/Memory `StorageBackend`, machine Bearer credentials, HMAC-signed webhooks, outbound Connector Agent, signed embedded context, WCAG 2.2 AA Light/Night theme.
  - **Planned Roadmap**: Enterprise human OIDC/SSO login lifecycle, platform-wide multi-tenant isolation across all legacy Streamlit/JSONL paths, managed cloud TLS/KMS/WORM retention deployment. Zero compliance certifications (PCI-DSS, SOC 2, GDPR) claimed.
