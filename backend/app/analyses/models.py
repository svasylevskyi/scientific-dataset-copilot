from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SavedAnalysis(Base):
    __tablename__ = "analyses"
    __table_args__ = (CheckConstraint("version >= 1", name="analysis_version"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    workspace_id: Mapped[UUID] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(120))
    query: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class AnalysisRun(Base):
    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'cancelled')", name="run_status"
        ),
        CheckConstraint("attempt BETWEEN 0 AND 3", name="run_attempt"),
        CheckConstraint(
            "(status IN ('queued', 'running') AND finished_at IS NULL) OR "
            "(status NOT IN ('queued', 'running') AND finished_at IS NOT NULL)",
            name="run_finished",
        ),
        CheckConstraint(
            "status <> 'running' OR (lease_token IS NOT NULL AND lease_until IS NOT NULL "
            "AND attempt_deadline IS NOT NULL)",
            name="run_lease",
        ),
        Index("ix_runs_queue", "status", "available_at"),
        Index("ix_runs_owner_history", "workspace_id", "created_at"),
    )
    # The client-generated key makes an uncertain HTTP submission safe to repeat.
    id: Mapped[UUID] = mapped_column(primary_key=True)
    analysis_id: Mapped[UUID] = mapped_column(ForeignKey("analyses.id", ondelete="CASCADE"))
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    reservation_id: Mapped[UUID] = mapped_column(
        ForeignKey("usage_reservations.id", ondelete="RESTRICT"), unique=True
    )
    title: Mapped[str] = mapped_column(String(120))
    query: Mapped[dict] = mapped_column(JSONB)
    analysis_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(12), default="queued")
    stage: Mapped[str] = mapped_column(String(30), default="queued")
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lease_token: Mapped[UUID | None] = mapped_column()
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    attempt_deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancel_requested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    purged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    error: Mapped[str | None] = mapped_column(String(500))


class RunEvent(Base):
    __tablename__ = "run_events"
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    attempt: Mapped[int] = mapped_column(Integer)
    stage: Mapped[str] = mapped_column(String(30))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class RunArtifact(Base):
    __tablename__ = "run_artifacts"
    __table_args__ = (CheckConstraint("bytes >= 0 AND bytes <= 16000000", name="artifact_size"),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    run_id: Mapped[UUID] = mapped_column(
        ForeignKey("analysis_runs.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(80))
    relative_path: Mapped[str] = mapped_column(String(180), unique=True)
    media_type: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64))
    bytes: Mapped[int] = mapped_column(Integer)
