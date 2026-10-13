# SST reference method — sst-area-monthly-v1

## Source contract

- Provider: NOAA NCEI, via NOAA CoastWatch ERDDAP.
- Server: `https://coastwatch.pfeg.noaa.gov/erddap`.
- Dataset path: `ncdcOisst21Agg` (final OISST v2.1, not the near-real-time product).
- Metadata: <https://coastwatch.pfeg.noaa.gov/erddap/info/ncdcOisst21Agg/index.json>.
- Citation: <https://doi.org/10.25921/RE9P-PT57>.
- Variable: `sst`, standard name `sea_surface_temperature`, units `degree_C`.
- Dimensions: `time, zlev, latitude, longitude`; `zlev = 0`.
- Regular grid: 0.25°, latitude centers -89.875…89.875, longitude centers 0.125…359.875.

The connector verifies the metadata before planning and the units/grid again after
download. Incompatible version, dimension, or unit changes stop execution. The
metadata's global `id` may differ from the requested dataset path; preserve the
raw metadata and actual requested dataset ID rather than silently substituting it.

## Spatial and temporal selection

The Canary Islands preset is the surrounding-ocean box 27–30° N, 19–13° W. Madeira
uses 31–34° N, 18–15° W. These are explicit product presets, not official maritime
boundaries or coastline-following polygons. Only grid centers inside the rectangle
are selected. No fractional boundary-cell intersections are calculated.

Western longitudes are converted to the dataset's 0…360 convention. The current
workflow rejects crossing the antimeridian or Greenwich seam. Requests cover every
available daily value, broken into calendar-year chunks; stride is always one.
CF metadata decode packed values and missing sentinels through xarray/scipy.

Dates are inclusive UTC calendar days. This source represents days at 12:00 UTC.
ERDDAP may resolve requested dates to nearby indices, so downloaded observations
are filtered to each exact chunk interval again. Duplicate days are rejected.
The full requested daily calendar is reindexed to expose gaps, including entire
missing months. Coverage outside provider metadata is rejected, never silently clipped.

## Calculation and coverage

1. Reject nonfinite infinities or finite SST outside provider bounds [-3, 45] °C.
   Decoded NaNs remain missing; do not convert them to zero-temperature observations.
2. Define the run's eligible-cell mask as cells with a valid value on at least one
   requested day. Exclude never-valid cells and disclose their count. This is not
   an independently verified land mask; a never-observed ocean cell is also excluded.
3. Weight eligible regular-grid cells by cosine(latitude), proportional to their
   cell areas. For each day divide the weighted sum by the available valid-cell weights.
4. Require at least 90% of the eligible area to be observed on a day; otherwise
   withhold its regional mean. Record daily area coverage. The 90% threshold is an
   explicit MVP policy, not a claim of scientific consensus.
5. Give valid daily regional means equal weight within each month. Require at least
   90% of requested days in that month to have valid daily means. Otherwise emit a
   null monthly value and a blank CSV cell; the chart must not bridge that gap.
6. For a partial requested calendar month, compute coverage over its requested
   days and flag `partial_month=true`. It is not interchangeable with a full month.

The mask is computed once over the complete analysis, not separately for each
download chunk. Different requested periods can yield different masks; comparisons
must check this. Monthly means, coverage fractions, and eligibility counts are
deterministic application calculations, not model-generated values.

## Limits

The current CLI supports at most 3,663 days, 2,000,000 cell-time values, 16 MB per
response, and 64 MB total subset bytes. Metadata is capped at 256 KB. It makes one
provider request at a time; requests have connect/read timeouts and an elapsed
download check. A ten-minute run budget is checked before each chunk (an in-flight
request may finish or time out after that boundary). There are no automatic retries.

Network destinations are fixed to the registered NOAA metadata/subset routes;
redirects are rejected. Partial output remains available for inspection if a
request fails. Future workers need hard process budgets as well as these checks.

## Provenance and limitations

Each CLI output contains exact metadata bytes and hash, resolved region/grid/date
parameters, source query URLs, unmodified subset bytes and hashes, software versions,
method version, source revision, coverage metrics, result JSON, and CSV. A rerun
creates a new directory and does not overwrite earlier evidence.

OISST combines observations and interpolation on a relatively coarse grid. It does
not measure conditions at a particular beach. Values may be revised upstream;
exact reproducibility requires retained subsets, not just a query URL. No causal
attribution, trend significance, uncertainty interval, anomaly, or marine-heatwave
classification is produced. The `err` field is not currently propagated into uncertainty.

References:
- [NOAA OISST product description](https://www.ncei.noaa.gov/products/optimum-interpolation-sst)
- [ERDDAP grid requests and stride](https://coastwatch.pfeg.noaa.gov/erddap/griddap/documentation.html)
- [Xarray area weighting](https://docs.xarray.dev/en/stable/examples/area_weighted_temperature.html)
