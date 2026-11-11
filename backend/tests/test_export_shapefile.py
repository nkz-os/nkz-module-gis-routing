import io
import json
import zipfile

import pytest
import shapefile

from app.services.coverage.errors import PlanError
from app.services.export_service import RouteExporter

SQ = [[-1.0, 42.0], [-1.0, 42.001], [-0.999, 42.001], [-0.999, 42.0], [-1.0, 42.0]]
HOLE = [[-0.9995, 42.0003], [-0.9995, 42.0006], [-0.9992, 42.0006], [-0.9992, 42.0003], [-0.9995, 42.0003]]
FAR = [[-0.99, 42.0], [-0.99, 42.001], [-0.989, 42.001], [-0.99, 42.0]]


def _rx(unit="kg_ha"):
    return {
        "unit": unit,
        "product": "NAC 27",
        "classes": [
            {"index": 0, "zone_id": "z1", "label": "Zone A", "rate": 240.5},
            {"index": 1, "zone_id": "z2", "label": "Zone B", "rate": 0},
            {"index": 2, "zone_id": None, "rest": True, "label": "Rest of parcel", "rate": 222.2},
        ],
        "zones": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"class_index": 0, "rate": 240.5, "zone_id": "z1", "label": "Zone A"},
             "geometry": {"type": "MultiPolygon", "coordinates": [[SQ, HOLE], [FAR]]}},
            {"type": "Feature", "properties": {"class_index": 1, "rate": 0, "zone_id": "z2", "label": "Zone B"},
             "geometry": {"type": "Polygon", "coordinates": [FAR]}},
            {"type": "Feature", "properties": {"class_index": 2, "rate": 222.2, "label": "Rest of parcel"},
             "geometry": {"type": "Polygon", "coordinates": [SQ]}},
        ]},
    }


def _op(rx):
    return {"id": "urn:x", "operation_type": "spraying", "ab_line_geojson": "{}", "prescription": rx}


def _read(content):
    zf = zipfile.ZipFile(io.BytesIO(content))
    d = {n: zf.read(n) for n in zf.namelist()}
    r = shapefile.Reader(shp=io.BytesIO(d["prescription.shp"]), shx=io.BytesIO(d["prescription.shx"]),
                         dbf=io.BytesIO(d["prescription.dbf"]), encoding="utf-8")
    return d, r


def test_zip_contents_and_records():
    d, r = _read(RouteExporter().to_shapefile(_op(_rx())))
    assert sorted(d) == ["prescription.dbf", "prescription.prj", "prescription.shp", "prescription.shx"]
    assert b"GCS_WGS_1984" in d["prescription.prj"]
    assert [f[0] for f in r.fields[1:]] == ["zone", "rate", "unit", "product"]
    assert len(r) == 3
    recs = [tuple(rec) for rec in r.records()]
    assert recs == [("Zone A", 240.5, "kg/ha", "NAC 27"), ("Zone B", 0.0, "kg/ha", "NAC 27"),
                    ("Rest of parcel", 222.2, "kg/ha", "NAC 27")]


def test_geometries_roundtrip_and_orientation():
    from shapely.geometry import shape
    _, r = _read(RouteExporter().to_shapefile(_op(_rx())))
    shapes = r.shapes()
    assert all(s.shapeType == shapefile.POLYGON for s in shapes)
    g0 = shape(shapes[0].__geo_interface__)
    assert g0.geom_type == "MultiPolygon" and len(g0.geoms) == 2
    assert g0.area == pytest.approx(
        shape({"type": "Polygon", "coordinates": [SQ, HOLE]}).area + shape({"type": "Polygon", "coordinates": [FAR]}).area)
    # Shapefile spec: exterior rings clockwise (negative shoelace sum)
    pts = shapes[2].points
    area2 = sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]))
    assert area2 < 0
    assert shapes[2].bbox == pytest.approx([-1.0, 42.0, -0.999, 42.001])


def test_liquid_unit_and_json_string_prescription():
    rx = _rx("l_ha")
    _, r = _read(RouteExporter().to_shapefile(_op(json.dumps(rx))))
    assert r.record(0)["unit"] == "L/ha"


def test_zones_as_json_string():
    rx = _rx()
    rx["zones"] = json.dumps(rx["zones"])
    _, r = _read(RouteExporter().to_shapefile(_op(rx)))
    assert len(r) == 3


