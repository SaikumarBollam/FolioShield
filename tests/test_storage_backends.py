"""
Tests for StorageBackend abstractions (Local, Memory, S3) and ExhibitStore integration.
"""

import tempfile
import unittest
from unittest import mock

from core.infrastructure.storage.local import LocalStorageBackend
from core.infrastructure.storage.memory import MemoryStorageBackend
from core.infrastructure.storage.s3 import S3StorageBackend
from core.exhibit_store import ExhibitStore


class TestMemoryStorageBackend(unittest.TestCase):
    def setUp(self):
        self.storage = MemoryStorageBackend()

    def test_basic_crud_and_tenant_isolation(self):
        # Put under tenant-1
        self.storage.put("doc1.pdf", b"tenant-1-content", tenant_id="tenant-1")
        # Put under tenant-2
        self.storage.put("doc1.pdf", b"tenant-2-content", tenant_id="tenant-2")

        # Verify tenant isolation
        self.assertEqual(self.storage.get("doc1.pdf", tenant_id="tenant-1"), b"tenant-1-content")
        self.assertEqual(self.storage.get("doc1.pdf", tenant_id="tenant-2"), b"tenant-2-content")
        self.assertTrue(self.storage.has("doc1.pdf", tenant_id="tenant-1"))
        self.assertFalse(self.storage.has("doc2.pdf", tenant_id="tenant-1"))

        # List keys
        self.storage.put("doc2.pdf", b"data2", tenant_id="tenant-1")
        keys = self.storage.list_keys(tenant_id="tenant-1")
        self.assertEqual(keys, ["doc1.pdf", "doc2.pdf"])

        # Delete
        self.assertTrue(self.storage.delete("doc1.pdf", tenant_id="tenant-1"))
        self.assertFalse(self.storage.has("doc1.pdf", tenant_id="tenant-1"))
        # Verify tenant-2 unaffected
        self.assertEqual(self.storage.get("doc1.pdf", tenant_id="tenant-2"), b"tenant-2-content")


class TestLocalStorageBackend(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = self._tmp.name
        self.storage = LocalStorageBackend(root=self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_local_storage_atomic_and_tenant_isolation(self):
        self.storage.put("file1.pdf", b"bytes-t1", tenant_id="hotel-a")
        self.storage.put("file1.pdf", b"bytes-t2", tenant_id="hotel-b")

        # Check tenant isolation
        self.assertEqual(self.storage.get("file1.pdf", tenant_id="hotel-a"), b"bytes-t1")
        self.assertEqual(self.storage.get("file1.pdf", tenant_id="hotel-b"), b"bytes-t2")
        self.assertTrue(self.storage.has("file1.pdf", tenant_id="hotel-a"))

        # Verify fallback for unscoped
        self.storage.put("global.pdf", b"global-bytes")
        self.assertEqual(self.storage.get("global.pdf", tenant_id="hotel-a"), b"global-bytes")

        # Delete
        self.assertTrue(self.storage.delete("file1.pdf", tenant_id="hotel-a"))
        self.assertFalse(self.storage.has("file1.pdf", tenant_id="hotel-a"))
        self.assertTrue(self.storage.has("file1.pdf", tenant_id="hotel-b"))


class TestS3StorageBackend(unittest.TestCase):
    def test_missing_boto3_raises_runtime_error(self):
        with mock.patch("core.infrastructure.storage.s3._BOTO_AVAILABLE", False):
            with self.assertRaises(RuntimeError) as ctx:
                S3StorageBackend(bucket_name="test-bucket")
            self.assertIn("boto3 package is required", str(ctx.exception))

    @mock.patch("core.infrastructure.storage.s3._BOTO_AVAILABLE", True)
    @mock.patch("core.infrastructure.storage.s3.boto3")
    def test_s3_storage_crud(self, mock_boto3):
        mock_client = mock.MagicMock()
        mock_boto3.client.return_value = mock_client

        # Mock get_object body
        body_mock = mock.MagicMock()
        body_mock.read.return_value = b"s3-test-data"
        mock_client.get_object.return_value = {"Body": body_mock}

        storage = S3StorageBackend(bucket_name="folio-bucket", prefix="exhibits")

        # Put
        storage.put("doc.pdf", b"payload", tenant_id="tenant-x")
        mock_client.put_object.assert_called_once_with(
            Bucket="folio-bucket",
            Key="exhibits/tenant-x/doc.pdf",
            Body=b"payload",
        )

        # Get
        retrieved = storage.get("doc.pdf", tenant_id="tenant-x")
        self.assertEqual(retrieved, b"s3-test-data")
        mock_client.get_object.assert_called_with(
            Bucket="folio-bucket",
            Key="exhibits/tenant-x/doc.pdf",
        )

        # Has
        self.assertTrue(storage.has("doc.pdf", tenant_id="tenant-x"))
        mock_client.head_object.assert_called_with(
            Bucket="folio-bucket",
            Key="exhibits/tenant-x/doc.pdf",
        )

        # Delete
        self.assertTrue(storage.delete("doc.pdf", tenant_id="tenant-x"))
        mock_client.delete_object.assert_called_with(
            Bucket="folio-bucket",
            Key="exhibits/tenant-x/doc.pdf",
        )


class TestExhibitStoreWithBackend(unittest.TestCase):
    def test_exhibit_store_initializes_with_backend(self):
        backend = MemoryStorageBackend()
        store = ExhibitStore(backend=backend)
        self.assertIs(store.backend, backend)

        # Put item
        meta = store.put(b"exhibit-data", "registration.pdf", tenant_id="t1")
        self.assertEqual(meta["size_bytes"], len(b"exhibit-data"))
        self.assertEqual(store.get(meta["stored_ref"], "registration.pdf", tenant_id="t1"), b"exhibit-data")


if __name__ == "__main__":
    unittest.main()
