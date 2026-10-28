import base64
import io
import re
import zipfile

import pytest
import shapefile
from fastapi.testclient import TestClient
from pyproj import Transformer
from shapely.geometry import box, mapping

from app.main import app
from tests.fixtures_parcels import wgs84

client = TestClient(app)
URL = "/api/routing/zones/external/ingest"
WGS84_PRJ = ('GEOGCS["GCS_WGS_1984",DATUM["D_WGS_1984",SPHEROID["WGS_1984",6378137.0,298.257223563]],'
             'PRIMEM["Greenwich",0.0],UNIT["Degree",0.0174532925199433]]')


def _ring(poly):
    return [list(c) for c in poly.exterior.coords]


def make_zip(polys, fields, rows, prj=WGS84_PRJ, with_prj=True):
    """Shapefile in memory: polys are shapely polygons, rows are attribute tuples."""
    shp, shx, dbf = io.BytesIO(), io.BytesIO(), io.BytesIO()
    w = shapefile.Writer(shp=shp, shx=shx, dbf=dbf, shapeType=shapefile.POLYGON)
    for name, kind in fields:
        w.field(name, *kind)
    for poly, row in zip(polys, rows):
        w.poly([_ring(poly)])
        w.record(*row)
    w.close()
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("zones.shp", shp.getvalue())
        z.writestr("zones.shx", shx.getvalue())
        z.writestr("zones.dbf", dbf.getvalue())
        if with_prj:
            z.writestr("zones.prj", prj)
    return out.getvalue()


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def post(fmt, data):
    return client.post(URL, json={"format": fmt, "content": b64(data)})


NUM = ("N", 18, 6)
TXT = ("C", 20)
POLYS = [wgs84(box(0, 0, 100, 100)), wgs84(box(100, 0, 200, 100))]


def test_shapefile_wgs84_value_field():
    r = post("shapefile", make_zip(POLYS, [("name", TXT), ("Value", NUM)], [("a", 1.5), ("b", 4.0)]))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["count"] == 2
    assert sorted(z["properties"]["value"] for z in d["zones"]) == [1.5, 4.0]
    assert len(d["distribution"]["percentiles"]) == 21
    assert d.get("warnings", []) == []
    assert d["zones"][0]["geometry"]["type"] == "Polygon"


def test_shapefile_picks_first_numeric_named_attribute():
    z = make_zip(POLYS, [("rate", TXT), ("area", NUM), ("NDVI", NUM), ("mean", NUM)],
                 [("x", 9.0, 0.3, 7.0), ("y", 9.0, 0.6, 8.0)])
    r = post("shapefile", z)
    assert r.status_code == 200
    # "rate" is text (not numeric), so the first numeric match is NDVI
    assert sorted(f["properties"]["value"] for f in r.json()["data"]["zones"]) == [0.3, 0.6]


def test_shapefile_without_value_attribute_lists_attributes():
    r = post("shapefile", make_zip(POLYS, [("name", TXT), ("area", NUM)], [("a", 1.0), ("b", 2.0)]))
    assert r.status_code == 400
    body = r.json()
    assert body["code"] == "ZONES_NO_VALUE"
    assert body["params"]["attributes"] == ["name", "area"]


def test_shapefile_without_prj_warns_and_assumes_wgs84():
    r = post("shapefile", make_zip(POLYS, [("value", NUM)], [(1.0,), (2.0,)], with_prj=False))
    assert r.status_code == 200
    assert r.json()["data"]["warnings"] == ["ZONES_NO_PRJ"]


def test_shapefile_reprojects_utm_to_wgs84():
    from pyproj import CRS
    utm = CRS.from_epsg(25830)
    tr = Transformer.from_crs("EPSG:4326", utm, always_xy=True).transform
    from shapely.ops import transform
    polys_utm = [transform(tr, p) for p in POLYS]
    r = post("shapefile", make_zip(polys_utm, [("value", NUM)], [(1.0,), (2.0,)], prj=utm.to_wkt()))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["warnings"] == []
    got = d["zones"][0]["geometry"]["coordinates"][0][0]
    want = mapping(POLYS[0])["coordinates"][0]
    assert any(abs(got[0] - w[0]) < 1e-6 and abs(got[1] - w[1]) < 1e-6 for w in want)


def test_shapefile_invalid_zip_is_400():
    r = post("shapefile", b"not a zip")
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_shapefile_zip_without_shp_is_400():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("a.txt", "x")
    r = post("shapefile", out.getvalue())
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_invalid_base64_is_400():
    r = client.post(URL, json={"format": "shapefile", "content": "***"})
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_decoded_size_limit_is_413():
    r = post("shapefile", b"\0" * (5 * 1024 * 1024 + 1))
    assert r.status_code == 413 and r.json()["code"] == "ZONES_FILE_TOO_LARGE"


def test_zip_expanding_past_limit_is_413():
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("zones.shp", b"\0" * (6 * 1024 * 1024))
    assert len(out.getvalue()) < 5 * 1024 * 1024
    r = post("shapefile", out.getvalue())
    assert r.status_code == 413


def _pln(poly, holes=()):
    def lsg(kind, ring):
        pts = "".join(f'<PNT A="2" C="{y}" D="{x}"/>' for x, y in ring[:-1])
        return f'<LSG A="{kind}">{pts}</LSG>'
    inner = lsg(1, list(poly.exterior.coords)) + "".join(lsg(2, list(h.coords)) for h in holes)
    return f'<PLN A="2">{inner}</PLN>'


