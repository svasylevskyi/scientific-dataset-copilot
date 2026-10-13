import csv
import io

import numpy as np
import pandas as pd
import pytest
import xarray as xr

from app.sst.erddap import SourceError
from app.sst.processing import aggregate, load_subset, monthly_csv


def sample(days=31):
    return xr.DataArray(
        np.tile(np.array([[10.0, 10.0], [30.0, 30.0]]), (days, 1, 1)),
        dims=("time", "latitude", "longitude"),
        coords={
            "time": pd.date_range("2020-01-01T12:00:00", periods=days),
            "latitude": [0.0, 60.0],
            "longitude": [0.125, 0.375],
        },
    )


def test_area_weights_have_independent_analytic_answer(plan):
    # Equal-width cells at 60 degrees have half the area of equatorial cells.
    result = aggregate([sample()], plan)
    month = result["months"][0]
    assert month.mean_celsius == pytest.approx((10 * 2 + 30 * 1) / 3)
    assert month.mean_celsius != pytest.approx(20)  # unweighted mean is incorrect
    assert month.valid_days == 31
    assert not month.partial_month


def test_missing_dates_are_not_zero_filled_or_interpolated(plan):
    result = aggregate([sample().isel(time=slice(4, None))], plan)
    assert result["months"][0].mean_celsius is None
    assert result["months"][0].valid_days == 27
    assert result["low_coverage_days"] == 4


def test_missing_whole_month_remains_visible(plan):
    plan = plan.model_copy(
        update={
            "request": plan.request.model_copy(update={"end": pd.Timestamp("2020-03-31").date()})
        }
    )
    march = sample().assign_coords(time=pd.date_range("2020-03-01T12:00:00", periods=31))
    result = aggregate([sample(), march], plan)
    assert len(result["months"]) == 3
    february = result["months"][1]
    assert february.expected_days == 29
    assert february.mean_celsius is None
    assert february.coverage_fraction == 0


def test_daily_spatial_coverage_excludes_sparse_observations(plan):
    data = sample()
    data[0, 0, :] = np.nan  # removes two-thirds of the eligible area
    result = aggregate([data], plan)
    assert result["low_coverage_days"] == 1
    assert result["months"][0].valid_days == 30
    assert result["months"][0].mean_celsius == pytest.approx(50 / 3)


def test_never_valid_cells_excluded_but_disclosed(plan):
    data = sample()
    data[:, 1, :] = np.nan
    result = aggregate([data], plan)
    assert result["never_valid_cells"] == 2
    assert result["eligible_cells"] == 2
    assert result["months"][0].mean_celsius == 10


def test_partial_month_is_explicit(plan):
    plan = plan.model_copy(
        update={
            "request": plan.request.model_copy(update={"start": pd.Timestamp("2020-01-16").date()})
        }
    )
    month = aggregate([sample()], plan)["months"][0]
    assert month.partial_month
    assert month.expected_days == 16


@pytest.mark.parametrize("value", [-9.99, 46, float("inf")])
def test_undecoded_fill_or_impossible_values_fail(plan, value):
    data = sample()
    data[0, 0, 0] = value
    with pytest.raises(SourceError, match="source bounds"):
        aggregate([data], plan)


def test_duplicate_days_fail(plan):
    with pytest.raises(SourceError, match="Duplicate"):
        aggregate([sample(), sample()], plan)


def test_all_missing_region_fails(plan):
    with pytest.raises(SourceError, match="no valid"):
        aggregate([sample() * np.nan], plan)


def test_cf_decoding_and_actual_grid_validation(tmp_path, plan):
    bounds = plan.selected_grid_bounds
    lat = np.arange(bounds.south, bounds.north + 0.125, 0.25)
    lon = np.arange(bounds.west + 360, bounds.east + 360 + 0.125, 0.25)
    values = np.full((2, 1, len(lat), len(lon)), 21.25)
    values[0, 0, 0, 0] = np.nan
    dataset = xr.Dataset(
        {"sst": (("time", "zlev", "latitude", "longitude"), values)},
        coords={
            "time": pd.date_range("2020-01-01T12:00:00", periods=2),
            "zlev": [0.0],
            "latitude": lat,
            "longitude": lon,
        },
    )
    dataset.sst.attrs["units"] = "degree_C"
    path = tmp_path / "packed.nc"
    dataset.to_netcdf(
        path,
        engine="scipy",
        encoding={"sst": {"dtype": "int16", "scale_factor": 0.01, "_FillValue": -999}},
    )
    loaded = load_subset(path, plan, plan.chunks[0])
    assert np.isnan(loaded[0, 0, 0])
    assert float(loaded[1, 0, 0]) == pytest.approx(21.25)
    # A source may serve a valid file but an incorrect region: reject it.
    dataset = dataset.assign_coords(longitude=lon + 0.25)
    dataset.to_netcdf(tmp_path / "wrong.nc", engine="scipy")
    with pytest.raises(SourceError, match="longitude"):
        load_subset(tmp_path / "wrong.nc", plan, plan.chunks[0])


def test_csv_blanks_low_coverage_values_and_includes_units(plan):
    months = aggregate([sample(days=20)], plan)["months"]
    rows = list(csv.DictReader(io.StringIO(monthly_csv(months))))
    assert rows[0]["mean_sst_celsius"] == ""
    assert rows[0]["expected_days"] == "31"
