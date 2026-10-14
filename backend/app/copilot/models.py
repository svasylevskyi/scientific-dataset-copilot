from datetime import date, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import CheckConstraint, Date, DateTime, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PlanningRequest(Base):
    __tablename__ = "planning_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'ready', 'clarification', 'unsupported', 'failed')",
            name="planning_status",
        ),
        CheckConstraint("turn BETWEEN 1 AND 3", name="planning_turn"),
        CheckConstraint("reserved_usd >= 0 AND estimated_cost_usd >= 0", name="planning_cost"),
        Index("ix_planning_day_owner", "budget_day", "workspace_id"),
    )
    id: Mapped[UUID] = mapped_column(primary_key=True)
    workspace_id: Mapped[UUID] = mapped_column(ForeignKey("workspaces.id", ondelete="CASCADE"))
    request_hash: Mapped[str] = mapped_column(String(64))
    # Bounded transcript is private to its owner. No account data is sent to the model.
    transcript: Mapped[list] = mapped_column(JSONB)
    turn: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="pending")
    message: Mapped[str] = mapped_column(String(500))
    proposal: Mapped[dict | None] = mapped_column(JSONB)
    analysis_id: Mapped[UUID | None] = mapped_column(ForeignKey("analyses.id", ondelete="SET NULL"))
    accepted_hash: Mapped[str | None] = mapped_column(String(64))
    budget_day: Mapped[date] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    model: Mapped[str] = mapped_column(String(80))
    prompt_version: Mapped[str] = mapped_column(String(40))
    pricing_version: Mapped[str] = mapped_column(String(50))
    reserved_usd: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    estimated_cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 6))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    cached_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
