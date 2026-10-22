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
