# Embedded Integration

## Model

Embedded FolioShield uses short-lived, HMAC-signed context tokens. The host application transports the token to the embedded FolioShield session, but FolioShield trusts tenant, property, user, roles, and case context only after server-side validation of:

- Signature.
- Issuer.
- Audience.
- Expiry.
- Origin allowlist, when configured.

Browser-supplied tenant IDs, roles, or permissions without a valid signed token are not trusted.

## Environment

```env
FOLIOSHIELD_EMBEDDED_ENABLED=true
FOLIOSHIELD_EMBEDDED_SECRET=server-side-secret
FOLIOSHIELD_EMBEDDED_ALLOWED_ORIGINS=https://host.example
FOLIOSHIELD_EMBEDDED_DEFAULT_VIEW=dashboard
```

Launch context uses `fs_embed=1` and `fs_embed_token=<signed-token>`. The token secret must never be placed in browser code.

## Views

Supported view identifiers: dashboard, dispute_status, document_upload, evidence_completeness, reconciliation_results, rebuttal_review, packet_download, integration_health.

## postMessage

Message types are documented in `embedded/configuration.py`. Messages must be origin-checked and must never contain API secrets, raw PANs, or unnecessary guest PII.

## OIDC/SSO status

OIDC/OAuth 2.0 production SSO is **requires identity-provider validation**. The signed-context mechanism is implemented; a real IdP integration must configure issuer, audience, JWKS/signature validation, callback flow, and session handling for the selected provider before production use.
