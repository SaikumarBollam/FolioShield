"""
On-premises Connector Agent tests (Phase 3).

No network and no vendor systems are used. Communication is faked; SQL
connector behavior is asserted to be explicitly not production-ready.
"""

import tempfile
import unittest
from pathlib import Path

from agent.agent import ConnectorAgent
from agent.config import AgentConfig, SourceConfig
from agent.connectors import SqlConnector, create_connector
from agent.queue import AgentQueue


class FakeCommunication:
    def __init__(self):
        self.uploads = []
        self.cases = set()
        self.heartbeats = 0

    def heartbeat(self, agent_id, version="", status="online"):
        self.heartbeats += 1
        return {"agent_id": agent_id, "status": "active"}

    def get_case(self, case_id):
        if case_id not in self.cases:
            raise KeyError("missing")
        return {"data": {"case_id": case_id}}

    def create_case(self, case_id, **kwargs):
        self.cases.add(case_id)
        return {"data": {"case_id": case_id}}

    def upload_document(self, case_id, document_type, filename, media_type, data, evidence_doc_type=None):
        self.uploads.append({"case_id": case_id, "document_type": document_type, "filename": filename, "data": data})
        return {"data": {"document": {"sha256": "x" * 64}}}


class FailingCommunication(FakeCommunication):
    def upload_document(self, *args, **kwargs):
        raise RuntimeError("network down")


class TestConnectorAgent(unittest.TestCase):

    def test_queue_durability_backoff_and_dead_letter(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "queue.sqlite3"
            queue = AgentQueue(path)
            job = queue.enqueue("upload_document", {"case_id": "C-1"}, idempotency_key="k-1", max_attempts=2)
            self.assertEqual(queue.enqueue("upload_document", {"case_id": "C-1"}, idempotency_key="k-1")["job_id"], job["job_id"])
            queue.close()

            reopened = AgentQueue(path)
            self.assertEqual(reopened.counts().get("queued"), 1)
            failed = reopened.mark_failed(job["job_id"], "down", backoff_base=1)
            self.assertEqual(failed["status"], "retrying")
            failed = reopened.mark_failed(job["job_id"], "down", backoff_base=1)
            self.assertEqual(failed["status"], "dead_letter")
            retried = reopened.retry_dead_letter(job["job_id"])
            self.assertEqual(retried["status"], "queued")
            reopened.close()

    def test_filesystem_connector_and_agent_sync(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "CASE-100"
            source.mkdir()
            (source / "dispute_notice.pdf").write_bytes(b"%PDF-1.4 notice")
            (source / "guest_folio.csv").write_text("Date,Description,Charge,Credit,Reference\n10/10/2026,Room,100,0,RM1\n", encoding="utf-8")
            config = AgentConfig(
                tenant_id="hotel-a", agent_id="agent-1", server_url="https://example.test",
                queue_path=str(Path(tmp) / "q.sqlite3"), state_path=str(Path(tmp) / "state.json"),
                sources=[SourceConfig(source_id="files", kind="filesystem", path=str(tmp))],
            )
            fake = FakeCommunication()
            agent = ConnectorAgent(config, communication=fake)  # type: ignore[arg-type]
            self.assertEqual(agent.collect_once(), 2)
            # Phase 2: hashes are marked processed only after a successful
            # upload. A second collect re-discovers the files, but queue
            # idempotency (doc-<sha256>) prevents duplicate jobs.
            agent.collect_once()
            self.assertEqual(agent.queue.counts().get("queued"), 2)
            outcomes = agent.sync_once()
            self.assertEqual(outcomes["succeeded"], 2)
            self.assertEqual({u["document_type"] for u in fake.uploads}, {"dispute_notice", "guest_folio"})
            self.assertEqual(agent.health()["queue"].get("succeeded"), 2)
            # After success the hashes are processed: nothing re-enqueues.
            self.assertEqual(agent.collect_once(), 0)
            agent.queue.close()

    def test_sync_failure_uses_retry_not_data_loss(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "CASE-200"
            source.mkdir()
            (source / "guest_folio.pdf").write_bytes(b"%PDF-1.4 folio")
            config = AgentConfig(
                tenant_id="hotel-a", agent_id="agent-1", server_url="https://example.test",
                queue_path=str(Path(tmp) / "q.sqlite3"), state_path=str(Path(tmp) / "state.json"),
                max_attempts=3, backoff_base_seconds=1,
                sources=[SourceConfig(source_id="files", kind="filesystem", path=str(tmp))],
            )
            agent = ConnectorAgent(config, communication=FailingCommunication())  # type: ignore[arg-type]
            agent.collect_once()
            outcomes = agent.sync_once()
            self.assertEqual(outcomes["failed"], 1)
            self.assertEqual(agent.queue.counts().get("retrying"), 1)
            agent.queue.close()

    def test_sql_connector_requires_vendor_validation(self):
        connector = create_connector(SourceConfig(source_id="db", kind="sql", path="customer-db"))
        self.assertIsInstance(connector, SqlConnector)
        with self.assertRaises(NotImplementedError):
            list(connector.discover())


if __name__ == "__main__":
    unittest.main()
