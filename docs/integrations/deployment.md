# Integration Deployment

## Environments

- **Development:** Streamlit app and built-in API server may run locally.
- **Controlled integration testing:** API behind localhost or private network controls; test tenants and synthetic documents only.
- **Production:** Requires TLS termination, network controls, secret management, monitored storage, backups, and customer security review.

## Docker (Phase 3)

```bash
cp .env.example .env   # fill in secrets (FOLIOSHIELD_API_KEY, provider keys)
docker compose up -d   # ui on :8501, api on :8000
```

- The image (`Dockerfile`, python:3.12-slim) runs as a non-root user; one
  image serves both processes (`python -m core.api` overrides the UI command).
- **Back up the `folioshield-data` volume** — it holds `cases.db` (case +
  evidence metadata), `exhibits/` (retained evidence bytes),
  `integrations/registry.db` plus `webhook_secret.key` (losing the key
  makes stored webhook secrets unrecoverable; subscriptions must rotate),
  and `submissions/` (submission/escalation/legal JSONL trails).
- Set `FOLIOSHIELD_API_KEY` in `.env`: in production the legacy endpoints
  fail closed (401) without it.
- CI (`.github/workflows/tests.yml`) runs the full unittest suite on
  Python 3.11 and 3.12 plus a bare-mode app smoke check.

## API server

The built-in server now uses `ThreadingHTTPServer` for better local concurrency, but it remains a development/controlled-testing server. For production, place it behind a reviewed reverse proxy or replace only the serving layer while keeping `core.integrations` and the existing FolioShield engine.

Recommended production controls:

- HTTPS only.
- Restrict legacy unauthenticated endpoints by network policy or disable public exposure.
- Set `FOLIOSHIELD_API_CORS_ORIGINS` to exact host origins.
- Set `FOLIOSHIELD_API_MAX_BODY_MB` to the smallest workable limit.
- Set `FOLIOSHIELD_INTEGRATION_ROOT` to backed-up, access-controlled storage.
- Set `AUDIT_HMAC_KEY` through a secret manager.
- Configure Llama provider keys through environment/secret management.

## Agent deployment

- Install Python and project dependencies in a dedicated service account.
- Store the agent secret in an environment variable or ACL-restricted credential file.
- Configure only authorized folders/endpoints as sources.
- Run `python -m agent.agent --config agent.json --health` before enabling scheduled operation.
- Use Windows Task Scheduler/Windows Service wrapper or systemd on Linux according to customer standards.

## Python version

The requested target is Python 3.12. Verify the full test suite in Python 3.12 before production deployment; local development may use a newer interpreter.
