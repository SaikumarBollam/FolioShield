"""
FolioShield Connector Agent.

A lightweight, outbound-only Python agent that runs inside hotel
infrastructure, collects authorized dispute documents from local sources,
and synchronizes them with FolioShield through the authenticated
enterprise integration API.

The agent never submits disputes to banks/processors and never creates
human approval. It only prepares and synchronizes case material.
"""

from .config import AgentConfig
from .queue import AgentQueue

__all__ = ["AgentConfig", "AgentQueue"]
