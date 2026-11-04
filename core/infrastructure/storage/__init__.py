"""
Storage abstractions and backends for evidence and document persistence.
"""

from core.infrastructure.storage.base import StorageBackend, StorageError
from core.infrastructure.storage.local import LocalStorageBackend
from core.infrastructure.storage.memory import MemoryStorageBackend
from core.infrastructure.storage.s3 import S3StorageBackend

__all__ = [
    "StorageBackend",
    "StorageError",
    "LocalStorageBackend",
    "MemoryStorageBackend",
    "S3StorageBackend",
]
