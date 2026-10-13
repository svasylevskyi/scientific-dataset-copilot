from datetime import date, datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from app.accounts.schemas import EmailInput, Input


class PlanInput(Input):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: str = Field(default="", max_length=500)
    active: bool = True
    monthly_analyses: int = Field(ge=0, le=10000, strict=True)
    concurrent_analyses: int = Field(ge=1, le=20, strict=True)
    max_date_range_days: int = Field(ge=1, le=3663, strict=True)
    retention_days: int = Field(ge=1, le=3650, strict=True)


class PlanUpdate(PlanInput):
    version: int = Field(ge=1)


class PlanVersion(Input):
    version: int = Field(ge=1)


class PlanView(PlanInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    is_default: bool
    billing: Literal["free"] = "free"


class AdminPlanView(PlanView):
    workspace_count: int


class AssignmentInput(EmailInput):
    plan_id: UUID
    status: Literal["active", "suspended"] = "active"


class UsageRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    status: Literal["reserved", "consumed", "released"]
    period_start: date
    created_at: datetime
    finished_at: datetime | None
    release_reason: Literal["failed", "cancelled"] | None


class UsageView(BaseModel):
    plan: PlanView
    status: Literal["active", "suspended"]
    period_start: date
    period_end: date
    consumed: int
    reserved: int
    remaining: int
    concurrent_reserved: int
    can_reserve: bool
    blocked_reason: str | None
    live_execution_available: Literal[True] = True
    recent: list[UsageRecord]
