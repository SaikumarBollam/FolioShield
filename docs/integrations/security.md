# Integration Security

## Controls implemented

- Tenant isolation in integration registry keys and API case access.
- Salted PBKDF2-HMAC-SHA256 credential hashes; raw secrets shown once.
- Credential suspension and revocation.
- Agent suspension/revocation through registry status and heartbeat failure.
- Bearer authentication for enterprise integration endpoints.
- Scope checks per endpoint/service operation.
- CORS allowlist; wildcard CORS removed from the API handler.
- JSON body size limit and safe error responses.
- Request IDs for correlation without logging payloads.
- PAN masking and prompt-injection sanitization through existing FolioShield security utilities.
- Upload validation using existing file signature/size checks.
- Signed webhooks with timestamp tolerance, event IDs, and idempotency keys.
- Hash-chained audit logging with optional HMAC via `AUDIT_HMAC_KEY`.

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
