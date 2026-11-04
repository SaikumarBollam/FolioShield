"""
Phase 5 (Approval & Chain of Custody) Tests for FolioShield.

  * Tamper matrix: edit / delete / reorder detected; TRUNCATION and FULL
    REWRITE detected once the anchored chain head is supplied; HMAC mode
    makes rewrites fail even without a head.
  * Disk round-trip: persisted JSONL re-loads and verifies; corrupted line
    and truncated file are caught.
  * Canonical fingerprint: volatile churn (raw_text, verified_at, 100 vs
    100.0, None keys) does NOT bust it; real changes DO and name the
    component (folio/draft/evidence/policy/notes).
  * Approval linkage: manifest carries fingerprint + approval event hash;
    PDF custody block prints fingerprint, chain head, packet hash (3 pages).
  * SDK parity: process_dispute records a fingerprint approval event.
"""

import io
import json
import os
import tempfile
import unittest

import pypdf

from core.audit_logger import AuditLogger
from core.client import FolioShield
from core.fingerprint import case_fingerprint, changed_components
from core.llm_engine import LlamaEngine
from core.reconciler import Reconciler
from data.sample_scenarios import SCENARIOS
from datetime import date

TODAY = date(2026, 11, 3)


def fresh_logger(**kw):
    tmp = tempfile.mkdtemp()
    lg = AuditLogger(log_dir=tmp, **kw)
    lg.log_event("notice_uploaded", {"case_id": "V-1", "sha256": "abc", "filename": "n.pdf", "message": "n"})
    lg.log_event("rebuttal_approved", {"case_id": "V-1", "rebuttal_sha256": "def", "fingerprint": "f" * 64, "message": "a"})
    lg.log_event("pdf_packet_generated", {"case_id": "V-1", "sha256": "ghi", "message": "p"})
    return lg


