"""Regression on real retained evidence and a separately written scalar calculation."""

import math
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest
from scipy.io import netcdf_file

from app.main import reference
from app.sst.erddap import sha256
from app.sst.processing import aggregate, load_subset, method_sha256


def test_retained_inputs_reproduce_reference():
    result = reference()
    root = files("app").joinpath("data")
    assert sha256(root.joinpath("metadata.json").read_bytes()) == result.plan.metadata_sha256
    assert method_sha256() == result.method_sha256
    arrays = []
    for artifact, chunk in zip(result.artifacts, result.plan.chunks, strict=True):
        path = root.joinpath(artifact.file)
        assert sha256(path.read_bytes()) == artifact.sha256
        arrays.append(load_subset(path, result.plan, chunk))
    actual = aggregate(arrays, result.plan)
    for actual_month, stored in zip(actual["months"], result.months, strict=True):
        observed, expected = actual_month.model_dump(), stored.model_dump()
        for key in ("mean_celsius", "min_daily_area_fraction"):
            a, b = observed.pop(key), expected.pop(key)
            assert a is None if b is None else a == pytest.approx(b, abs=1e-10, rel=0)
        assert observed == expected
    assert actual["received_days"] == 3636
    assert actual["low_coverage_days"] == 17


def test_independent_scalar_calculation_agrees_with_reference():
    """Use scipy's raw reader and Python scalar sums, not xarray's aggregation path."""
    result = reference()
    observations = []
    eligible = set()
    weights = {}
    for artifact, chunk in zip(result.artifacts, result.plan.chunks, strict=True):
        path = files("app").joinpath("data", artifact.file)
        with netcdf_file(path, mmap=False) as dataset:
            var = dataset.variables["sst"]
            values = var.data.copy()
            fill = float(var._FillValue)
            for index, lat in enumerate(dataset.variables["latitude"].data):
                for j in range(values.shape[3]):
                    weights[index, j] = math.cos(math.radians(float(lat)))
            for i, seconds in enumerate(dataset.variables["time"].data):
                day = (datetime(1970, 1, 1, tzinfo=UTC) + timedelta(seconds=float(seconds))).date()
                if day < chunk.start or day > chunk.end:
                    continue
                valid = {}
                for y in range(values.shape[2]):
                    for x in range(values.shape[3]):
                        value = float(values[i, 0, y, x])
                        if math.isfinite(value) and value != fill:
                            valid[y, x] = value
                            eligible.add((y, x))
                observations.append((day, valid))
    total_weight = math.fsum(weights[cell] for cell in eligible)
    monthly = defaultdict(list)
    for day, valid in observations:
        available_weight = math.fsum(weights[cell] for cell in valid)
        if available_weight / total_weight >= 0.9:
            mean = (
                math.fsum(value * weights[cell] for cell, value in valid.items()) / available_weight
            )
            monthly[day.replace(day=1)].append(mean)
    for month in result.months:
        values = monthly[month.month]
        if len(values) / month.expected_days < 0.9:
            assert month.mean_celsius is None
        else:
            assert month.mean_celsius == pytest.approx(
                math.fsum(values) / len(values), abs=1e-10, rel=0
            )
