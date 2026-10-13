"""A deliberately narrow, metadata-validated ERDDAP adapter. No arbitrary URLs."""

import hashlib
import json
import math
from datetime import date, datetime, timedelta
from pathlib import Path
from time import monotonic
from urllib.parse import quote

import httpx

from app.sst.contracts import (
    MAX_CELLS,
    REGIONS,
    AnalysisRequest,
    Bounds,
    QueryChunk,
    QueryPlan,
    Source,
)

BASE_URL = "https://coastwatch.pfeg.noaa.gov/erddap"
DATASET_ID = "ncdcOisst21Agg"
METADATA_URL = f"{BASE_URL}/info/{DATASET_ID}/index.json"
MAX_METADATA_BYTES = 256_000
MAX_CHUNK_BYTES = 16_000_000
MAX_TOTAL_BYTES = 64_000_000


class SourceError(ValueError):
    """A source contract, coverage, or retrieval failure safe to explain to a user."""


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def parse_metadata(raw: bytes) -> Source:
    try:
        table = json.loads(raw)["table"]
        expected = ["Row Type", "Variable Name", "Attribute Name", "Data Type", "Value"]
        if table["columnNames"] != expected:
            raise SourceError("ERDDAP metadata columns have changed.")
        attrs = {(r[1], r[2]): r[4] for r in table["rows"] if r[0] == "attribute"}
        variables = {r[1]: r[4] for r in table["rows"] if r[0] == "variable"}
        if variables.get("sst") != "time, zlev, latitude, longitude":
            raise SourceError("Unsupported SST dimensions; review the connector.")
        if attrs["sst", "standard_name"] != "sea_surface_temperature":
            raise SourceError("The selected variable is not sea surface temperature.")
        if attrs["sst", "units"] != "degree_C":
            raise SourceError("The source no longer advertises the expected Celsius units.")
        if attrs["NC_GLOBAL", "product_version"] != "Version v02r01":
            raise SourceError("OISST version changed; scientific revalidation is required.")
        lat = [float(x) for x in attrs["latitude", "actual_range"].split(",")]
        lon = [float(x) for x in attrs["longitude", "actual_range"].split(",")]
        if lat != [-89.875, 89.875] or lon != [0.125, 359.875]:
            raise SourceError("OISST grid has changed; review the connector.")
        if any(
            float(attrs["NC_GLOBAL", f"geospatial_{axis}_resolution"]) != 0.25
            for axis in ("lat", "lon")
        ):
            raise SourceError("Unsupported grid spacing.")
        return Source(
            dataset_id=DATASET_ID,
            name=attrs["NC_GLOBAL", "title"],
            provider="NOAA NCEI",
            version=attrs["NC_GLOBAL", "product_version"],
            variable="sst",
            units="°C",
            metadata_url=METADATA_URL,
            citation_url="https://doi.org/10.25921/RE9P-PT57",
            coverage_start=date.fromisoformat(attrs["NC_GLOBAL", "time_coverage_start"][:10]),
            coverage_end=date.fromisoformat(attrs["NC_GLOBAL", "time_coverage_end"][:10]),
            latitude_min=lat[0],
            latitude_max=lat[1],
            longitude_min=lon[0],
            longitude_max=lon[1],
            grid_resolution=0.25,
            license=attrs["NC_GLOBAL", "license"],
        )
    except (KeyError, TypeError, IndexError, json.JSONDecodeError) as exc:
        raise SourceError("Incomplete or malformed ERDDAP metadata.") from exc


def _inside_grid(low: float, high: float, origin: float, step: float) -> tuple[float, float]:
    start = origin + math.ceil((low - origin) / step) * step
    stop = origin + math.floor((high - origin) / step) * step
    if stop < start:
        raise SourceError("The region contains no grid-cell centers.")
    return start, stop


def plan_query(request: AnalysisRequest, raw: bytes, fetched_at: datetime) -> QueryPlan:
    source = parse_metadata(raw)
    if request.start < source.coverage_start or request.end > source.coverage_end:
        raise SourceError(
            f"Requested dates exceed this source's available coverage "
            f"({source.coverage_start} to {source.coverage_end}). Choose an available period."
        )
    region = REGIONS[request.region_id]
    bounds = region.bounds
    south, north = _inside_grid(bounds.south, bounds.north, source.latitude_min, 0.25)
    # Keep 0° at the upper bound of a western region as 360°, not 0°.
    offset = 360 if bounds.west < 0 else 0
    west, east = _inside_grid(bounds.west + offset, bounds.east + offset, 0.125, 0.25)
    cells = round(((north - south) / 0.25 + 1) * ((east - west) / 0.25 + 1))
    estimate = cells * ((request.end - request.start).days + 1)
    if estimate > MAX_CELLS:
        raise SourceError(f"Request exceeds the {MAX_CELLS:,} cell-time-value limit.")
    chunks = []
    start = request.start
    while start <= request.end:
        end = min(date(start.year, 12, 31), request.end)
        query = (
            f"sst[({start}T12:00:00Z):1:({end}T12:00:00Z)][(0.0)]"
            f"[({south}):1:({north})][({west}):1:({east})]"
        )
        chunks.append(
            QueryChunk(
                start=start,
                end=end,
                url=f"{BASE_URL}/griddap/{DATASET_ID}.nc?{quote(query, safe='')}",
            )
        )
        start = end + timedelta(days=1)
    return QueryPlan(
        request=request,
        region=region,
        source=source,
        selected_grid_bounds=Bounds(
            west=west - offset, east=east - offset, south=south, north=north
        ),
        estimated_cells=estimate,
        chunks=chunks,
        metadata_sha256=sha256(raw),
        metadata_fetched_at=fetched_at,
        warnings=[
            "The region is a stated bounding box, not an island boundary or a coastal station.",
            "Final OISST data lag real time. Coverage is taken from the inspected metadata.",
            "A time stride is sampling, not averaging; this plan requests every available day.",
        ],
    )


def fetch_bytes(client: httpx.Client, url: str, limit: int) -> bytes:
    # Defense in depth: callers cannot turn the connector into a generic URL fetcher.
    if url != METADATA_URL and not url.startswith(f"{BASE_URL}/griddap/{DATASET_ID}.nc?"):
        raise SourceError("Only the registered NOAA source is allowed.")
    started = monotonic()
    content = bytearray()
    try:
        with client.stream("GET", url, follow_redirects=False) as response:
            response.raise_for_status()
            for piece in response.iter_bytes(chunk_size=65_536):
                if len(content) + len(piece) > limit:
                    raise SourceError("The source response exceeded the download limit.")
                if monotonic() - started > 90:
                    raise SourceError("The source response exceeded the 90-second time limit.")
                content.extend(piece)
    except httpx.HTTPError as exc:
        raise SourceError(f"NOAA request failed ({type(exc).__name__}); retry explicitly.") from exc
    return bytes(content)


def write_new(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
