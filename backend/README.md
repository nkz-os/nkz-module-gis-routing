# GIS Routing — Backend

FastAPI service for the coverage path planning and routing engine.

## Coverage engine (Fields2Cover)

Route coverage is computed with [Fields2Cover](https://github.com/Fields2Cover/Fields2Cover)
(BSD-3), built from source inside the Docker image (C++17 + SWIG Python bindings).
There is no pip wheel; the `Dockerfile` builder stage compiles F2C v2.0.0 and its
OR-Tools dependency (auto-fetched by F2C's CMake), and the runtime stage carries the
native libraries and the `fields2cover` Python module.

## Running tests (Fields2Cover required)

`fields2cover` is only available inside the built image, so run the test suite there
with the working tree mounted:

```bash
docker build -t gis-routing-backend:f2c-prod .
docker run --rm -v "$PWD":/app -w /app gis-routing-backend:f2c-prod python -m pytest -q
```

A quick import/pipeline smoke check:

```bash
docker run --rm gis-routing-backend:f2c-prod python scripts/f2c_smoke.py
```

## API

### `POST /api/routing/generate`

Builds a validated coverage plan for a parcel and (optionally) persists it as an
`AgriParcelOperation`.

Request additions:

- `pattern`: `auto` (default), `boustrophedon`, `snake`, `spiral` or `headland-only`.
  Legacy aliases `ab-line` and `ab-skip` are still accepted.
- `return_to_access`: return to the access point at the end of the route.
- `planned_start_at`, `planned_end_at`: ISO 8601, UTC.
- `pattern_config.headland_passes`: integer >= 1. A value of 0 is coerced to 1 with a warning.
- Deprecated but accepted (ignored with a warning; removed in the next major contract version):
  `selected_alternative_id`, `base_pattern_id`, `pattern_config.direction`, `coupling_model`.

Response: `{success, operation_id, plan, selected, prescription_map}`.
`selected` and `prescription_map` are legacy and deprecated.

`plan` keys:

| Key | Description |
|---|---|
| `pattern`, `curve_type`, `swath_count`, `headland_passes` | Plan summary |
| `route` | `LineString`, or `MultiLineString` when manual turns were needed |
| `swaths` | `[{index, kind: work\|headland, geometry}]` |
| `access_path`, `access_point`, `exit_point` | Transit geometry |
| `working_area` | Drivable area used for planning |
| `unreached_parts` | `[{geometry, area_ha}]` |
| `metrics` | `worked_distance_m, non_working_distance_m, access_distance_m, field_efficiency, covered_area_ha, parcel_area_ha, working_area_ha` |
| `validation` | `{ok, checks[{id, ok, value, limit, geometry}], fallbacks_applied[], warnings[{code, geometry, params}]}` |
| `exclusion_zones` | `FeatureCollection` |
| `prescription` | `null` in this version |

Guarantees: the route stays inside the parcel minus half the working width
(tolerance 0.5 m) and outside every no-go zone plus half the working width
(tolerance 0.1 m). When the preferred plan cannot satisfy this, a fallback ladder
is applied (headland widening, Reeds-Shepp curves, another pattern, manual turns);
the route is never clipped.

Warning codes: `UNREACHED_AREA`, `HEADLAND_WIDENED`, `MANUAL_TURN`, `ACCESS_PATH_UNAVAILABLE`.
`fallbacks_applied` entries: `headland_passes:a->b`, `curve:reeds_shepp`,
`pattern:<p>`, `manual_turns:<n>`.

Errors use the body `{code, detail, params}`; `params` carries GeoJSON to highlight
on a map (`point`, `geometry`).

| Code | HTTP |
|---|---|
| `NO_DRIVABLE_AREA` | 422 |
| `ACCESS_OUTSIDE_PARCEL` | 422 |
| `ACCESS_IN_ZONE` | 422 |
| `MACHINE_WIDTH_MISSING` | 422 |
| `TURNING_RADIUS_MISSING` | 422 |
| `INVALID_GEOMETRY` | 400 |
| `ENGINE_FAILURE` | 500 |

Persisted `AgriParcelOperation` attributes added: `accessPoint`, `accessPath`,
`exclusionZones`, `swaths`, `workingArea`, `validation`, `planVersion` (1),
`headlandPasses`, `plannedStartAt`, `plannedEndAt`. `couplingModel` is no longer written.

### A-B pathfinding

`POST /path/calculate` and `GET /path/{job_id}` require authentication.

- Jobs are tenant-scoped, expire after 1 h, and each tenant may hold at most 20 live
  jobs; beyond that the API answers 429 `{"detail": {"code": "JOB_LIMIT"}}`.
- `machine_id` resolves the working width; an unknown machine makes the job `failed`.
- Without `parcel_id`, the no-go zones of every tenant parcel intersecting the search
  box are respected.
- `min_turn_radius_m` is deprecated and ignored.
- Alternatives carry `max_slope_deg_found` and `blocked_cells_hit`; completed jobs carry `report`.

## Tests

The default run excludes the `slow` marker. The full guarantee matrix (240 cases)
runs nightly (`.github/workflows/nightly-slow.yml`) or on demand with `-m slow`.
