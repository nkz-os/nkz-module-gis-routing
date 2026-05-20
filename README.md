# GIS Routing & VRA

Precision agriculture guidance module for the Nekazari platform. Interactive route wizard with live SVG preview, multi-strategy A-B guidance lines, VRA prescription maps, least-cost A-B pathfinding on Cesium, and ISOBUS export for autonomous tractors.

## Features

**Routing Wizard**
- 5-step wizard with progressive disclosure (Parcel → Equipment → Pattern → VRA → Save)
- Real-time SVG preview with hover/click line highlighting and legend
- Headland passes composition (perimeter + internal swaths in a single plan)
- Pattern persistence: save, load, delete, and compare saved routes (sorted by date)
- Cross-tab "View in Cesium" via sessionStorage
- 2-column responsive layout (config | preview + results)

**Pattern Strategies**
- **AB-Line** — parallel swaths at configurable heading
- **AB-Skip** — alternating skip-row pattern for seeding
- **Spiral** — concentric inward/outward rings for harvesting
- **Headland** — perimeter passes with configurable count

**Pathfinding**
- A-B point picker directly on the Cesium 3D map (unified viewer)
- Cesium terrain sampling (`sampleTerrainMostDetailed`) for DEM grid — no backend dependency
- A* least-cost pathfinding with 3 weighted alternatives
- Auto-cancel on entity change, visual markers (green A / red B)
- Pathfinding results visible in both module SVG and Cesium map

**Viewer Integration**
- Context panel: saved routes list with click-to-visualize on Cesium
- Pick mode cancels automatically when changing entity selection
- Cross-tab route visualization from module page

**VRA Prescription**
- Auto-fetch vegetation-health zones per parcel
- Swath-to-zone intersection with per-segment application rates
- External file upload (GeoJSON/CSV)
- Prescription summary with segments, zones, total length, average rate

**Export & Handoff**
- ISOXML 11783-10 (ISOBUS), GeoJSON, GPX export
- Mobile handoff: copy operation ID → NKZ Mobile → sync → execute
- WatermelonDB delta pull/push for offline-first mobile apps

**Internationalization**
- 6 languages: Catalan, English, Spanish, Basque, French, Portuguese

## Architecture

```
nkz-mobile (WatermelonDB) ←→ GET/POST /api/routing/sync
Web UI (Module Federation 2.0 remote)
  ├── Module page (/gis-routing) — routing wizard + SVG preview
  └── Viewer slots
       ├── GisRoutingMapLayer — swath/VRA/pathfinding rendering on Cesium
       └── ContextPanelSlot — saved routes + pathfinding pick mode
                              ↓
                         FastAPI Backend
                    ┌────────┼────────┐
                    ↓        ↓        ↓
               Orion-LD  TimescaleDB  MinIO
                         (patterns)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/api/routing/generate` | Generate routing plan (all patterns, optional VRA, headland composition) |
| `GET`  | `/api/routing/parcels` | List available parcels |
| `GET`  | `/api/routing/parcels/{id}/geometry` | Get parcel geometry |
| `GET`  | `/api/routing/equipment` | List equipment (tractors/implements) |
| `POST` | `/api/routing/path/calculate` | Submit pathfinding job (A-B, async) |
| `GET`  | `/api/routing/path/{job_id}` | Poll pathfinding result (3 alternatives) |
| `GET`  | `/api/routing/patterns?parcel_id=X` | List saved patterns for a parcel |
| `GET`  | `/api/routing/patterns/{id}` | Get single pattern |
| `POST` | `/api/routing/patterns` | Save pattern |
| `DELETE` | `/api/routing/patterns/{id}` | Soft-delete pattern |
| `GET`  | `/api/routing/zones/{id}` | Fetch AgriManagementZone for a parcel |
| `POST` | `/api/routing/zones/external/ingest` | Upload external VRA zones (GeoJSON/CSV) |
| `GET`  | `/api/routing/export/{id}` | Export operation (isoxml, geojson, gpx) |
| `GET`  | `/api/routing/operations?limit=` | List saved operations |
| `POST` | `/api/routing/operations/session/start` | Start field session |
| `POST` | `/api/routing/operations/session/close` | Close field session |
| `GET`  | `/api/routing/operations/active` | Get active operation |
| `GET`  | `/api/routing/operations/coverage/{id}` | Get operation coverage |
| `GET`  | `/api/routing/sync` | WatermelonDB pull (delta sync) |
| `POST` | `/api/routing/sync` | WatermelonDB push (conflict detection) |
| `GET`  | `/health` | Health check (no auth) |

## Development

```bash
pnpm install
pnpm dev          # Vite dev server at localhost:5003
pnpm build        # Module Federation 2.0 build → dist/
pnpm typecheck    # TypeScript check
```

## Deployment

```bash
# Build
pnpm build

# Upload entire dist/ to MinIO
mc cp --recursive dist/ minio-srv/nekazari-frontend/modules/nkz-module-gis-routing/

# Backend
cd backend && docker build -t ghcr.io/nkz-os/nkz-module-gis-routing/backend:latest .
docker push ghcr.io/nkz-os/nkz-module-gis-routing/backend:latest

# Register in marketplace (once per environment)
kubectl exec -n nekazari deployment/postgresql -- psql -U postgres -d nekazari -f k8s/registration.sql
```

## Dependencies

- **eu-elevation** — DEM elevation data for pathfinding + slope correction
- **vegetation-health** — VRA zone generation proxy (server-to-server)
- Orion-LD Context Broker
- TimescaleDB + PostGIS
- MinIO (module artifacts)

## License

AGPL-3.0 — Powered by [robotika.cloud](https://robotika.cloud/)
