# FolioShield Enterprise Integration Architecture

FolioShield remains a document-first chargeback defense application. The enterprise expansion adds three delivery methods around the same processing engine:

1. **Hybrid:** an outbound-only Connector Agent inside hotel infrastructure.
2. **API:** authenticated, tenant-scoped REST API and Python SDK clients.
3. **Embedded:** signed-context embedded views inside a host hotel application.

All three delegate dispute processing to the existing `FolioShield` SDK and core modules (`DocumentExtractor`, `Reconciler`, `LlamaEngine`, `EvidencePacketGenerator`, `AuditLogger`). No duplicate dispute pipeline exists.

## Trust boundaries

- Tenant identity is resolved server-side from credentials or signed context.
- Browser-supplied tenant IDs, roles, and permissions are never trusted alone.
- Agent communication is outbound-only by default.
- Human approval remains explicit. API/agent processing can draft and prepare, but cannot create human approval or submit to banks.
- SQL Server/PostgreSQL and OIDC providers are **requires vendor validation** until tested against real customer systems.

## Main components

- `core/integrations/`: contracts, credential registry, tenant registry, integration service, webhooks.
- `agent/`: local connector agent, durable SQLite queue, filesystem/REST connectors.
- `embedded/`: signed context tokens, view configuration, CSP/frame helpers.
- `app.py`: Streamlit workflow plus Integration Management tab.
