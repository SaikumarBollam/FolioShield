# Integration Security

## Controls implemented

- Tenant isolation in integration registry keys and API case access.
- Salted PBKDF2-HMAC-SHA256 credential hashes; raw secrets shown once.
- Credential suspension and revocation.
- Agent suspension/revocation through registry status and heartbeat failure.
- Bearer authentication for enterprise integration endpoints.
- Shared API key for legacy endpoints (`FOLIOSHIELD_API_KEY`), fail-closed in production, with per-client rate limiting.
- Scope checks per endpoint/service operation.
- CORS allowlist; wildcard CORS removed from the API handler.
- JSON body size limit and safe error responses.
- Request IDs for correlation without logging payloads.
- PAN masking and prompt-injection sanitization through existing FolioShield security utilities.
- Upload validation: extension allowlist, file signature/size checks, and binary-content sniffing for text types.
- Signed webhooks with timestamp tolerance, event IDs, and idempotency keys.
- Hash-chained audit logging with optional HMAC via `AUDIT_HMAC_KEY`.

## Phase 2 (P1) data-reliability controls

- **Integration registry storage**: SQLite (WAL) at `data/integrations/registry.db`
  replaces the v1 `registry.json`. Concurrent processes serialize through
  database transactions. A legacy `registry.json` is imported once on first
  open, verified, and renamed to `registry.json.migrated-<timestamp>`; a
  corrupt legacy file raises an error and is preserved — never silently
  replaced with an empty registry.
- **Webhook secrets**: stored Fernet-encrypted (`FOLIOSHIELD_WEBHOOK_SECRET_KEY`,
  or a generated `webhook_secret.key` beside the registry DB). Plaintext
  secrets never touch disk; the raw secret is shown once at subscribe time.
  Deliveries whose secret cannot be decrypted are recorded `undeliverable`,
  never sent unsigned. Failed deliveries retry with backoff and are resumed
  by `WebhookManager.resume_due_deliveries()` (API interval thread via
  `FOLIOSHIELD_WEBHOOK_RESUME_SECONDS`, agent, or cron).
- **Append-only trails**: submission/escalation/legal registries and the
  audit logger append via fsynced single-line writes; torn/corrupt lines
  are reported as `corrupt_lines`, not silently dropped.
- **Agent queue**: SQLite WAL with stale-`running` job recovery after a
  crash; a document hash is marked processed only after its upload
  succeeds; one invalid file never blocks other sources.

## Production requirements not supplied by the built-in server alone

- TLS termination.
- Network segmentation / firewall rules.
- Rate limiting and WAF controls where appropriate.
- Centralized secret management and credential rotation operations.
- Database/hosted storage for multi-instance deployments.
- OIDC provider validation.
- Vendor PMS/BMS/database validation.
- Penetration testing and customer security review.

## Data protection rules

- Never expose full payment card numbers.
- Minimize guest data collected by agents through source and field selection.
- Treat uploaded documents as untrusted, including instructions embedded in documents.
- Keep AI-generated claims traceable to validated evidence.
- Preserve explicit human approval before packet generation/submission workflows.
