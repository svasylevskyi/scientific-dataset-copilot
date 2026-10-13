from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

MAX_DAYS = 3663
MAX_CELLS = 2_000_000
MIN_AREA_COVERAGE = 0.9
MIN_MONTH_COVERAGE = 0.9
METHOD_VERSION = "sst-area-monthly-v1"


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class Bounds(Contract):
    west: float = Field(ge=-180, le=180)
    east: float = Field(ge=-180, le=180)
    south: float = Field(ge=-89, le=89)
    north: float = Field(ge=-89, le=89)

    @model_validator(mode="after")
    def check_region(self):
        if self.east <= self.west or self.north <= self.south:
            raise ValueError("Bounds must increase; antimeridian crossing is not supported yet.")
        if self.east - self.west > 10 or self.north - self.south > 10:
            raise ValueError("The reference workflow supports regions up to 10° on each axis.")
        # OISST uses 0..360. Splitting requests at that seam is a later capability.
        if self.west < 0 < self.east:
            raise ValueError("Regions crossing the Greenwich meridian are not supported yet.")
        return self


class Region(Contract):
    id: str
    name: str
    bounds: Bounds


REGIONS = {
    "canaries": Region(
        id="canaries",
        name="Canary Islands — surrounding ocean",
        bounds=Bounds(west=-19, east=-13, south=27, north=30),
    ),
    "madeira": Region(
        id="madeira",
        name="Madeira — surrounding ocean",
        bounds=Bounds(west=-18, east=-15, south=31, north=34),
    ),
}


class AnalysisRequest(Contract):
    region_id: Literal["canaries", "madeira"] = "canaries"
    start: date
    end: date

    @model_validator(mode="after")
    def check_dates(self):
        if self.end < self.start:
            raise ValueError("End date must be on or after start date.")
        if (self.end - self.start).days + 1 > MAX_DAYS:
            raise ValueError("The reference workflow supports at most ten years (3663 days).")
        return self


class Source(Contract):
    dataset_id: str
    name: str
    provider: str
    version: str
    variable: str
    units: str
    metadata_url: str
    citation_url: str
    coverage_start: date
    coverage_end: date
    latitude_min: float
    latitude_max: float
    longitude_min: float
    longitude_max: float
    grid_resolution: float
    license: str


class QueryChunk(Contract):
    start: date
    end: date
    url: str


class QueryPlan(Contract):
    request: AnalysisRequest
    region: Region
    source: Source
    selected_grid_bounds: Bounds
    estimated_cells: int
    chunks: list[QueryChunk]
    metadata_sha256: str
    metadata_fetched_at: datetime
    warnings: list[str]


class MonthlyValue(Contract):
    month: date
    mean_celsius: float | None
    valid_days: int
    expected_days: int
    coverage_fraction: float
    min_daily_area_fraction: float
    partial_month: bool


class RawArtifact(Contract):
    file: str
    sha256: str
    bytes: int
    query_url: str
    duration_seconds: float


class AnalysisResult(Contract):
    schema_version: Literal[1] = 1
    method_version: str = METHOD_VERSION
    plan: QueryPlan
    created_at: datetime
    source_kind: Literal["live_noaa", "synthetic_test"]
    months: list[MonthlyValue]
    actual_start: date
    actual_end: date
    received_days: int
    expected_days: int
    eligible_cells: int
    never_valid_cells: int
    low_coverage_days: int
    artifacts: list[RawArtifact]
    runtime_versions: dict[str, str]
    source_revision: str
    method_sha256: str
    warnings: list[str]
