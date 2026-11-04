"""
Secure outbound communication client for the Connector Agent.

Outbound-only by default: the agent initiates HTTPS calls to FolioShield.
No inbound listener is opened by this client.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from core.client import FolioShieldHTTPClient


class AgentCommunicationClient:
    """Thin wrapper around the authenticated FolioShield HTTP client."""

    def __init__(self, server_url: str, api_key: str, timeout: int = 30):
        if not api_key:
            raise ValueError("Agent API key is not configured")
        self.client = FolioShieldHTTPClient(server_url, api_key, timeout=timeout)

    def heartbeat(self, agent_id: str, version: str = "", status: str = "online") -> Dict[str, Any]:
        return self.client._request("POST", f"/api/v1/integrations/agents/{agent_id}/heartbeat", {
            "version": version, "status": status,
        })

    def create_case(self, case_id: str, external_system: Optional[str] = None,
                    external_case_id: Optional[str] = None, external_folio_id: Optional[str] = None,
                    external_transaction_id: Optional[str] = None, property_id: Optional[str] = None) -> Dict[str, Any]:
        return self.client.create_case(
            case_id=case_id, external_system=external_system, external_case_id=external_case_id,
            external_folio_id=external_folio_id, external_transaction_id=external_transaction_id,
            property_id=property_id, idempotency_key=f"agent-case-{case_id}")

    def upload_document(self, case_id: str, document_type: str, filename: str, media_type: str,
                        data: bytes, evidence_doc_type: Optional[str] = None) -> Dict[str, Any]:
        return self.client.upload_document(case_id, document_type, filename, media_type, data,
                                           evidence_doc_type=evidence_doc_type)

    def process_case(self, case_id: str) -> Dict[str, Any]:
        return self.client.process_case(case_id)

    def get_case(self, case_id: str) -> Dict[str, Any]:
        return self.client.get_case(case_id)

    def monitoring(self) -> Dict[str, Any]:
        return self.client.monitoring()
