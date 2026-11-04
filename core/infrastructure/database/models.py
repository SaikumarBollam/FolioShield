"""
SQLAlchemy 2.0 Declarative Models for FolioShield.
"""

from typing import Optional
from sqlalchemy import Float, Integer, String, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Base declarative class for all FolioShield relational entities."""


class CaseModel(Base):
    __tablename__ = "cases"

    case_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(80), index=True, nullable=True)
    created_at: Mapped[str] = mapped_column(String(40))
    updated_at: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), default="open")
    notice_json: Mapped[str] = mapped_column(Text)
    folio_json: Mapped[str] = mapped_column(Text)
    evidence_items_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    draft_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    policy_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    custom_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    approval_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    audit_session_id: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    audit_head_hash: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)
    audit_event_count: Mapped[int] = mapped_column(Integer, default=0)


class SubmissionModel(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(80), index=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(80), index=True, nullable=True)
    portal_id: Mapped[str] = mapped_column(String(80))
    portal_name: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    submitted_by: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    submitted_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    confirmation_reference: Mapped[Optional[str]] = mapped_column(String(120), nullable=True)
    bundle_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    packet_sha256: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    approval_fingerprint: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(40), default="prepared")
    expected_decision_by: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class OutcomeModel(Base):
    __tablename__ = "outcomes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String(80), index=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(80), index=True, nullable=True)
    decision: Mapped[str] = mapped_column(String(40), default="pending")
    decided_at: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    amount_recovered: Mapped[float] = mapped_column(Float, default=0.0)
    next_stage: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    next_deadline: Mapped[Optional[str]] = mapped_column(String(40), nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class ExhibitModel(Base):
    __tablename__ = "exhibits"

    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(80), index=True, nullable=True)
    filename: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(80))
    size_bytes: Mapped[int] = mapped_column(Integer)
    storage_backend: Mapped[str] = mapped_column(String(40), default="local")
    created_at: Mapped[str] = mapped_column(String(40))
