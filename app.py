"""
FolioShield: Autonomous Chargeback Defense & Evidence Builder
Meta Llama Hackathon Submission — Track: Build for Your World

Workflow: Upload → Extract → (Vision) → Review fields → Reconcile → Evidence checklist
          → Draft (Llama 3.3 70B / template) → Human approval → 3-page PDF packet.
"""

import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from core.audit_logger import AuditLogger
from core.extractor import DocumentExtractor, ExtractionError
from core.llm_engine import OFFLINE_PROVIDER, PROVIDERS, LlamaEngine
from core.pdf_generator import EvidencePacketGenerator
from core.reconciler import Reconciler
from core.rules import SUPPORTING_DOC_TYPES
from core.security import validate_upload
from data.sample_scenarios import SCENARIOS

load_dotenv()
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DEFAULT_MERCHANT = os.getenv("FOLIOSHIELD_MERCHANT_NAME", "Grand Horizon Resort & Suites")
CARD_NETWORKS = ["Visa", "Mastercard", "American Express", "Discover"]
PROVIDER_OPTIONS = {
    "Offline / Template Mode": OFFLINE_PROVIDER,
    "Groq": "groq",
    "Together AI": "together",
    "OpenRouter": "openrouter",
}
SCENARIO_OPTIONS = {
    "visa_fraud_10_4": "Visa 10.4: False Fraud Claim ($1,280.50)",
    "mc_cancellation_4853": "Mastercard 4853: Late Cancel ($690.00)",
    "amex_partial_c08": "Amex C08: Partial Incidental ($245.00)",
    "custom": "📂 Custom Document Upload",
}
DEFAULT_SCENARIO = "visa_fraud_10_4"


