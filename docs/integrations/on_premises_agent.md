# On-Premises Connector Agent

## Purpose

The FolioShield Connector Agent runs inside hotel infrastructure and synchronizes authorized dispute documents to FolioShield over outbound HTTPS. It does not expose hotel databases publicly and does not open an inbound listener.

## Implemented

- Python agent for Windows/Linux-style local execution.
- Local JSON configuration.
- Credential via environment variable or local credential file.
- Durable SQLite job queue.
- Exponential backoff and dead-letter recovery.
- Filesystem connector for PDF/CSV/image folders.
- Generic REST connector for customer-controlled endpoints returning document JSON.
- Heartbeat that also acts as suspension/revocation check.
- Health output with queue counts and source status.
- Document hash deduplication and upload validation through existing FolioShield security utilities.

## Not production-verified

- SQL Server/PostgreSQL connectors are protocol-only and refuse to run until a customer-specific driver/schema/read-only credential adapter is validated.
- Windows Service / systemd installation wrappers are deployment tasks for the customer environment; the Python agent loop is provided.

## Example configuration

```json
{
  "tenant_id": "grand-horizon",
  "agent_id": "front-office-agent-1",
  "agent_name": "Front Office Connector",
  "server_url": "https://folioshield.example.com",
  "credential_env": "FOLIOSHIELD_AGENT_API_KEY",
  "queue_path": "agent_queue.sqlite3",
  "state_path": "agent_state.json",
  "sources": [
    {"source_id": "dispute-files", "kind": "filesystem", "path": "D:/FolioShield/Inbox", "enabled": true}
  ]
}
```

Run once:

```bash
python -m agent.agent --config agent.json --once
```

Health:

```bash
python -m agent.agent --config agent.json --health
```
