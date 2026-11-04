"""
Repository interfaces and implementations for FolioShield persistence.
"""

from core.infrastructure.database.repositories.base import CaseRepository
from core.infrastructure.database.repositories.sql import SqlCaseRepository
from core.infrastructure.database.repositories.sqlite_legacy import SqliteLegacyCaseRepository

__all__ = [
    "CaseRepository",
    "SqlCaseRepository",
    "SqliteLegacyCaseRepository",
]
