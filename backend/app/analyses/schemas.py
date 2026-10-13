from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.sst.contracts import AnalysisRequest


class AnalysisInput(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    title: str = Field(min_length=1, max_length=120)
    query: AnalysisRequest


class AnalysisUpdate(AnalysisInput):
    version: int = Field(ge=1, strict=True)


class AnalysisView(AnalysisInput):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    version: int
    created_at: datetime
    updated_at: datetime


class RunInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_key: UUID
    version: int = Field(ge=1, strict=True)


class EventView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    attempt: int
    stage: str
    message: str
    created_at: datetime


class ArtifactView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    name: str
    media_type: str
    sha256: str
    bytes: int


class RunView(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: UUID
    analysis_id: UUID
    title: str
    query: AnalysisRequest
    analysis_version: int
    status: Literal["queued", "running", "succeeded", "failed", "cancelled"]
    stage: str
    attempt: int
    created_at: datetime
    finished_at: datetime | None
    cancel_requested_at: datetime | None
    expires_at: datetime | None
    error: str | None
    results_available: bool = False


class RunDetail(RunView):
    events: list[EventView]
    artifacts: list[ArtifactView]
