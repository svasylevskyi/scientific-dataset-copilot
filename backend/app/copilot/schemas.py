from datetime import date, datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.analyses.schemas import AnalysisInput
from app.sst.contracts import QueryPlan


class Intent(BaseModel):
    """All fields required for strict provider JSON schema; no executable model output."""

    model_config = ConfigDict(extra="forbid")
    operation: Literal["monthly_sst", "unclear", "unsupported"]
    region_id: Literal["canaries", "madeira"] | None
    start: date | None
    end: date | None
    clarification: Literal["none", "variable", "region", "dates", "method", "ambiguous"]


class PlanningInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    request_key: UUID
    prompt: str = Field(min_length=3, max_length=2000)
    parent_id: UUID | None = None


class Proposal(BaseModel):
    analysis: AnalysisInput
    plan: QueryPlan
    method: str = "Area-weighted daily regional means, averaged into monthly means."
    allowance_required: int = 1
    retention_days: int
    can_run: bool
    blocked_reason: str | None


class PlanningView(BaseModel):
    id: UUID
    status: Literal["pending", "ready", "clarification", "unsupported", "failed"]
    message: str
    prompt: str
    turn: int
    proposal: Proposal | None = None
    analysis_id: UUID | None = None
    created_at: datetime


class PlannerStatus(BaseModel):
    enabled: bool
    daily_limit: int
    remaining: int
    resets_at: datetime
    blocked_reason: str | None


class PlanningCosts(BaseModel):
    day: date
    model: str
    requests: int
    estimated_cost_usd: Decimal
    unresolved_requests: int
    budget_used_usd: Decimal
    daily_budget_usd: Decimal
