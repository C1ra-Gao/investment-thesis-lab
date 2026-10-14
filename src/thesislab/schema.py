"""Portable SQLAlchemy models; Decimal values are strings, never SQLite floats."""

from sqlalchemy import ForeignKey, Integer, LargeBinary, String, Text, CheckConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class SchemaVersion(Base):
    __tablename__ = "schema_version"
    version: Mapped[int] = mapped_column(Integer, primary_key=True)
    __table_args__ = (CheckConstraint("version = 1"),)


class SourceRecord(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    payload: Mapped[str] = mapped_column(Text)


class ArtifactRecord(Base):
    __tablename__ = "artifacts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    sha256: Mapped[str] = mapped_column(String(64))
    media_type: Mapped[str] = mapped_column(String)
    acquired_at: Mapped[str] = mapped_column(String)
    local_reference: Mapped[str] = mapped_column(Text)
    body: Mapped[bytes] = mapped_column(LargeBinary)


class EvidenceRecord(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    artifact_id: Mapped[str | None] = mapped_column(ForeignKey("artifacts.id"), nullable=True)
    payload: Mapped[str] = mapped_column(Text)


class CalculationRecord(Base):
    __tablename__ = "calculations"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    result_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"), unique=True)
    payload: Mapped[str] = mapped_column(Text)


class CalculationInput(Base):
    __tablename__ = "calculation_inputs"
    calculation_id: Mapped[str] = mapped_column(ForeignKey("calculations.id"), primary_key=True)
    position: Mapped[int] = mapped_column(Integer, primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))


class ConflictRecord(Base):
    __tablename__ = "conflicts"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    left_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    right_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    payload: Mapped[str] = mapped_column(Text)


class CrosscheckRecord(Base):
    __tablename__ = "crosschecks"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    provider_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    issuer_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    payload: Mapped[str] = mapped_column(Text)


class ReviewRecord(Base):
    __tablename__ = "reviews"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conflict_id: Mapped[str] = mapped_column(ForeignKey("conflicts.id"))
    selected_evidence_id: Mapped[str | None] = mapped_column(ForeignKey("evidence.id"), nullable=True)
    payload: Mapped[str] = mapped_column(Text)


class RevisionRecord(Base):
    __tablename__ = "thesis_revisions"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    thesis_id: Mapped[str] = mapped_column(String, index=True)
    parent_id: Mapped[str | None] = mapped_column(ForeignKey("thesis_revisions.id"), nullable=True)
    payload: Mapped[str] = mapped_column(Text)


class CheckpointRecord(Base):
    __tablename__ = "checkpoints"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String, index=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("thesis_revisions.id"))
    payload: Mapped[str] = mapped_column(Text)


class AssessmentRecord(Base):
    __tablename__ = "assessments"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    revision_id: Mapped[str] = mapped_column(ForeignKey("thesis_revisions.id"))
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence.id"))
    payload: Mapped[str] = mapped_column(Text)


class AuditRecord(Base):
    __tablename__ = "audit_events"
    sequence: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    payload: Mapped[str] = mapped_column(Text)
