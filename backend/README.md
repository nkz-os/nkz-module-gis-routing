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
- `planned_start_at`, `planned_end_at`: ISO 8601 with a timezone offset (e.g. `Z`);
  stored in UTC. A date without offset is rejected with 422.
- `pattern_config.headland_passes`: integer >= 1. A value of 0 is coerced to 1 (logged).
- Deprecated but accepted (ignored and logged; removed in the next major contract version):
  `selected_alternative_id`, `base_pattern_id`, `pattern_config.direction`, `coupling_model`.

Response: `{success, operation_id, persisted, plan, selected, prescription_map}`.
`persisted` is `true` only when persistence was requested (`persist` and `parcel_id`)
and the operation was written; on a write failure it is `false`, `operation_id` is
`null` and the plan is still returned.
`selected` and `prescription_map` are legacy and deprecated.

`plan` keys:

| Key | Description |
|---|---|
| `pattern`, `curve_type`, `swath_count`, `headland_passes` | Plan summary |
| `route` | `LineString`, or `MultiLineString` when manual turns were needed |
| `swaths` | `[{index, kind: work\|headland, geometry}]` |
| `access_path`, `access_point`, `exit_point` | Transit geometry: gate -> route start |
| `return_path` | Route end -> gate when `return_to_access` (else `null`); `exit_point` is then the gate |
| `working_area` | Drivable area used for planning |
| `unreached_parts` | `[{geometry, area_ha}]` |
| `metrics` | `worked_distance_m, non_working_distance_m, access_distance_m, access_leg_distance_m, return_distance_m, field_efficiency, covered_area_ha, parcel_area_ha, working_area_ha` |
| `validation` | `{ok, checks[{id, ok, value, limit, geometry}], fallbacks_applied[], warnings[{code, geometry, params}]}` |
| `exclusion_zones` | `FeatureCollection` |
| `prescription` | `null` in this version |

Guarantees: the route stays inside the parcel minus half the working width
(tolerance 0.5 m) and outside every no-go zone plus half the working width
(tolerance 0.1 m). This holds for every pattern, `headland-only` included.
When the preferred plan cannot satisfy this, a fallback ladder is applied
(headland widening, Reeds-Shepp curves, another pattern, manual turns); the route
is never clipped.

Transit: the access is a straight leg from the gate on the fence to the area
eroded by half the working width, then a path inside that area to the route start
(`access_path` is both, joined). The leg is checked against the parcel and the
zones (`inside_parcel:access_leg`, `outside_zones:access_leg`); the access and
return paths against the eroded parcel and the zones (`...:access_path`,
`...:return_path`). `starts_at_access` measures gate -> start of the access and
`access_reaches_route` access end -> route start (both <= 1 m). A transit
geometry that fails a parcel or zone check is never returned: it is dropped and
`ACCESS_PATH_UNAVAILABLE` is reported.

Pattern `auto` has a wall-time budget (`LADDER_TIME_BUDGET_S`, default 30 s): once
a valid plan exists and the budget is spent, the best plan so far is returned and
`time_budget` is added to `fallbacks_applied` (the attempt in progress finishes first).

No-go zones stored on the parcel must be a GeoJSON FeatureCollection whose features
have a geometry; otherwise `/generate` answers `INVALID_GEOMETRY`. Self-intersecting
zone polygons are repaired keeping all their area, and the repair is logged.

Warning codes: `UNREACHED_AREA`, `HEADLAND_WIDENED`, `MANUAL_TURN`, `ACCESS_PATH_UNAVAILABLE`.
`fallbacks_applied` entries: `headland_passes:a->b`, `curve:reeds_shepp`,
`pattern:<p>`, `manual_turns:<n>`, `time_budget`.

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

`implement_id` / `tractor_id` that resolves to no machine answers `MACHINE_WIDTH_MISSING`.

Persisted `AgriParcelOperation` attributes added: `accessPoint`, `accessPath`,
`returnPath` (when present), `exclusionZones`, `swaths`, `workingArea`, `validation`, `planVersion` (1),
`headlandPasses`, `plannedStartAt`, `plannedEndAt`. `couplingModel` is no longer written.

### A-B pathfinding

`POST /path/calculate` and `GET /path/{job_id}` require authentication.

- Jobs are tenant-scoped, expire after 1 h, and each tenant may hold at most 20 live
  jobs; beyond that the API answers 429 `{"detail": {"code": "JOB_LIMIT"}}`.
- `machine_id` resolves the working width; an unknown machine makes the job `failed`.
- The no-go zones of every tenant parcel intersecting the search box are respected;
  with `parcel_id`, that parcel's zones are added and its access point is the default origin.
- `min_turn_radius_m` is deprecated and ignored.
- Alternatives carry `max_slope_deg_found` and `blocked_cells_hit`; completed jobs carry `report`.

## Tests

The default run excludes the `slow` marker. The full guarantee matrix (480 cases,
with and without a gate) and a large-parcel regression time guard (< 120 s) run nightly
(`.github/workflows/nightly-slow.yml`) or on demand with `-m slow`.
