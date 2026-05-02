# GIS Routing & VRA

Precision agriculture guidance module for the Nekazari platform. Generates A-B guidance lines with terrain slope correction, VRA prescription maps, and ISOBUS-compatible export for autonomous tractors.

## Features

- **A-B Line Routing** — Dynamic UTM projection with parallel swath generation clipped to field boundaries
- **DEM Slope Correction** — Terrain-aware swath spacing via CNIG (Spain) / Copernicus (Europe) elevation data
- **VRA Prescription Maps** — Swath-to-zone intersection with per-segment application rates
- **Multi-format Export** — ISOXML 11783-10 (ISOBUS), GeoJSON, GPX
- **Offline Maps** — PMTiles generation with MinIO cache for disconnected field operation
- **Mobile Sync** — WatermelonDB delta pull/push protocol for offline-first mobile apps
- **Equipment Kinematics** — Full steering model: Ackermann, differential, articulated. 3D GPS offset compensation. Trailer/implement tracking
- **6 Languages** — Catalan, English, Spanish, Basque, French, Portuguese

## Architecture

```
nkz-mobile (WatermelonDB) ←→ GET/POST /api/routing/sync
Frontend (IIFE bundle)    ←→ /modules/nkz-module-gis-routing/nkz-module.js
                              ↓
                         FastAPI Backend
                    ┌────────┼────────┐
                    ↓        ↓        ↓
               Orion-LD  TimescaleDB  MinIO
                         (cache)
```

## API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/api/routing/sync` | WatermelonDB pull (delta sync) |
| `POST` | `/api/routing/sync` | WatermelonDB push (conflict detection) |
| `POST` | `/api/routing/generate` | Generate A-B swaths |
| `POST` | `/api/routing/generate/with-vra` | Generate swaths with VRA prescription intersection |
| `GET` | `/api/routing/export/{id}` | Export operation (isoxml, geojson, gpx) |
| `GET` | `/api/routing/tiles` | Download offline PMTiles basemap |
| `GET` | `/api/routing/zones/{id}` | Fetch AgriManagementZone for a parcel |
| `POST` | `/api/routing/zones/{id}/generate` | Trigger VRA zone generation |
| `GET` | `/health` | Health check (no auth) |

## Deployment

```bash
# Build frontend
npm install && npm run build:module

# Upload to MinIO
mc cp dist/nkz-module.js minio/nekazari-frontend/modules/nkz-module-gis-routing/nkz-module.js

# Docker build
cd backend && docker build -t ghcr.io/nkz-os/nkz-module-gis-routing/nkz-module-gis-routing-backend:latest .

# Register in marketplace (once per environment)
kubectl exec -n nekazari deployment/postgresql -- psql -U postgres -d nekazari -f k8s/registration.sql

# Deploy
kubectl apply -f k8s/backend-deployment.yaml -n nekazari
```

## Dependencies

- **eu-elevation** — DEM slope correction (server-to-server, non-blocking)
- **vegetation-health** — VRA zone generation proxy (server-to-server, non-blocking)
- Orion-LD Context Broker
- TimescaleDB + PostGIS
- MinIO (IIFE bundle + PMTiles cache)

## License

AGPL-3.0 — Powered by [robotika.cloud](https://robotika.cloud/)