class TestPhase5Custody(unittest.TestCase):

    # ------------------------------------------------------------ tamper matrix
    def test_01_edit_delete_reorder_detected(self):
        lg = fresh_logger()
        self.assertTrue(lg.verify_chain())
        lg.events[1]["details"]["rebuttal_sha256"] = "FORGED"
        self.assertFalse(lg.verify_chain())

        lg = fresh_logger()
        del lg.events[1]
        self.assertFalse(lg.verify_chain())

        lg = fresh_logger()
        lg.events[0], lg.events[1] = lg.events[1], lg.events[0]
        self.assertFalse(lg.verify_chain())

    def test_02_truncation_detected_with_anchored_head(self):
        lg = fresh_logger()
        head = lg.chain_head
        lg.events = lg.events[:2]  # truncate the packet event
        self.assertTrue(lg.verify_chain())  # unanchored: internally consistent
        self.assertFalse(lg.verify_chain(expected_head=head))  # anchored: caught

    def test_03_full_rewrite_detected_with_head_or_hmac(self):
        import hashlib
        lg = fresh_logger()
        head = lg.chain_head
        lg.events[1]["details"]["rebuttal_sha256"] = "FORGED"
        prev = "0" * 64
        for e in lg.events:  # attacker recomputes the whole chain
            e["prev_hash"] = prev
            payload = {k: v for k, v in e.items() if k != "event_hash"}
            e["event_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
            prev = e["event_hash"]
        self.assertFalse(lg.verify_chain(expected_head=head))

        # HMAC mode: rewrite without the key fails even unanchored
        lg2 = fresh_logger(hmac_key="server-secret")
        self.assertTrue(lg2.verify_chain())
        lg2.events[1]["details"]["rebuttal_sha256"] = "FORGED"
        prev = "0" * 64
        for e in lg2.events:
            e["prev_hash"] = prev
            payload = {k: v for k, v in e.items() if k != "event_hash"}
            e["event_hash"] = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
            prev = e["event_hash"]
        self.assertFalse(lg2.verify_chain())

    # ------------------------------------------------------------ disk verify
    def test_04_disk_roundtrip_and_corruption(self):
        lg = fresh_logger()
        path = os.path.join(lg.log_dir, f"audit_trail_{lg.session_id}.jsonl")
        ok, events, msg = AuditLogger.load_and_verify(path)
        self.assertTrue(ok, msg)
        self.assertEqual(len(events), 3)

        with open(path, "a", encoding="utf-8") as f:
            f.write('{"timestamp": "2026-11-03", "action": "forged"}\n')
        ok, _, _ = AuditLogger.load_and_verify(path)
        self.assertFalse(ok)

        lg2 = fresh_logger()
        path2 = os.path.join(lg2.log_dir, f"audit_trail_{lg2.session_id}.jsonl")
        head = lg2.chain_head
        with open(path2, encoding="utf-8") as _f2:
            lines = _f2.read().splitlines()
        with open(path2, "w", encoding="utf-8") as f:
            f.write("\n".join(lines[:2]) + "\n")  # truncated file
        ok, _, _ = AuditLogger.load_and_verify(path2, expected_head=head)
        self.assertFalse(ok)

    # ------------------------------------------------------------- fingerprint
    def test_05_fingerprint_canonical_stability(self):
        s = SCENARIOS["visa_fraud_10_4"]
        ev = {i["doc_type"]: i for i in Reconciler.reconcile(
            s["notice"], s["folio"], s["supporting_docs"], today=TODAY)["evidence_items"]}
        base = case_fingerprint(s["notice"], s["folio"], ev, "draft text", "policy", "notes", "Hotel")

        churn_notice = {**s["notice"], "raw_text": "completely   different\nraw text"}
        churn_folio = {**s["folio"], "total_charges": 1280.5, "raw_text": "other"}
        churn_ev = {k: {**v, "verified_at": "2099-01-01", "filename": "renamed.pdf"} for k, v in ev.items()}
        churned = case_fingerprint(churn_notice, churn_folio, churn_ev, "draft text", "policy", "notes", "Hotel")
        self.assertEqual(base["fingerprint"], churned["fingerprint"])

        int_folio = {**s["folio"], "total_charges": 1280.50}
        self.assertEqual(base["fingerprint"],
                         case_fingerprint(s["notice"], int_folio, ev, "draft text", "policy", "notes", "Hotel")["fingerprint"])

    def test_06_fingerprint_names_changed_component(self):
        s = SCENARIOS["visa_fraud_10_4"]
        recon = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
        ev = {i["doc_type"]: i for i in recon["evidence_items"]}
        base = case_fingerprint(s["notice"], s["folio"], ev, "draft", "policy", "", "Hotel")

        folio_changed = case_fingerprint(s["notice"], {**s["folio"], "room_number": "999"}, ev, "draft", "policy", "", "Hotel")
        self.assertEqual(changed_components(base, folio_changed), ["folio"])

        draft_changed = case_fingerprint(s["notice"], s["folio"], ev, "EDITED draft", "policy", "", "Hotel")
        self.assertEqual(changed_components(base, draft_changed), ["draft"])

        notes_changed = case_fingerprint(s["notice"], s["folio"], ev, "draft", "policy", "new notes", "Hotel")
        self.assertEqual(changed_components(base, notes_changed), ["notes"])

    # ------------------------------------------------------------ manifest/pdf
    def test_07_manifest_and_pdf_custody_block(self):
        s = SCENARIOS["visa_fraud_10_4"]
        lg = fresh_logger()
        manifest = lg.build_case_manifest("V-1")
        self.assertEqual(manifest["approval"]["fingerprint"], "f" * 64)
        self.assertEqual(manifest["chain_head"]["event_count"], 3)
        self.assertTrue(manifest["files"])

        recon = Reconciler.reconcile(s["notice"], s["folio"], s["supporting_docs"], today=TODAY)
        draft = LlamaEngine(provider="mock").draft_rebuttal(s["notice"], s["folio"], recon)
        fs = FolioShield()
        pdf_bytes = fs.generate_pdf_packet_hashed(
            s["notice"], s["folio"], recon, draft,
            approved_by="Test Manager (Manager)", approved_at="2026-11-03T12:00:00+00:00",
            policy_text="Non-refundable.", approval_fingerprint="f" * 64,
            chain_head=lg.chain_head)
        reader = pypdf.PdfReader(io.BytesIO(pdf_bytes))
        self.assertEqual(len(reader.pages), 3)
        text = "\n".join(p.extract_text() or "" for p in reader.pages)
        self.assertIn("Approval fingerprint", text)
        self.assertIn("Audit chain head", text)
        self.assertIn("Packet SHA-256", text)

    def test_08_sdk_approval_parity(self):
        """Phase 1 P0: headless processing must NOT record human approval.

        process_dispute() performs machine processing only: it logs
        api_rebuttal_processed, returns approval=None with
        human_approval_required=True, and the packet is a draft. Approval
        exists only after an explicit approve_dispute() call by a named
        human, bound to the case fingerprint.
        """
        fs = FolioShield()
        s = SCENARIOS["visa_fraud_10_4"]
        result = fs.process_dispute(
            notice=s["notice"], folio=s["folio"], supporting_docs=s["supporting_docs"],
            reviewer_name="SDK Test", generate_pdf=True)
        self.assertIsNotNone(result.pdf_base64)
        self.assertIsNone(result.approval)
        self.assertTrue(result.human_approval_required)
        self.assertEqual(len(result.approval_fingerprint), 64)
        actions = [e["action"] for e in fs.audit_logger.events]
        self.assertIn("api_rebuttal_processed", actions)
        self.assertNotIn("api_rebuttal_approved", actions)
        self.assertNotIn("rebuttal_approved", actions)

        # Explicit human approval: fingerprint-bound and verifiable.
        approval = fs.approve_dispute(
            s["notice"], s["folio"], s["supporting_docs"], result.rebuttal_text,
            approved_by="Test Manager")
        self.assertEqual(approval["fingerprint"], result.approval_fingerprint)
        self.assertEqual(approval["approved_by"], "Test Manager")
        self.assertTrue(fs.verify_approval(
            s["notice"], s["folio"], s["supporting_docs"], result.rebuttal_text, approval))
        # A changed draft invalidates the approval.
        self.assertFalse(fs.verify_approval(
            s["notice"], s["folio"], s["supporting_docs"], result.rebuttal_text + " edited", approval))
        actions = [e["action"] for e in fs.audit_logger.events]
        self.assertIn("rebuttal_approved", actions)
        self.assertTrue(fs.audit_logger.verify_chain())

    def test_09_approve_dispute_requires_human_and_draft(self):
        fs = FolioShield()
        s = SCENARIOS["visa_fraud_10_4"]
        with self.assertRaises(ValueError):
            fs.approve_dispute(s["notice"], s["folio"], s["supporting_docs"], "draft", approved_by="  ")
        with self.assertRaises(ValueError):
            fs.approve_dispute(s["notice"], s["folio"], s["supporting_docs"], "", approved_by="Manager")


if __name__ == "__main__":
    unittest.main()