# -----------------------------------------------------------------------------
# PAGE SETUP & STYLING
# -----------------------------------------------------------------------------
st.set_page_config(
    page_title="FolioShield | Hotel Chargeback Defense",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1E3A8A; margin-bottom: 0px; }
    .sub-header { font-size: 1.05rem; color: #475569; margin-bottom: 20px; }
    .stTabs [data-baseweb="tab-list"] { gap: 8px; }
    .stTabs [data-baseweb="tab"] { padding: 10px 18px; border-radius: 6px 6px 0px 0px; font-weight: 600; }
    .badge { display: inline-block; padding: 3px 8px; font-size: 12px; font-weight: 600;
             border-radius: 4px; background-color: #DBEAFE; color: #1E40AF; }
</style>
""", unsafe_allow_html=True)


# -----------------------------------------------------------------------------
# STATE HELPERS
# -----------------------------------------------------------------------------
def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def empty_notice() -> Dict[str, Any]:
    return {k: None for k in ("case_id", "card_network", "reason_code", "reason_description", "transaction_date",
                              "dispute_date", "response_deadline", "cardholder_name", "card_last_4", "arn")} | {
        "disputed_amount": 0.0, "original_amount": 0.0, "currency": "USD", "raw_text": ""}


def empty_folio() -> Dict[str, Any]:
    return {k: None for k in ("hotel_name", "hotel_address", "guest_name", "folio_number", "room_number",
                              "check_in", "check_out", "card_last_4", "auth_code")} | {
        "rate_per_night": 0.0, "total_charges": 0.0, "total_payments": 0.0, "balance": 0.0,
        "line_items": [], "raw_text": ""}


def actor() -> str:
    return (st.session_state.get("reviewer_name") or "").strip() or "Staff Reviewer"


def log(action: str, details: Dict[str, Any]) -> None:
    st.session_state.audit_logger.log_event(action, details, user=actor())


def reset_outputs() -> None:
    """Invalidates anything derived from the case data (draft, approval, packet, vision findings)."""
    st.session_state.rebuttal_editor = ""
    st.session_state.draft_engine = None
    st.session_state.approval = None
    st.session_state.generated_pdf = None
    st.session_state.pdf_fingerprint = None


def set_supporting_docs(docs: Dict[str, bool]) -> None:
    for key in SUPPORTING_DOC_TYPES:
        st.session_state[f"doc_{key}"] = bool(docs.get(key, False))


def load_case(notice: Dict[str, Any], folio: Dict[str, Any], docs: Dict[str, bool]) -> None:
    st.session_state.notice_data = json.loads(json.dumps(notice))  # deep copy; never mutate SCENARIOS
    st.session_state.folio_data = json.loads(json.dumps(folio))
    set_supporting_docs(docs)
    st.session_state.processed_uploads = {}
    st.session_state.vision_audit_result = None
    st.session_state.vision_image_hash = None
    reset_outputs()


def init_state() -> None:
    if "audit_logger" in st.session_state:
        return
    st.session_state.audit_logger = AuditLogger()
    st.session_state.current_scenario_key = DEFAULT_SCENARIO
    st.session_state.custom_notes = ""
    st.session_state.policy_text = ""
    s = SCENARIOS[DEFAULT_SCENARIO]
    load_case(s["notice"], s["folio"], s["supporting_docs"])


def current_supporting_docs() -> Dict[str, bool]:
    return {key: bool(st.session_state.get(f"doc_{key}", False)) for key in SUPPORTING_DOC_TYPES}


def case_fingerprint(notice: Dict[str, Any], folio: Dict[str, Any], docs: Dict[str, bool], draft: str, policy: str) -> str:
    """Hash of everything that goes into the packet — used to detect stale approvals / PDFs."""
    payload = json.dumps({"n": notice, "f": folio, "d": docs, "r": draft, "p": policy}, sort_keys=True, default=str)
    return sha256_text(payload)


def new_upload(slot: str, data: bytes) -> bool:
    """True only the first time a given file is seen in a slot (Streamlit reruns the script on every click)."""
    digest = AuditLogger.calculate_sha256(data)
    if st.session_state.processed_uploads.get(slot) == digest:
        return False
    st.session_state.processed_uploads[slot] = digest
    return True


init_state()


# -----------------------------------------------------------------------------
# SIDEBAR CONTROLS
# -----------------------------------------------------------------------------
with st.sidebar:
    st.markdown("## 🛡️ **FolioShield**")
    st.caption("**Autonomous Chargeback Defense & Evidence Builder**\n*Meta Llama Hackathon Submission*")
    st.markdown("---")

    st.markdown("### ⚡ **Test Scenario Quick-Loader**")
    selected_scenario = st.selectbox(
        "Choose test scenario or custom upload:",
        options=list(SCENARIO_OPTIONS.keys()),
        format_func=SCENARIO_OPTIONS.get,
        index=list(SCENARIO_OPTIONS).index(st.session_state.current_scenario_key),
    )
    if selected_scenario != st.session_state.current_scenario_key:
        st.session_state.current_scenario_key = selected_scenario
        if selected_scenario == "custom":
            load_case(empty_notice(), empty_folio(), {})
            log("custom_case_started", {"message": "Cleared case for custom document upload"})
        else:
            s_data = SCENARIOS[selected_scenario]
            load_case(s_data["notice"], s_data["folio"], s_data["supporting_docs"])
            log("scenario_loaded", {"scenario": selected_scenario, "message": f"Loaded {s_data['title']}"})
        st.rerun()

    st.markdown("---")
    st.markdown("### 👤 **Reviewer**")
    st.text_input("Reviewer name (recorded in audit log):", key="reviewer_name", placeholder="e.g. A. Rivera, Revenue Manager")
    merchant_name = st.text_input("Merchant / property name:", value=DEFAULT_MERCHANT,
                                  help="Used when the uploaded folio does not state the property name.")

    st.markdown("---")
    st.markdown("### 🤖 **Meta Llama AI Engine**")
    env_provider = os.getenv("LLAMA_PROVIDER", OFFLINE_PROVIDER).lower()
    provider_labels = list(PROVIDER_OPTIONS)
    default_label = next((lbl for lbl, code in PROVIDER_OPTIONS.items() if code == env_provider), provider_labels[0])
    provider_label = st.selectbox("Inference Provider:", options=provider_labels, index=provider_labels.index(default_label))
    provider_code = PROVIDER_OPTIONS[provider_label]

    api_key_input = ""
    if provider_code != OFFLINE_PROVIDER:
        env_var = PROVIDERS[provider_code].api_key_env
        api_key_input = st.text_input(
            "Provider API Key:",
            type="password",
            placeholder=f"Leave blank to use ${env_var}",
            help="Keys are held in memory for this session only and are never written to logs or packets.",
        )

    llama_engine = LlamaEngine(provider=provider_code, api_key=api_key_input or None)
    if llama_engine.is_api_configured():
        st.success(f"🟢 {provider_label} key configured (Llama 3.3 70B + Vision)")
    elif provider_code == OFFLINE_PROVIDER:
        st.info("🟡 Offline template mode — no data leaves this machine")
    else:
        st.warning("🟠 No API key found — falling back to offline template")

    st.markdown("---")
    st.markdown("### 🔐 **Compliance Safeguards**")
    st.checkbox("PCI-DSS Card Masking (PAN Redaction)", value=True, disabled=True,
                help="Always enforced: card numbers are masked at extraction time, before storage or display.")
    st.caption("Full card numbers are never stored; only the last 4 digits are retained.")


# -----------------------------------------------------------------------------
# DERIVED CASE STATE (computed before rendering so metrics are never one click behind)
# -----------------------------------------------------------------------------
supporting_docs = current_supporting_docs()
notice_data: Dict[str, Any] = st.session_state.notice_data
folio_data: Dict[str, Any] = {**st.session_state.folio_data,
                              "hotel_name": st.session_state.folio_data.get("hotel_name") or merchant_name}
reconciliation = Reconciler.reconcile(notice_data, folio_data, supporting_docs)


def current_fingerprint() -> str:
    return case_fingerprint(notice_data, folio_data, supporting_docs,
                            st.session_state.get("rebuttal_editor", ""), st.session_state.get("policy_text", ""))


# -----------------------------------------------------------------------------
# MAIN HEADER & METRICS
# -----------------------------------------------------------------------------
st.markdown("<h1 class='main-header'>🛡️ FolioShield: Autonomous Chargeback Defense</h1>", unsafe_allow_html=True)
st.markdown(
    "<p class='sub-header'>Outside-in document reconciliation, multimodal evidence auditing, "
    "and automated 3-page dispute packet generation powered by <b>Meta Llama 3.3 70B</b> &amp; <b>Llama Vision</b>.</p>",
    unsafe_allow_html=True,
)

network_code = f"{notice_data.get('card_network') or 'Unknown'} {notice_data.get('reason_code') or ''}".strip()
m1, m2, m3, m4, m5 = st.columns(5)
with m1:
    st.metric("Disputed Amount", f"${reconciliation['disputed_amount']:,.2f}", delta=network_code, delta_color="off")
with m2:
    st.metric("Total Folio Charges", f"${reconciliation['folio_charges']:,.2f}",
              delta=f"Settled: ${reconciliation['folio_payments']:,.2f}", delta_color="off")
with m3:
    diff = reconciliation["folio_charges"] - reconciliation["disputed_amount"]
    if reconciliation["is_exact_match"]:
        diff_label = "Exact Match"
    elif reconciliation["is_partial"]:
        diff_label = "Partial Dispute"
    elif reconciliation["disputed_amount"] <= 0:
        diff_label = "Amount Missing"
    else:
        diff_label = "Over-Disputed"
    st.metric("Variance / Status", f"${abs(diff):,.2f}", delta=diff_label,
              delta_color="normal" if reconciliation["is_exact_match"] else "off")
with m4:
    st.metric("Evidence Completeness", f"{reconciliation['completeness_score']}%",
              delta=reconciliation["completeness_assessment"].split("(")[0].strip(),
              delta_color="normal" if reconciliation["status_color"] == "green" else "inverse")
with m5:
    days = reconciliation["days_to_deadline"]
    st.metric("Response Deadline", notice_data.get("response_deadline") or "Unknown",
              delta=("Overdue" if days < 0 else f"{days} day(s) left") if days is not None else "Not found",
              delta_color="inverse" if days is not None and days <= 5 else "off")

st.markdown("<br/>", unsafe_allow_html=True)

tab_ingest, tab_audit, tab_rebuttal, tab_pdf, tab_logs = st.tabs([
    "📄 1. Upload Notice & Guest Folio",
    "🔍 2. Stay & Billing Verification",
    "✍️ 3. Dispute Response Letter",
    "📑 4. Generate Bank Evidence Packet",
    "🔒 5. Staff Activity & History",
])


# -----------------------------------------------------------------------------
# TAB 1: UPLOAD NOTICE & GUEST FOLIO
# -----------------------------------------------------------------------------
with tab_ingest:
    st.subheader("Front Desk & Back Office Document Intake")
    st.markdown(
        "Upload the bank's dispute notice and the guest's folio ledger (PDF or CSV export from Oracle OPERA, Cloudbeds, Mews, etc.). "
        "No direct PMS connection needed — FolioShield reads your existing hotel exports directly."
    )

    c_up1, c_up2 = st.columns(2)
    with c_up1:
        st.markdown("#### 1. Bank Dispute Notice (PDF)")
        notice_file = st.file_uploader("Upload Acquirer / Issuer Dispute Notice:", type=["pdf"], key="notice_uploader")
        if notice_file:
            notice_bytes = notice_file.getvalue()
            if new_upload("notice", notice_bytes):
                try:
                    validate_upload(notice_bytes, notice_file.name)
                    parsed_notice = DocumentExtractor.parse_dispute_notice(DocumentExtractor.extract_text_from_pdf(notice_bytes))
                except (ExtractionError, ValueError) as e:
                    st.session_state.processed_uploads.pop("notice", None)
                    st.error(f"❌ {e}")
                    log("notice_rejected", {"filename": notice_file.name, "error": str(e)})
                else:
                    st.session_state.notice_data = parsed_notice
                    reset_outputs()
                    log("notice_uploaded", {
                        "filename": notice_file.name,
                        "sha256": AuditLogger.calculate_sha256(notice_bytes),
                        "disputed_amount": parsed_notice["disputed_amount"],
                        "message": f"Notice {parsed_notice.get('case_id') or '(no case ID)'} ingested",
                    })
                    st.rerun()
            st.success(f"✓ Notice ingested: Case #{notice_data.get('case_id') or 'not detected'} "
                       f"(${float(notice_data.get('disputed_amount') or 0):,.2f})")

        with st.expander("View Ingested Notice Details", expanded=True):
            st.json({k: v for k, v in notice_data.items() if k != "raw_text"})
        if notice_data.get("raw_text"):
            with st.expander("View extracted notice text (card numbers masked)"):
                st.code(notice_data["raw_text"][:5000], language=None)

    with c_up2:
        st.markdown("#### 2. Hotel Guest Folio (PDF or CSV)")
        folio_file = st.file_uploader("Upload Itemized Guest Folio / PMS Ledger:", type=["pdf", "csv"], key="folio_uploader")
        if folio_file:
            folio_bytes = folio_file.getvalue()
            if new_upload("folio", folio_bytes):
                try:
                    validate_upload(folio_bytes, folio_file.name)
                    if folio_file.name.lower().endswith(".csv"):
                        parsed_folio = DocumentExtractor.parse_folio_csv(folio_bytes)
                    else:
                        parsed_folio = DocumentExtractor.parse_folio_pdf(DocumentExtractor.extract_text_from_pdf(folio_bytes))
                except (ExtractionError, ValueError) as e:
                    st.session_state.processed_uploads.pop("folio", None)
                    st.error(f"❌ {e}")
                    log("folio_rejected", {"filename": folio_file.name, "error": str(e)})
                else:
                    st.session_state.folio_data = parsed_folio
                    reset_outputs()
                    log("folio_uploaded", {
                        "filename": folio_file.name,
                        "sha256": AuditLogger.calculate_sha256(folio_bytes),
                        "total_charges": parsed_folio["total_charges"],
                        "message": f"Folio with {len(parsed_folio['line_items'])} line items ingested",
                    })
                    st.rerun()
            st.success(f"✓ Folio parsed: Room #{folio_data.get('room_number') or 'N/A'} "
                       f"(${float(folio_data.get('total_charges') or 0):,.2f})")

        with st.expander("View Ingested Folio Details", expanded=True):
            st.json({k: v for k, v in folio_data.items() if k not in ("line_items", "raw_text")})

    # --- Human review of extracted fields -------------------------------------------------
    with st.expander("✏️ Review & Correct Stay Details (Guest Name, Dates, Room #)", expanded=False):
        st.caption("Verify extracted stay information against your PMS. Any staff corrections are automatically recorded in the audit log.")
        with st.form("field_review"):
            fc1, fc2 = st.columns(2)
            with fc1:
                st.markdown("**Bank notice**")
                n_case = st.text_input("Case ID", value=notice_data.get("case_id") or "")
                current_net = notice_data.get("card_network")
                n_net = st.selectbox("Card network", CARD_NETWORKS,
                                     index=CARD_NETWORKS.index(current_net) if current_net in CARD_NETWORKS else 0)
                n_code = st.text_input("Reason code", value=notice_data.get("reason_code") or "")
                n_amt = st.number_input("Disputed amount (USD)", min_value=0.0, step=0.01, format="%.2f",
                                        value=float(notice_data.get("disputed_amount") or 0.0))
                n_name = st.text_input("Cardholder name", value=notice_data.get("cardholder_name") or "")
                n_last4 = st.text_input("Card last 4 (notice)", value=notice_data.get("card_last_4") or "", max_chars=4)
                n_txn = st.text_input("Transaction date", value=notice_data.get("transaction_date") or "")
                n_deadline = st.text_input("Response deadline", value=notice_data.get("response_deadline") or "")
            with fc2:
                st.markdown("**Guest folio**")
                raw_folio = st.session_state.folio_data
                f_hotel = st.text_input("Property name", value=raw_folio.get("hotel_name") or "")
                f_guest = st.text_input("Guest name", value=raw_folio.get("guest_name") or "")
                f_room = st.text_input("Room number", value=raw_folio.get("room_number") or "")
                f_in = st.text_input("Check-in", value=raw_folio.get("check_in") or "")
                f_out = st.text_input("Check-out", value=raw_folio.get("check_out") or "")
                f_last4 = st.text_input("Card last 4 (folio)", value=raw_folio.get("card_last_4") or "", max_chars=4)
                f_auth = st.text_input("Authorization code", value=raw_folio.get("auth_code") or "")
            if st.form_submit_button("Save corrections", type="primary"):
                bad_last4 = [v for v in (n_last4, f_last4) if v and not (v.isdigit() and len(v) == 4)]
                if bad_last4:
                    st.error("Card last 4 must be exactly four digits.")
                else:
                    notice_updates = {"case_id": n_case, "card_network": n_net, "reason_code": n_code,
                                      "disputed_amount": round(n_amt, 2), "cardholder_name": n_name, "card_last_4": n_last4,
                                      "transaction_date": n_txn, "response_deadline": n_deadline}
                    folio_updates = {"hotel_name": f_hotel, "guest_name": f_guest, "room_number": f_room, "check_in": f_in,
                                     "check_out": f_out, "card_last_4": f_last4, "auth_code": f_auth}
                    clean = lambda v: (v.strip() or None) if isinstance(v, str) else v  # noqa: E731
                    changed = [f"notice.{k}" for k, v in notice_updates.items() if clean(v) != notice_data.get(k)]
                    changed += [f"folio.{k}" for k, v in folio_updates.items() if clean(v) != raw_folio.get(k)]
                    if changed:
                        st.session_state.notice_data = {**notice_data, **{k: clean(v) for k, v in notice_updates.items()}}
                        st.session_state.folio_data = {**raw_folio, **{k: clean(v) for k, v in folio_updates.items()}}
                        reset_outputs()
                        log("fields_corrected", {"fields": changed, "message": f"{len(changed)} field(s) corrected"})
                        st.rerun()
                    else:
                        st.info("No changes to save.")

    st.markdown("---")
    st.markdown("#### 👁️ Scanned Reg Card & Signature Check (Vision AI)")
    st.caption("Upload a photo or scan of the signed registration card, front desk ID verification, or restaurant dining chit.")

    img_file = st.file_uploader("Upload Scanned Document / Receipt Image (Optional):",
                                type=["png", "jpg", "jpeg"], key="vision_uploader")
    if img_file:
        img_bytes = img_file.getvalue()
        img_hash = AuditLogger.calculate_sha256(img_bytes)
        if st.session_state.vision_image_hash != img_hash:
            st.session_state.vision_image_hash = img_hash
            st.session_state.vision_audit_result = None
        try:
            validate_upload(img_bytes, img_file.name)
        except ValueError as e:
            st.error(f"❌ {e}")
        else:
            col_img, col_vis_res = st.columns([1, 2])
            with col_img:
                st.image(img_bytes, caption="Uploaded Supporting Document", width="stretch")
            with col_vis_res:
                if st.button("Run Llama Vision Analysis", type="primary"):
                    with st.spinner("Analyzing visual evidence via Meta Llama Vision..."):
                        vis_res = llama_engine.analyze_visual_evidence(img_bytes, document_type="Registration Card")
                    st.session_state.vision_audit_result = vis_res
                    log("vision_analysis_completed", {**vis_res, "sha256": img_hash, "filename": img_file.name})

                vis = st.session_state.vision_audit_result
                if vis:
                    st.markdown("##### 🔍 Vision Audit Findings")
                    st.json(vis)
                    if not vis.get("analyzed"):
                        st.warning("⚠️ Image was not machine-analyzed. Verify the document manually before relying on it.")
                    elif vis.get("signature_detected") is True:
                        st.success("✓ Model reports a signature is visible. Confirm visually before marking evidence as available.")
                    else:
                        st.warning("⚠️ Model did not confirm a signature on this document.")


# -----------------------------------------------------------------------------
# TAB 2: STAY & BILLING VERIFICATION
# -----------------------------------------------------------------------------
with tab_audit:
    st.subheader("Stay & Billing Verification")
    st.markdown(
        "Cross-checks the bank's dispute notice against your hotel folio records to verify guest stay dates, card numbers, and billed charges."
    )

    rule_info = reconciliation.get("rule_details") or {}
    net_col1, net_col2 = st.columns([1, 2])
    with net_col1:
        st.markdown(f"### **{network_code}**")
        st.markdown(f"<span class='badge'>{rule_info.get('category', 'Dispute')}</span>", unsafe_allow_html=True)
        st.write(f"**Dispute Reason:** {rule_info.get('name', 'Reason code not in knowledge base')}")
        st.write(f"**Cardholder Claim:** {rule_info.get('description', 'Verify reason code requirements with your processor.')}")
    with net_col2:
        st.info(f"**🏨 Hotel Defense Playbook (How to Win):**\n{rule_info.get('win_strategy', 'Provide proof of authorization and service delivery.')}")
    st.caption("Reason-code guidance is a simplified hospitality reference — validate against current card-network rules.")

    st.markdown("---")
    st.markdown("#### 1. Stay & Billing Match Highlights")
    for highlight in reconciliation["audit_highlights"]:
        st.success(f"✓ **{highlight}**")
    for disc in reconciliation["discrepancies"]:
        render = {"critical": (st.error, "❌"), "warning": (st.warning, "⚠️")}.get(disc["severity"], (st.info, "ℹ️"))
        render[0](f"{render[1]} **{disc['type']}:** {disc['message']}")

    st.markdown("---")
    st.markdown("#### 2. Room Charges & Incidentals Breakdown")
    items = folio_data.get("line_items") or []
    if items:
        st.dataframe(pd.DataFrame(items), width="stretch", hide_index=True)
    else:
        st.write(f"No explicit line items extracted. Folio total charges: ${float(folio_data.get('total_charges') or 0):,.2f}")

    st.markdown("---")
    st.markdown("#### 3. Front Desk Proof Checklist (What's on File)")
    st.caption("Confirm only documents you actually have on file at the hotel. Claims in the response letter follow these selections.")
    doc_keys = list(SUPPORTING_DOC_TYPES)
    chk_c1, chk_c2 = st.columns(2)
    for i, key in enumerate(doc_keys):
        with (chk_c1 if i < (len(doc_keys) + 1) // 2 else chk_c2):
            st.checkbox(SUPPORTING_DOC_TYPES[key], key=f"doc_{key}")

    st.markdown("##### Evidence coverage status")
    st.dataframe(
        pd.DataFrame(reconciliation["evidence_checklist"])[["item", "status"]].rename(
            columns={"item": "Required evidence", "status": "Status"}),
        width="stretch", hide_index=True,
    )

    st.markdown("##### Cancellation & booking terms on file (optional)")
    st.text_area("Exact cancellation wording shown to the guest during reservation (printed on page 3 of the packet):",
                 key="policy_text", height=100)


# -----------------------------------------------------------------------------
# TAB 3: DISPUTE RESPONSE LETTER
# -----------------------------------------------------------------------------
with tab_rebuttal:
    st.subheader("Dispute Response Letter Studio")
    st.markdown(
        "Generate and review an evidence-backed dispute rebuttal letter for the bank. "
        "Generated drafts only assert proof confirmed in the checklist above, and **must be approved by a manager or designated staff** before compiling the final packet."
    )

    col_reb_ctrl, col_reb_gen = st.columns([3, 1])
    with col_reb_ctrl:
        st.text_area(
            "Front Desk Notes / Special Guest Context (Optional):",
            key="custom_notes",
            placeholder="e.g. Guest checked in with agent Sarah at 3:15pm, ordered room service on night 2, and concierge booked airport transfer.",
            help="Included in the drafting prompt as front desk notes (sanitized, max 2,000 characters).",
        )
    with col_reb_gen:
        st.markdown("<br/>", unsafe_allow_html=True)
        if st.button("✨ Draft Response Letter", type="primary", width="stretch"):
            with st.spinner("Drafting response letter..."):
                draft = llama_engine.draft_rebuttal(notice_data, folio_data, reconciliation,
                                                    custom_instructions=st.session_state.custom_notes)
            st.session_state.rebuttal_editor = draft
            st.session_state.draft_engine = llama_engine.last_engine_used
            st.session_state.approval = None
            log("rebuttal_drafted", {"word_count": len(draft.split()), "engine": llama_engine.last_engine_used,
                                     "sha256": sha256_text(draft), "message": f"Draft generated by {llama_engine.last_engine_used}"})

    if st.session_state.draft_engine:
        st.caption(f"Last draft generated by: `{st.session_state.draft_engine}`")

    st.markdown("#### ✍️ Review Letter & Manager Sign-Off")
    st.text_area("Review and refine the defense letter before signing off and compiling the packet:", key="rebuttal_editor", height=420,
                 placeholder="Click “Draft Response Letter” to generate a starting draft, or write your own.")
    draft_text: str = st.session_state.rebuttal_editor or ""
    unresolved = draft_text.count("[MISSING")

    approval: Optional[Dict[str, Any]] = st.session_state.approval
    approval_current = bool(approval and approval["fingerprint"] == current_fingerprint())

    col_app1, col_app2 = st.columns([1, 3])
    with col_app1:
        approve_disabled = not draft_text.strip() or not (st.session_state.get("reviewer_name") or "").strip()
        if st.button("✅ Manager Sign-Off & Approve", disabled=approve_disabled):
            st.session_state.approval = {
                "by": actor(),
                "at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                "fingerprint": current_fingerprint(),
                "sha256": sha256_text(draft_text),
            }
            log("rebuttal_approved", {"rebuttal_sha256": sha256_text(draft_text), "length": len(draft_text),
                                      "unresolved_missing_markers": unresolved, "message": "Rebuttal approved"})
            st.rerun()
    with col_app2:
        if approval_current:
            st.success(f"Approved by **{approval['by']}** at {approval['at']}. Ready for packet compilation.")
        elif approval:
            st.warning("The draft or stay data changed after approval. Review and approve again.")
        elif approve_disabled:
            st.info("Enter your staff reviewer name in the sidebar and provide a draft to enable manager sign-off.")
        if unresolved:
            st.warning(f"Draft contains {unresolved} `[MISSING ...]` marker(s). Resolve or remove them before submission.")


# -----------------------------------------------------------------------------
# TAB 4: GENERATE BANK EVIDENCE PACKET
# -----------------------------------------------------------------------------
with tab_pdf:
    st.subheader("Generate & Download 3-Page Bank Dispute Packet")
    st.markdown(
        "Generate a standardized, professional 3-page dispute packet formatted for submission to your acquiring bank or payment processor."
    )

    fingerprint = current_fingerprint()
    approval = st.session_state.approval
    is_approved = bool(approval and approval["fingerprint"] == fingerprint)
    pdf_current = st.session_state.generated_pdf is not None and st.session_state.pdf_fingerprint == fingerprint

    if not is_approved:
        st.info("🔒 Approve the defense letter in Tab 3 (Manager Sign-Off) to unlock packet compilation.")

    col_btn_gen, col_btn_dl = st.columns(2)
    with col_btn_gen:
        if st.button("🔨 Compile 3-Page Bank Evidence Packet", type="primary", width="stretch", disabled=not is_approved):
            with st.spinner("Generating 3-page PDF evidence packet..."):
                pdf_bytes = EvidencePacketGenerator.generate_packet(
                    notice_data, folio_data, reconciliation, draft_text,
                    audit_sha256=approval["sha256"],
                    approved_by=approval["by"],
                    approved_at=approval["at"],
                    policy_text=st.session_state.policy_text,
                )
            st.session_state.generated_pdf = pdf_bytes
            st.session_state.pdf_fingerprint = fingerprint
            pdf_current = True
            log("pdf_packet_generated", {"size_bytes": len(pdf_bytes), "pages": 3,
                                         "sha256": AuditLogger.calculate_sha256(pdf_bytes),
                                         "message": "Evidence packet compiled"})
            st.success("✓ 3-Page Bank Evidence Packet successfully generated.")

    with col_btn_dl:
        if pdf_current:
            safe_case = "".join(ch for ch in str(notice_data.get("case_id") or "Packet") if ch.isalnum() or ch in "-_")
            if st.download_button(
                label="📥 Download Bank Dispute Packet (PDF)",
                data=st.session_state.generated_pdf,
                file_name=f"FolioShield_Dispute_{safe_case}.pdf",
                mime="application/pdf",
                width="stretch",
                on_click="ignore",
            ):
                pass
        else:
            if st.session_state.generated_pdf is not None:
                st.warning("Stay data changed since the last compile — recompile to download.")
            st.button("📥 Download Ready After Compilation", disabled=True, width="stretch")

    st.markdown("---")
    st.markdown("#### 📑 What's Inside the 3-Page Packet")
    p1, p2, p3 = st.columns(3)
    with p1:
        st.markdown("""
        **📄 Page 1: Dispute Cover Letter**
        - Hotel branding & case reference
        - Bank reason code explanation
        - Manager-approved defense statement
        - Staff signature & sign-off block
        """)
    with p2:
        st.markdown("""
        **📊 Page 2: Itemized Folio & Stay Audit**
        - Check-in/out dates, room #, and auth code
        - Itemized room rates, taxes & incidentals
        - Computed ledger balance ($0.00 settled)
        - Stay verification check summary
        """)
    with p3:
        st.markdown("""
        **🏛️ Page 3: Evidence Annex & Certification**
        - Card network compelling evidence checklist
        - Physical hotel documents on file (Reg card, ID, Keys)
        - Booking cancellation terms disclosure
        - SHA-256 tamper-evident integrity certification
        """)


# -----------------------------------------------------------------------------
# TAB 5: STAFF ACTIVITY & HISTORY
# -----------------------------------------------------------------------------
with tab_logs:
    st.subheader("Staff Activity Log & Chain of Custody")
    st.markdown(
        "Complete chronological history of all staff actions, document uploads, reviewer corrections, "
        "manager approvals, and PDF generations with tamper-evident SHA-256 verification."
    )

    logger_obj: AuditLogger = st.session_state.audit_logger
    events = logger_obj.get_events()
    if events:
        if logger_obj.verify_chain():
            st.success(f"🔗 Chain verified — {len(events)} event(s), session `{logger_obj.session_id}`")
        else:
            st.error("⛔ Audit chain verification FAILED — log integrity compromised.")
        df_events = pd.DataFrame(events)
        df_events["details"] = df_events["details"].apply(lambda d: json.dumps(d, default=str))
        df_events["event_hash"] = df_events["event_hash"].str[:12]
        st.dataframe(df_events.drop(columns=["prev_hash", "session_id"]), width="stretch", hide_index=True)
        st.download_button(
            "⬇️ Download staff activity history (JSONL)",
            data="\n".join(json.dumps(e, default=str) for e in events),
            file_name=f"audit_trail_{logger_obj.session_id}.jsonl",
            mime="application/jsonl",
            on_click="ignore",
        )
    else:
        st.write("No events recorded in current session.")

    st.markdown("---")
    st.markdown("#### ⚖️ Responsible AI & Legal Disclaimer")
    st.caption("""
    FolioShield is an evidence preparation and decision-support tool. It does not guarantee chargeback reversals,
    legal compliance, or acceptance of generated documents by banks, payment processors, or card networks.
    All generated content should be reviewed by an authorized person before submission. Applicable deadlines,
    dispute reason codes, evidence requirements, and submission procedures must be verified with the relevant payment processor.
    """)
