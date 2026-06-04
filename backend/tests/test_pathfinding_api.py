import asyncio
import time
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)


def _grid():
    # Flat 11x11 grid -> both objectives reach B; routes well-defined.
    return {
        "elevations": [[0.0] * 11 for _ in range(11)],
        "origin_lon": -2.0,
        "origin_lat": 43.0,
        "pixel_size_deg": 0.001,
    }


def test_calculate_returns_two_objectives():
    resp = client.post("/api/routing/path/calculate", json={
        "point_a": [-2.0, 43.0],
        "point_b": [-1.99, 43.0],
        "elevation_grid": _grid(),
    })
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    for _ in range(50):
        r = client.get(f"/api/routing/path/{job_id}")
        body = r.json()
        if body["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)

    assert body["status"] == "completed", body
    ids = {a["id"] for a in body["alternatives"]}
    assert ids == {"least_slope", "fastest"}


def test_build_dem_registry_uses_settings_eu_url(monkeypatch):
    from app.api import pathfinding_router as pr

    class _S:
        eu_elevation_url = "http://eu-elev:8000"

    monkeypatch.setattr(pr, "get_settings", lambda: _S())
    reg = pr.build_dem_registry()
    assert asyncio.iscoroutinefunction(reg.fetch_best)
    assert any(p.name == "eu-elevation" and p.covers((-1.7, 42.7, -1.6, 42.9))
               for p in reg._providers)
