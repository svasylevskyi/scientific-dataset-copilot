"""Deterministic, coverage-aware regional SST aggregation."""

import calendar
import csv
import hashlib
import io
from importlib.metadata import version
from pathlib import Path

import numpy as np
import pandas as pd
import xarray as xr

from app.sst.contracts import (
    MAX_CELLS,
    MIN_AREA_COVERAGE,
    MIN_MONTH_COVERAGE,
    MonthlyValue,
    QueryChunk,
    QueryPlan,
)
from app.sst.erddap import SourceError


def runtime_versions() -> dict[str, str]:
    return {name: version(name) for name in ("xarray", "numpy", "pandas", "scipy")}


def method_sha256() -> str:
    digest = hashlib.sha256()
    for name in ("contracts.py", "erddap.py", "processing.py"):
        digest.update(name.encode())
        digest.update(Path(__file__).with_name(name).read_bytes())
    return digest.hexdigest()


def validate_grid(dataset: xr.Dataset, plan: QueryPlan) -> xr.DataArray:
    if "sst" not in dataset or dataset.sst.dims != ("time", "zlev", "latitude", "longitude"):
        raise SourceError("Downloaded SST dimensions do not match the inspected source.")
    sst = dataset.sst
    if sst.size > MAX_CELLS:
        raise SourceError("Downloaded array exceeds the cell-time-value limit.")
    if sst.attrs.get("units") != "degree_C":
        raise SourceError("Downloaded SST has unexpected units; no implicit conversion is allowed.")
    if dataset.zlev.size != 1 or float(dataset.zlev[0]) != 0:
        raise SourceError("Unexpected vertical coordinate.")
    bounds = plan.selected_grid_bounds
    expected_lat = np.arange(bounds.south, bounds.north + 0.125, 0.25)
    offset = 360 if bounds.west < 0 else 0
    expected_lon = np.arange(bounds.west + offset, bounds.east + offset + 0.125, 0.25)
    if not np.array_equal(dataset.latitude.values, expected_lat):
        raise SourceError("Downloaded latitude cells differ from the requested region.")
    if not np.array_equal(dataset.longitude.values, expected_lon):
        raise SourceError("Downloaded longitude cells differ from the requested region.")
    return sst.isel(zlev=0, drop=True)


def load_subset(path: Path, plan: QueryPlan, chunk: QueryChunk) -> xr.DataArray:
    # ERDDAP .nc produces classic NetCDF. Explicit engine avoids backend selection differences.
    with xr.open_dataset(path, engine="scipy", decode_cf=True) as dataset:
        sst = validate_grid(dataset, plan)
        # ERDDAP resolves dates to nearest available indices. Enforce our exact interval again.
        return sst.sel(time=slice(str(chunk.start), str(chunk.end))).load()


def aggregate(arrays: list[xr.DataArray], plan: QueryPlan) -> dict:
    arrays = [array for array in arrays if array.sizes["time"]]
    if not arrays:
        raise SourceError("No source observations fall within the requested dates.")
    sst = xr.concat(arrays, dim="time", join="exact").sortby("time").astype("float64")
    if sst.size > MAX_CELLS:
        raise SourceError("Combined data exceed the processing limit.")
    sst = sst.sel(time=slice(str(plan.request.start), str(plan.request.end)))
    times = pd.DatetimeIndex(sst.time.values)
    if times.has_duplicates or times.normalize().has_duplicates:
        raise SourceError("Duplicate daily observations would bias the monthly means.")
    if not all((times.hour == 12) & (times.minute == 0) & (times.second == 0)):
        raise SourceError("OISST observation times differ from the expected daily noon convention.")
    values = sst.values
    if np.isinf(values).any() or ((values < -3) | (values > 45)).any():
        raise SourceError("SST values violate source bounds; inspect decoding and source quality.")
    valid = sst.notnull()
    eligible = valid.any(dim="time")
    eligible_count = int(eligible.sum())
    if eligible_count == 0:
        raise SourceError("The requested region has no valid SST observations.")
    # For the validated, regular 0.25° grid, cosine latitude is proportional to cell area.
    weights = np.cos(np.deg2rad(sst.latitude.astype("float64"))).broadcast_like(eligible)
    eligible_weights = weights.where(eligible, 0)
    daily_weights = eligible_weights.where(valid, 0)
    denominator = daily_weights.sum(dim=("latitude", "longitude"))
    area_fraction = denominator / eligible_weights.sum()
    numerator = (sst.fillna(0) * daily_weights).sum(dim=("latitude", "longitude"))
    regional = (numerator / denominator.where(denominator > 0)).where(
        area_fraction >= MIN_AREA_COVERAGE
    )
    days = pd.date_range(plan.request.start, plan.request.end, freq="D")
    frame = pd.DataFrame(
        {"sst": regional.values, "area_fraction": area_fraction.values},
        index=times.normalize(),
    ).reindex(days)
    frame["area_fraction"] = frame["area_fraction"].fillna(0)
    months = []
    for month, group in frame.groupby(frame.index.to_period("M")):
        expected = len(group)
        valid_days = int(group.sst.notna().sum())
        coverage = valid_days / expected
        mean = float(group.sst.mean()) if coverage >= MIN_MONTH_COVERAGE else None
        full_month_days = calendar.monthrange(month.year, month.month)[1]
        months.append(
            MonthlyValue(
                month=month.start_time.date(),
                mean_celsius=mean,
                valid_days=valid_days,
                expected_days=expected,
                coverage_fraction=coverage,
                min_daily_area_fraction=float(group.area_fraction.min()),
                partial_month=expected != full_month_days,
            )
        )
    low_days = int((frame.area_fraction < MIN_AREA_COVERAGE).sum())
    never_valid = int(eligible.size - eligible_count)
    warnings = [
        "OISST is a blended, interpolated gridded product, not an in-situ coastal measurement.",
        "Eligible cells are those with at least one valid value in this run. Never-valid cells "
        "are excluded; they are not independently classified as land.",
        "Daily means need 90% eligible area; monthly means need 90% valid requested days. "
        "Missing days are not interpolated. Partial calendar months are explicitly flagged.",
        "The fixed eligible-cell mask is specific to this analysis period. Comparisons across "
        "runs require checking the mask and method, not just the reported means.",
        "No trend significance, causal attribution, anomaly, or marine-heatwave diagnosis is made.",
    ]
    if low_days:
        warnings.append(f"{low_days} requested days failed area coverage or had no observation.")
    if any(month.mean_celsius is None for month in months):
        warnings.append("Some monthly values are withheld because coverage is below 90%.")
    return dict(
        months=months,
        actual_start=times.min().date(),
        actual_end=times.max().date(),
        received_days=len(times),
        expected_days=len(days),
        eligible_cells=eligible_count,
        never_valid_cells=never_valid,
        low_coverage_days=low_days,
        warnings=warnings,
    )


def monthly_csv(months: list[MonthlyValue]) -> str:
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow(
        [
            "month",
            "mean_sst_celsius",
            "valid_days",
            "expected_days",
            "coverage_fraction",
            "min_daily_area_fraction",
            "partial_month",
        ]
    )
    for month in months:
        writer.writerow(
            [
                month.month.isoformat(),
                month.mean_celsius if month.mean_celsius is not None else "",
                month.valid_days,
                month.expected_days,
                month.coverage_fraction,
                month.min_daily_area_fraction,
                str(month.partial_month).lower(),
            ]
        )
    return output.getvalue()
