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
- `POST /api/v1/dispute/approve` *(added in Phase 1 P0 — explicit human approval)*

Production deployments should place these behind network controls and TLS. New enterprise integrations should use the authenticated tenant-scoped endpoints below.

### Phase 1 (P0) endpoint protection

- When `FOLIOSHIELD_API_KEY` is set, every non-health endpoint requires
  `Authorization: Bearer <FOLIOSHIELD_API_KEY>` (constant-time comparison).
  Enterprise integration credentials continue to work on their own endpoints.
- When no key is set, legacy endpoints are open only when
  `FOLIOSHIELD_API_ALLOW_LEGACY_UNAUTHENTICATED=true`. The default is
  **allowed outside production, denied in production** (fail closed).
- `GET /health` stays public but returns a minimal payload; operational
  details (`environment`, `provider`, `api_configured`) are included only
  for requests presenting the valid API key.
- Per-client rate limiting: `FOLIOSHIELD_API_RATE_LIMIT_PER_MIN`
  (default 120; `429` with `Retry-After` when exceeded).
- Bind address: `FOLIOSHIELD_API_HOST` (default `0.0.0.0`).

### Approval integrity (breaking change)

Machine processing is never human approval:

- `POST /api/v1/dispute/process` and SDK `FolioShield.process_dispute()`
  now return `approval: null`, `human_approval_required: true`, and an
  `approval_fingerprint` for the processed draft. The generated packet is
  a **draft** ("Pending approval"). The old `api_rebuttal_approved` audit
  event is no longer emitted; `api_rebuttal_processed` is logged instead.
- To approve, a human-operated caller invokes
  `POST /api/v1/dispute/approve` (or SDK `FolioShield.approve_dispute()`)
  with the approver's name and the exact rebuttal text. The approval is
  bound to the canonical case fingerprint and recorded as
  `rebuttal_approved` in the audit chain.
- `POST /api/v1/packet/generate` accepts an optional `approval` object
  (`{approved_by, approved_at, fingerprint}`). The fingerprint is
  re-verified server-side: a mismatch returns `409 approval_stale`.
  Without an approval object the packet is generated as a draft and the
  response carries `approval_status: "draft_pending_human_approval"`.
  A caller-supplied `approved_by` string alone is **ignored** — it is no
  longer stamped into packets.

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

- Shared API key for legacy endpoints (`FOLIOSHIELD_API_KEY`), fail-closed in production.
- Per-client rate limiting (`FOLIOSHIELD_API_RATE_LIMIT_PER_MIN`).
- Tenant-scoped credentials with salted PBKDF2 hashes.
- Scopes per credential.
- CORS allowlist via `FOLIOSHIELD_API_CORS_ORIGINS`.
- JSON body limit via `FOLIOSHIELD_API_MAX_BODY_MB`.
- Request IDs and safe error responses.
- Signed webhooks with event IDs, idempotency keys, delivery tracking, and duplicate suppression.

## Python SDK

`FolioShield.process_dispute()` performs machine processing only (see
Approval integrity above). `FolioShield.approve_dispute(...)` records an
explicit, fingerprint-bound human approval, and
`FolioShield.verify_approval(...)` checks an approval against the current
case and draft. `FolioShieldHTTPClient` adds authenticated remote API
access with retries and idempotency headers.
