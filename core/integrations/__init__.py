"""
FolioShield Enterprise Integration Foundation.

This package adds tenant-aware integration services around the existing
FolioShield processing engine. It does not reimplement dispute processing:
API, agent, and embedded integrations all delegate to core.client.FolioShield
and the existing extraction/reconciliation/Llama/PDF modules.
"""

from .contracts import (
    ApprovalReference,
    DocumentSubmission,
    IntegrationCaseRef,
    IntegrationEvent,
    ProcessingJob,
    TenantContext,
)
from .registry import IntegrationRegistry
from .webhooks import WebhookManager

__all__ = [
    "ApprovalReference",
    "DocumentSubmission",
    "IntegrationCaseRef",
    "IntegrationEvent",
    "ProcessingJob",
    "TenantContext",
    "IntegrationRegistry",
    "WebhookManager",
]
