"""
Acquirer / Processor Portal Profiles for FolioShield (Phase 6).

FolioShield prepares submission bundles; delivery itself is usually a manual
portal upload performed by hotel staff. Profiles encode, per acquirer:
  * delivery method (portal upload / API / email-fax) — honestly labelled
  * file constraints (accepted types, max bundle size, max pages)
  * decision window (days the issuer typically takes)
  * staff instructions for completing the submission

Constraints are conservative defaults — processors change portal rules, so
every profile is labelled "verify current rules in the portal".
"""

from typing import Any, Dict, List, Optional

PORTAL_PROFILES: Dict[str, Dict[str, Any]] = {
    "chase": {
        "id": "chase",
        "name": "Chase Merchant Services (Paymentech / Chase Orbital)",
        "delivery": "portal_upload",
        "portal_hint": "Chase Merchant Center / Access portal — Disputes section",
        "accepted_types": ["pdf", "jpg", "jpeg", "png", "tiff"],
        "max_bundle_mb": 10,
        "max_pages": 50,
        "decision_window_days": (30, 45),
        "requires": ["case_id", "arn"],
        "instructions": (
            "1. Sign in to the Chase Merchant Center and open Disputes.\n"
            "2. Locate the case by Case ID / ARN and choose 'Respond'.\n"
            "3. Upload 00_packet.pdf first, then each Exhibit file in letter order.\n"
            "4. Paste the Executive Summary from the packet into the response comments if a text box is provided.\n"
            "5. Submit, then copy the confirmation/reference shown and record it in FolioShield (Mark as Submitted)."
        ),
    },
    "fiserv": {
        "id": "fiserv",
        "name": "Fiserv (ClientLine / Business Track)",
        "delivery": "portal_upload",
        "portal_hint": "ClientLine / Business Track — Chargeback Management",
        "accepted_types": ["pdf", "jpg", "jpeg", "png"],
        "max_bundle_mb": 8,
        "max_pages": 40,
        "decision_window_days": (30, 45),
        "requires": ["case_id", "arn"],
        "instructions": (
            "1. Sign in to ClientLine / Business Track and open the chargeback case.\n"
            "2. Choose 'Submit Documentation' and upload 00_packet.pdf, then the Exhibit files in letter order.\n"
            "3. Confirm the total page count is within the portal limit shown on screen.\n"
            "4. Submit and record the confirmation/reference in FolioShield."
        ),
    },
    "stripe": {
        "id": "stripe",
        "name": "Stripe (Dashboard / Disputes API)",
        "delivery": "portal_upload",
        "portal_hint": "Stripe Dashboard — Payments → Disputes (API evidence upload also exists; FolioShield prepares files for manual/API-assisted upload)",
        "accepted_types": ["pdf", "jpg", "jpeg", "png"],
        "max_bundle_mb": 5,
        "max_pages": 25,
        "decision_window_days": (30, 45),
        "requires": ["case_id"],
        "instructions": (
            "1. Open the dispute in the Stripe Dashboard.\n"
            "2. Use 'Submit evidence': upload 00_packet.pdf as the primary evidence file and attach exhibits where the form allows.\n"
            "3. Map key facts into the evidence text fields (uncategorized text) if prompted.\n"
            "4. Submit and record the dispute status/confirmation in FolioShield."
        ),
    },
    "elavon": {
        "id": "elavon",
        "name": "Elavon (MerchantConnect)",
        "delivery": "portal_upload",
        "portal_hint": "MerchantConnect — Chargeback Management",
        "accepted_types": ["pdf", "jpg", "jpeg", "png"],
        "max_bundle_mb": 10,
        "max_pages": 50,
        "decision_window_days": (30, 45),
        "requires": ["case_id", "arn"],
        "instructions": (
            "1. Sign in to MerchantConnect and open the chargeback case.\n"
            "2. Upload 00_packet.pdf followed by the Exhibit files in letter order.\n"
            "3. Submit and record the confirmation/reference in FolioShield."
        ),
    },
    "worldpay": {
        "id": "worldpay",
        "name": "Worldpay (Access Worldpay / iQ)",
        "delivery": "portal_upload",
        "portal_hint": "Worldpay iQ / Access — Dispute Management",
        "accepted_types": ["pdf", "jpg", "jpeg", "png"],
        "max_bundle_mb": 10,
        "max_pages": 50,
        "decision_window_days": (30, 45),
        "requires": ["case_id", "arn"],
        "instructions": (
            "1. Sign in to Worldpay iQ / Access and open the dispute.\n"
            "2. Upload 00_packet.pdf followed by the Exhibit files in letter order.\n"
            "3. Submit and record the confirmation/reference in FolioShield."
        ),
    },
    "generic": {
        "id": "generic",
        "name": "Generic Acquirer Portal",
        "delivery": "portal_upload",
        "portal_hint": "Your acquirer's dispute portal",
        "accepted_types": ["pdf", "jpg", "jpeg", "png"],
        "max_bundle_mb": 10,
        "max_pages": 50,
        "decision_window_days": (30, 45),
        "requires": ["case_id"],
        "instructions": (
            "1. Sign in to your acquirer's dispute portal and open the case by Case ID / ARN.\n"
            "2. Upload 00_packet.pdf first, then each Exhibit file in letter order.\n"
            "3. Verify the portal's file-type/size limits on screen before submitting.\n"
            "4. Submit and record the confirmation/reference in FolioShield."
        ),
    },
}


def get_portal_profile(portal_id: Optional[str]) -> Dict[str, Any]:
    return PORTAL_PROFILES.get((portal_id or "generic").strip().lower(), PORTAL_PROFILES["generic"])


def list_portals() -> List[Dict[str, Any]]:
    return list(PORTAL_PROFILES.values())
