# Initial live reference verification

Retrieved on 2026-10-13 using the registered NOAA CoastWatch endpoint. The bundled
example uses real source data. Normal CI reprocesses the retained subsets offline.

| Item | Observed result |
| --- | --- |
| Dataset | `ncdcOisst21Agg`, OISST final v2.1 |
| Metadata coverage at retrieval | 1981-09-01 to 2026-09-27 |
| Requested period | 2016-01-01 through 2025-12-31 |
| Requested region | 27–30° N, 19–13° W |
| Selected centers | 27.125–29.875° N, 18.875–13.125° W |
| Requested calendar days | 3,653 |
| Returned days within the requested intervals | 3,636 |
| Missing / insufficient daily coverage | 17 days |
| Grid cells | 288; 285 eligible, 3 never valid |
| Monthly records | 120; December 2023 withheld for insufficient coverage |
| Raw subset bytes | 4,297,760 across ten annual chunks |
| Observed fetch + processing elapsed time | 138.344 seconds in the development environment |

The elapsed time is one observation, not a service-level commitment or capacity
benchmark. Provider latency, cache state, concurrency, and deployment hardware may
change it. No hosted AI or paid API was used.

The 2023 request included 2024-01-01 because ERDDAP resolves bounds to available
time coordinates. Per-chunk date enforcement excludes that observation before
combining chunks, preventing double counting and incorrect January averages.

The bundled calculation was recomputed using float64 accumulation. An independent
test reads the retained NetCDF through scipy and uses scalar Python/math sums to
verify every accepted monthly value within 1e-10 °C, including coverage exclusions.
Additional tests use analytically known synthetic values, missing days/months,
duplicate days, grid mismatch, packed CF values, and unit/version mismatches.

## Retained evidence

`backend/app/data` includes `metadata.json`, `reference.json`, and ten unmodified
NetCDF subsets (about 4.3 MB total). These small, public scientific inputs are
deliberately retained in this initial repository fixture so users and CI can
reproduce the exact example even if the live provider revises its data. Future
customer artifacts belong in protected object storage, not Git.

`reference.json` carries their SHA-256 checksums, query URLs, retrieval metadata,
software versions, and the source-code fingerprint of the three scientific modules.
The first result was generated while bootstrapping this branch, so its Git revision
records the initial base plus `+dirty`; the scientific-module fingerprint identifies
the exact processing code and is checked in CI. Deliberate method changes must
update the method version and regenerate the result with the retained source data.

NOAA attribution, source license text, and dataset DOI are preserved in the raw
metadata and result. See [methodology](scientific-method.md) for scientific caveats.
