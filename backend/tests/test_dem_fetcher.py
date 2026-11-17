"""eu-elevation /raster -> internal DemGrid (row 0 = south). Synthetic payloads only."""
import logging

import pytest
import respx
from httpx import Response

from app.services.pathfinding.dem_fetcher import dem_secret_configured, fetch_dem_raster

URL = "http://dem"
BBOX = (-1.0, 42.0, -0.997, 42.003)


def _payload(**over):
    p = {
        "elevations": [[30.0, 31.0], [20.0, 21.0], [10.0, 11.0]],  # north first
        "origin_lon": -1.0, "origin_lat": 42.0, "north_lat": 42.003,
        "row_order": "north_first", "pixel_size_deg": 0.0015,
        "cols": 2, "rows": 3, "nodata_count": 0,
        "source": {"id": "builtin:XX", "category": "custom_wcs:XX", "resolution_m": 25.0,
                   "fallback_reason": None},
    }
    p.update(over)
    return p


@pytest.fixture(autouse=True)
def _secret(monkeypatch):
    monkeypatch.setenv("INTERNAL_SERVICE_SECRET", "s3cret")


@respx.mock
async def test_sends_secret_and_nodata_null():
    route = respx.get(f"{URL}/raster").mock(return_value=Response(200, json=_payload()))
    await fetch_dem_raster(URL, BBOX, 10)
    req = route.calls.last.request
    assert req.headers["X-Internal-Service-Secret"] == "s3cret"
    assert req.url.params["nodata"] == "null"
    assert float(req.url.params["resolution_m"]) == 10


@respx.mock
async def test_rows_reordered_south_first():
    respx.get(f"{URL}/raster").mock(return_value=Response(200, json=_payload()))
    grid = await fetch_dem_raster(URL, BBOX, 10)
    assert grid["elevations"] == [[10.0, 11.0], [20.0, 21.0], [30.0, 31.0]]
    assert grid["origin_lat"] == 42.0
    assert grid["pixel_size_deg"] == 0.0015
    assert grid["pixel_height_deg"] == pytest.approx(0.001)
    assert grid["rows"] == 3 and grid["cols"] == 2
    assert grid["source"]["resolution_m"] == 25.0


@respx.mock
async def test_null_cells_kept_as_none():
    respx.get(f"{URL}/raster").mock(return_value=Response(200, json=_payload(
        elevations=[[None, 31.0], [20.0, 21.0], [10.0, 11.0]], nodata_count=1)))
    grid = await fetch_dem_raster(URL, BBOX, 10)
    assert grid["elevations"][2] == [None, 31.0]


@respx.mock
async def test_missing_source_becomes_empty_dict():
    p = _payload()
    del p["source"]
    respx.get(f"{URL}/raster").mock(return_value=Response(200, json=p))
    grid = await fetch_dem_raster(URL, BBOX, 10)
    assert grid["source"] == {}


@pytest.mark.parametrize("over, reason", [
    ({"row_order": None}, "row_order"),
    ({"row_order": "south_first"}, "row_order"),
    ({"north_lat": None}, "north_lat"),
    ({"rows": 4}, "shape"),
    ({"elevations": [[30.0, 31.0], [20.0], [10.0, 11.0]]}, "shape"),
])
@respx.mock
async def test_unexpected_layout_rejected(over, reason, caplog):
    p = _payload(**over)
    p = {k: v for k, v in p.items() if v is not None}
    respx.get(f"{URL}/raster").mock(return_value=Response(200, json=p))
    with caplog.at_level(logging.ERROR):
        assert await fetch_dem_raster(URL, BBOX, 10) is None
    assert reason in caplog.text


@respx.mock
async def test_all_null_returns_none():
    respx.get(f"{URL}/raster").mock(return_value=Response(200, json=_payload(
        elevations=[[None, None]] * 3, nodata_count=6)))
    assert await fetch_dem_raster(URL, BBOX, 10) is None


@respx.mock
async def test_no_secret_skips_call(monkeypatch):
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET")
    route = respx.get(f"{URL}/raster").mock(return_value=Response(200, json=_payload()))
    assert dem_secret_configured() is False
    assert await fetch_dem_raster(URL, BBOX, 10) is None
    assert not route.called


@pytest.mark.parametrize("status", [401, 503])
@respx.mock
async def test_non_200_returns_none(status, caplog):
    respx.get(f"{URL}/raster").mock(return_value=Response(status, json={"detail": "x"}))
    with caplog.at_level(logging.WARNING):
        assert await fetch_dem_raster(URL, BBOX, 10) is None
    assert str(status) in caplog.text
    assert "s3cret" not in caplog.text


def test_secret_configured_true():
    assert dem_secret_configured() is True


def test_startup_check_logs_critical_without_secret(monkeypatch, caplog):
    from app.main import check_dem_secret
    monkeypatch.delenv("INTERNAL_SERVICE_SECRET")
    with caplog.at_level(logging.CRITICAL):
        check_dem_secret()
    assert "INTERNAL_SERVICE_SECRET not set: terrain (DEM) disabled" in caplog.text


def test_startup_check_silent_with_secret(caplog):
    from app.main import check_dem_secret
    with caplog.at_level(logging.CRITICAL):
        check_dem_secret()
    assert caplog.text == ""
