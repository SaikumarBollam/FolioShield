# API Integration

## Legacy endpoints preserved

The original endpoints remain available for backward compatibility:

- `GET /health`
- `POST /api/v1/reconcile`
- `POST /api/v1/rebuttal/draft`
- `POST /api/v1/packet/generate`
- `POST /api/v1/submission/bundle`
- `POST /api/v1/submission/register`
- `POST /api/v1/submission/outcome`
- `POST /api/v1/dispute/process`

Production deployments should place these behind network controls and TLS. New enterprise integrations should use the authenticated tenant-scoped endpoints below.

## Enterprise endpoints

Authentication: `Authorization: Bearer <credential_id>.<secret>`

- `POST /api/v1/integrations/cases`
- `GET /api/v1/integrations/cases`
- `GET /api/v1/integrations/cases/{case_id}`
- `POST /api/v1/integrations/cases/{case_id}/documents`
- `POST /api/v1/integrations/cases/{case_id}/reconcile`
- `POST /api/v1/integrations/cases/{case_id}/draft`
- `POST /api/v1/integrations/cases/{case_id}/process`
- `POST /api/v1/integrations/cases/{case_id}/packet` (requires explicit human approval reference)
- `GET /api/v1/integrations/cases/{case_id}/audit`
- `GET /api/v1/integrations/monitoring`
- `GET /api/v1/integrations/agents`
- `POST /api/v1/integrations/agents/{agent_id}/heartbeat`
- `GET/POST /api/v1/integrations/webhooks`

## Security controls

- Tenant-scoped credentials with salted PBKDF2 hashes.
- Scopes per credential.
- CORS allowlist via `FOLIOSHIELD_API_CORS_ORIGINS`.
- JSON body limit via `FOLIOSHIELD_API_MAX_BODY_MB`.
- Request IDs and safe error responses.
- Signed webhooks with event IDs, idempotency keys, delivery tracking, and duplicate suppression.

## Python SDK

The local `FolioShield` SDK remains unchanged in behavior. `FolioShieldHTTPClient` adds authenticated remote API access with retries and idempotency headers.