@pytest.mark.parametrize("rx", [None, "", "null"])
def test_no_prescription_is_export_empty(rx):
    with pytest.raises(PlanError) as e:
        RouteExporter().to_shapefile(_op(rx))
    assert e.value.code == "EXPORT_EMPTY"


@pytest.mark.parametrize("mutate", [
    lambda rx: rx.update(unit="bushels"),
    lambda rx: rx["classes"][0].update(rate=-1),
    lambda rx: rx["zones"]["features"][0]["properties"].update(class_index=9),
    lambda rx: rx.update(zones={"features": "x"}),
])
def test_invalid_prescription_is_invalid_vra(mutate):
    rx = _rx()
    mutate(rx)
    with pytest.raises(PlanError) as e:
        RouteExporter().to_shapefile(_op(rx))
    assert e.value.code == "INVALID_VRA"


def test_long_non_ascii_text_is_cut_safely():
    rx = _rx()
    rx["product"] = "ñ" * 200
    _, r = _read(RouteExporter().to_shapefile(_op(rx)))
    assert set(r.record(0)["product"]) == {"ñ"}


# -- route -----------------------------------------------------------------

def _entity(rx, op_type="spraying"):
    return {
        "id": "urn:ngsi-ld:AgriParcelOperation:t:op1",
        "name": {"value": "n"},
        "operationType": {"value": op_type},
        "implementWidth": {"value": 20},
        "location": {"value": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]}},
        "prescription": {"type": "Property", "value": rx} if rx is not None else None,
    }


class _Orion:
    tenants = []

    def __init__(self, tenant, ent):
        self.tenants.append(tenant)
        self.ent = ent

    async def get_entity(self, *a, **k):
        return self.ent

    async def close(self):
        pass


def _client(monkeypatch, ent):
    from fastapi.testclient import TestClient
    from app.main import create_app
    _Orion.tenants = []
    monkeypatch.setattr("app.api.routing.OrionClient", lambda tenant, *a, **k: _Orion(tenant, ent))
    return TestClient(create_app())


def test_route_returns_zip(monkeypatch):
    c = _client(monkeypatch, _entity(_rx()))
    r = c.get("/api/routing/export/urn:ngsi-ld:AgriParcelOperation:t:op1?format=shapefile")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    assert r.headers["content-disposition"] == 'attachment; filename="op1-prescription.zip"'
    assert len(shapefile.Reader(shp=io.BytesIO(zipfile.ZipFile(io.BytesIO(r.content)).read("prescription.shp")),
                                shx=io.BytesIO(zipfile.ZipFile(io.BytesIO(r.content)).read("prescription.shx")),
                                dbf=io.BytesIO(zipfile.ZipFile(io.BytesIO(r.content)).read("prescription.dbf")))) == 3


def test_route_reads_operation_in_callers_tenant(monkeypatch):
    c = _client(monkeypatch, _entity(_rx()))
    c.get("/api/routing/export/op1?format=shapefile")
    c.get("/api/routing/export/op1?format=shapefile", headers={"X-Tenant-ID": "tenant-b"})
    assert _Orion.tenants == ["tenant-a", "tenant-b"]


def test_route_unknown_operation_404(monkeypatch):
    c = _client(monkeypatch, None)
    assert c.get("/api/routing/export/op1?format=shapefile").status_code == 404


def test_route_requires_identity(monkeypatch):
    c = _client(monkeypatch, _entity(_rx()))
    r = c.get("/api/routing/export/op1?format=shapefile", headers={"X-Tenant-ID": ""})
    assert r.status_code in (400, 401, 403)


def test_route_transit_422_like_isoxml(monkeypatch):
    c = _client(monkeypatch, _entity(_rx(), "transit"))
    r = c.get("/api/routing/export/op1?format=shapefile")
    assert r.status_code == 422 and r.json()["code"] == "EXPORT_NOT_SUPPORTED"


def test_route_no_prescription_422(monkeypatch):
    c = _client(monkeypatch, _entity(None))
    r = c.get("/api/routing/export/op1?format=shapefile")
    assert r.status_code == 422 and r.json()["code"] == "EXPORT_EMPTY"


def test_route_invalid_prescription_422(monkeypatch):
    c = _client(monkeypatch, _entity([1]))
    r = c.get("/api/routing/export/op1?format=shapefile")
    assert r.status_code == 422 and r.json()["code"] == "INVALID_VRA"