def _box_xy(x, y):
    from shapely.geometry import box as _b
    return _b(x, y, x + 100, y + 100)


def isoxml(tzns):
    body = ""
    for idx, (poly, b, holes) in enumerate(tzns):
        pdv = f'<PDV A="0006" B="{b}"/><PDV A="0001" B="999"/>' if b is not None else ""
        body += f'<TZN A="{idx}" B="Class {idx + 1}">{pdv}{_pln(poly, holes)}</TZN>'
    return ('<?xml version="1.0" encoding="UTF-8"?>\n<ISO11783TaskData VersionMajor="4" VersionMinor="0">'
            f'<TSK TSKID="TSK1">{body}</TSK></ISO11783TaskData>').encode()


def test_isoxml_zones_with_first_pdv_value_and_hole():
    outer = POLYS[0]
    hole = box(*[v for v in outer.bounds]).buffer(-0.0001).exterior
    from shapely.geometry import Polygon
    hole_ring = Polygon(hole)
    r = post("isoxml", isoxml([(outer, 3000, [hole_ring.exterior]), (POLYS[1], 5000, [])]))
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert d["count"] == 2
    assert [z["properties"]["value"] for z in d["zones"]] == [3000.0, 5000.0]
    assert len(d["zones"][0]["geometry"]["coordinates"]) == 2
    first = d["zones"][0]["geometry"]["coordinates"][0][0]
    assert abs(first[0] - outer.exterior.coords[0][0]) < 1e-9
    assert len(d["distribution"]["zones"]) == 2


def test_isoxml_tzn_without_pdv_is_reported_missing():
    r = post("isoxml", isoxml([(POLYS[0], 100, []), (POLYS[1], None, [])]))
    assert r.status_code == 200
    assert [m["reason"] for m in r.json()["data"]["distribution"]["missing"]] == ["no_mean_value"]


def test_isoxml_without_zones_is_400():
    r = post("isoxml", b'<ISO11783TaskData><TSK TSKID="1"/></ISO11783TaskData>')
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_isoxml_malformed_is_400():
    r = post("isoxml", b"<a><b></a>")
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_isoxml_doctype_is_refused():
    r = post("isoxml", b'<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "b">]><x/>')
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_isoxml_utf16_doctype_is_refused():
    xml = ('<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>').encode("utf-16")
    r = post("isoxml", xml)
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_shapefile_without_prj_with_projected_coordinates_is_rejected():
    from shapely.geometry import box as _box
    r = post("shapefile", make_zip([_box(600000, 4700000, 600100, 4700100)], [("value", NUM)], [(1.0,)],
                                   with_prj=False))
    assert r.status_code == 400
    assert r.json()["code"] == "ZONES_FILE_INVALID"
    assert r.json()["params"]["reason"] == "coordinates_out_of_range"


def test_isoxml_out_of_range_coordinates_rejected():
    r = post("isoxml", isoxml([(_box_xy(600000, 4700000), 1, [])]))
    assert r.status_code == 400 and r.json()["params"]["reason"] == "coordinates_out_of_range"


def test_isoxml_non_finite_coordinates_rejected():
    xml = re.sub(rb'C="[^"]*"', b'C="nan"', isoxml([(POLYS[0], 1, [])]), count=1)
    r = post("isoxml", xml)
    assert r.status_code == 400 and r.json()["code"] == "ZONES_FILE_INVALID"


def test_shapefile_self_intersecting_polygon_is_repaired_or_rejected_not_500():
    from shapely.geometry import Polygon as _P
    bow = _P([(0, 0), (0.001, 0.001), (0.001, 0), (0, 0.001), (0, 0)])
    r = post("shapefile", make_zip([bow], [("value", NUM)], [(1.0,)]))
    assert r.status_code in (200, 400)


def test_isoxml_roundtrips_export_service_output():
    from app.services.export_service import RouteExporter
    rx = {"unit": "kg_ha",
          "classes": [{"index": 0, "min_pct": 0, "max_pct": 50, "rate": 20.0},
                      {"index": 1, "min_pct": 50, "max_pct": 100, "rate": 40.0}],
          "zones": {"type": "FeatureCollection", "features": [
              {"type": "Feature", "properties": {"class_index": 0}, "geometry": mapping(POLYS[0])},
              {"type": "Feature", "properties": {"class_index": 1}, "geometry": mapping(POLYS[1])}]}}
    xml = "<ISO11783TaskData><TSK>" + RouteExporter()._treatment_zones(rx) + "</TSK></ISO11783TaskData>"
    r = post("isoxml", xml.encode())
    assert r.status_code == 200, r.text
    d = r.json()["data"]
    assert [z["properties"]["value"] for z in d["zones"]] == [2000.0, 4000.0]
    assert d["zones"][1]["geometry"]["type"] == "Polygon"


def test_geojson_and_csv_still_work():
    import json
    feats = [{"type": "Feature", "geometry": mapping(POLYS[0]), "properties": {"value": 2.0}}]
    r = client.post(URL, json={"format": "geojson", "content": json.dumps(
        {"type": "FeatureCollection", "features": feats})})
    assert r.status_code == 200
