"""
FolioShield Connector Agent lifecycle.

Responsibilities:
- Load local configuration and credential.
- Send heartbeat / check revocation through authenticated API access.
- Discover documents from configured connectors.
- Validate file type/size using existing FolioShield security utilities.
- Queue jobs durably and synchronize with retry/backoff.
- Retrieve processing status.

Non-responsibilities:
- No bank/processor submission.
- No human approval creation.
- No local dispute-processing duplicate pipeline.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, Optional

from core.security import mask_card_number, validate_upload

from .communication import AgentCommunicationClient
from .config import AgentConfig
from .connectors import create_connector
from .queue import AgentQueue

logger = logging.getLogger(__name__)
AGENT_VERSION = "0.1.0"


class ConnectorAgent:
    """Outbound-only synchronization agent."""

    def __init__(self, config: AgentConfig, communication: Optional[AgentCommunicationClient] = None,
                 queue: Optional[AgentQueue] = None):
        self.config = config
        self.queue = queue or AgentQueue(config.queue_path)
        self.communication = communication
        self._state_path = Path(config.state_path)
        self._processed_hashes = self._load_state()

    # ------------------------------------------------------------------ state

    def _load_state(self) -> set[str]:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                return set(data.get("processed_hashes", []))
            except (OSError, json.JSONDecodeError):
                return set()
        return set()

    def _save_state(self) -> None:
        # Atomic write (tmp + replace): a crash mid-save must not corrupt
        # the processed-hash set.
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"processed_hashes": sorted(self._processed_hashes)}, indent=2), encoding="utf-8")
        tmp.replace(self._state_path)

    # -------------------------------------------------------------- lifecycle

    def client(self) -> AgentCommunicationClient:
        if self.communication is None:
            self.communication = AgentCommunicationClient(self.config.server_url, self.config.api_key)
        return self.communication

    def heartbeat(self) -> Dict[str, Any]:
        """Heartbeat also acts as suspension/revocation check: inactive agents fail closed."""
        return self.client().heartbeat(self.config.agent_id, version=self.config.version or AGENT_VERSION)

    def health(self) -> Dict[str, Any]:
        return {
            "agent_id": self.config.agent_id,
            "tenant_id": self.config.tenant_id,
            "version": self.config.version or AGENT_VERSION,
            "queue": self.queue.counts(),
            "sources": [{"source_id": s.source_id, "kind": s.kind, "enabled": s.enabled} for s in self.config.sources],
            "credential_configured": bool(self.config.api_key),
            "server_url": self.config.server_url,
        }

    # -------------------------------------------------------------- collection

    def collect_once(self) -> int:
        """Discover documents from enabled sources and enqueue new jobs.

        Per-item isolation: one invalid/unsupported file is logged and
        skipped — it never aborts discovery for the remaining files or
        sources. Hashes are NOT marked processed here; that happens only
        after the upload succeeds (see sync_once), so a lost queue cannot
        strand a document in a 'done' state.
        """
        enqueued = 0
        for source in self.config.sources:
            if not source.enabled:
                continue
            connector = create_connector(source)
            for item in connector.discover():
                data: bytes = item["data"]
                sha256 = item.get("sha256") or hashlib.sha256(data).hexdigest()
                if sha256 in self._processed_hashes:
                    continue
                try:
                    validate_upload(data, item["filename"],
                                    max_bytes=self.config.max_upload_mb * 1024 * 1024)
                except ValueError as exc:
                    logger.warning("Skipping %s from source %s: %s", item.get("filename"), source.source_id, exc)
                    continue
                document_type = item["document_type"]
                if document_type not in self.config.allowed_document_types:
                    continue
                payload = {
                    "case_id": item.get("case_id"),
                    "document_type": document_type,
                    "filename": item["filename"],
                    "media_type": item["media_type"],
                    "sha256": sha256,
                    "content_base64": __import__("base64").b64encode(data).decode("utf-8"),
                    "evidence_doc_type": item.get("evidence_doc_type"),
                    "source_id": source.source_id,
                }
                self.queue.enqueue("upload_document", payload, idempotency_key=f"doc-{sha256}", max_attempts=self.config.max_attempts)
                enqueued += 1
        return enqueued

    # ---------------------------------------------------------- synchronization

    def sync_once(self) -> Dict[str, int]:
        """Process due queue jobs once. Returns counts by outcome.

        Recovers jobs stuck in 'running' from a previous crash first, and
        records a document's hash as processed only after its upload has
        actually succeeded.
        """
        recovered = self.queue.recover_stale_running(self.config.running_lease_seconds)
        if recovered:
            logger.warning("Recovered %d stale 'running' job(s) after restart", recovered)
        outcomes = {"succeeded": 0, "failed": 0, "dead_letter": 0, "recovered": recovered}
        state_changed = False
        for job in self.queue.due_jobs():
            self.queue.mark_running(job["job_id"])
            payload = json.loads(job["payload"])
            try:
                result = self._execute_job(payload)
                self.queue.mark_succeeded(job["job_id"], result=result)
                outcomes["succeeded"] += 1
                sha256 = payload.get("sha256")
                if sha256 and sha256 not in self._processed_hashes:
                    self._processed_hashes.add(sha256)
                    state_changed = True
            except Exception as exc:
                updated = self.queue.mark_failed(
                    job["job_id"], str(exc), backoff_base=self.config.backoff_base_seconds,
                    backoff_max=self.config.backoff_max_seconds)
                if updated.get("status") == "dead_letter":
                    outcomes["dead_letter"] += 1
                else:
                    outcomes["failed"] += 1
        if state_changed:
            self._save_state()
        return outcomes

    def _execute_job(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        import base64

        client = self.client()
        case_id = str(payload.get("case_id") or "")
        if not case_id:
            raise ValueError("Job payload is missing case_id")
        # Ensure the tenant-scoped case exists before uploading documents.
        try:
            client.get_case(case_id)
        except Exception:
            client.create_case(case_id, external_system=payload.get("source_id"))
        data = base64.b64decode(str(payload.get("content_base64") or ""), validate=True)
        # Data minimization: never transmit a raw PAN in filenames/metadata.
        filename = mask_card_number(str(payload.get("filename") or "document.bin"))
        result = client.upload_document(
            case_id, str(payload.get("document_type") or "supporting_evidence"), filename,
            str(payload.get("media_type") or "application/octet-stream"), data,
            evidence_doc_type=payload.get("evidence_doc_type"))
        return {"document": result.get("data", {}).get("document")}

    def run_forever(self, stop_after_seconds: Optional[int] = None) -> None:
        """Background loop for service/daemon operation."""
        started = time.time()
        last_heartbeat = 0.0
        while True:
            now = time.time()
            if now - last_heartbeat >= self.config.heartbeat_seconds:
                try:
                    self.heartbeat()
                except Exception as exc:
                    logger.warning("Agent heartbeat failed: %s", exc)
                last_heartbeat = now
            try:
                self.collect_once()
                self.sync_once()
            except Exception as exc:
                logger.warning("Agent sync cycle failed: %s", exc)
            if stop_after_seconds and (time.time() - started) >= stop_after_seconds:
                return
            time.sleep(5)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser(description="FolioShield Connector Agent")
    parser.add_argument("--config", required=True, help="Path to agent JSON config")
    parser.add_argument("--once", action="store_true", help="Run one collect/sync cycle and exit")
    parser.add_argument("--health", action="store_true", help="Print local health and exit")
    args = parser.parse_args()

    config = AgentConfig.load(args.config)
    agent = ConnectorAgent(config)
    if args.health:
        print(json.dumps(agent.health(), indent=2))
        return
    if args.once:
        agent.collect_once()
        print(json.dumps(agent.sync_once(), indent=2))
        return
    agent.run_forever()


if __name__ == "__main__":
    main()
