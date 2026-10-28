"""Parsers for external management-zone files: shapefile (zip) and ISOXML TZN.

Both return ``(features, warnings)`` with WGS84 GeoJSON features whose
properties carry ``zone_id`` and, when known, ``value``. Failures are coded
``PlanError``s so the client can localise them.
"""
from __future__ import annotations

import base64
import binascii
import io
import math
import re
import zipfile
from xml.etree import ElementTree as ET

from pyproj import CRS, Transformer
from shapely.geometry import MultiPolygon, Polygon, mapping, shape
from shapely.ops import transform

from app.services.coverage.errors import PlanError

MAX_BYTES = 5 * 1024 * 1024
VALUE_FIELDS = ("value", "mean", "ndvi", "rate")
WARN_NO_PRJ = "ZONES_NO_PRJ"


def _invalid(detail: str, **params) -> PlanError:
    return PlanError("ZONES_FILE_INVALID", detail, params)


def _too_large() -> PlanError:
    return PlanError("ZONES_FILE_TOO_LARGE", "file exceeds 5 MB", {"max_bytes": MAX_BYTES})


def decode_content(content: str) -> bytes:
    text = re.sub(r"\s+", "", content or "")
    if len(text) // 4 * 3 - 2 > MAX_BYTES:
        raise _too_large()
    try:
        data = base64.b64decode(text, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _invalid("content is not valid base64") from exc
    if len(data) > MAX_BYTES:
        raise _too_large()
    return data


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def parse_shapefile(data: bytes) -> tuple[list[dict], list[str]]:
    import shapefile

    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise _invalid("not a zip archive") from exc
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir() and "__MACOSX" not in i.filename]
        if sum(i.file_size for i in infos) > MAX_BYTES:
            raise _too_large()
        by_ext: dict[str, zipfile.ZipInfo] = {}
        for i in infos:
            ext = i.filename.rsplit(".", 1)[-1].lower() if "." in i.filename else ""
            by_ext.setdefault(ext, i)
        if "shp" not in by_ext or "dbf" not in by_ext:
            raise _invalid("zip needs .shp and .dbf files")
        shp = io.BytesIO(zf.read(by_ext["shp"]))
        dbf = io.BytesIO(zf.read(by_ext["dbf"]))
        shx = io.BytesIO(zf.read(by_ext["shx"])) if "shx" in by_ext else None
        prj = zf.read(by_ext["prj"]).decode("utf-8", "replace") if "prj" in by_ext else None

    warnings: list[str] = []
    project = None
    if prj is None or not prj.strip():
        warnings.append(WARN_NO_PRJ)
    else:
        try:
            crs = CRS.from_wkt(prj)
        except Exception as exc:
            raise _invalid("unreadable .prj projection") from exc
        if crs.to_epsg() != 4326:
            project = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform

    try:
        reader = shapefile.Reader(shp=shp, dbf=dbf, shx=shx)
        names = [f[0] for f in reader.fields[1:]]
        records = reader.shapeRecords()
    except Exception as exc:
        raise _invalid("unreadable shapefile") from exc

    wanted = {n.lower() for n in VALUE_FIELDS}
    candidates = [n for n in names if n.lower() in wanted]
    value_field = next(
        (n for n in candidates if any(_is_number(sr.record.as_dict().get(n)) for sr in records)), None)
    if value_field is None:
        raise PlanError("ZONES_NO_VALUE", "no numeric value|mean|ndvi|rate attribute", {"attributes": names})
    id_field = next((n for n in names if n.lower() in ("zone_id", "zoneid")), None)

    feats: list[dict] = []
    for idx, sr in enumerate(records):
        geom = sr.shape.__geo_interface__ if sr.shape.shapeType else None
        if not geom or geom.get("type") not in ("Polygon", "MultiPolygon"):
            continue
        try:
            g = shape(geom)
            if project is not None:
                g = transform(project, g)
        except Exception as exc:
            raise _invalid("invalid geometry", record=idx + 1) from exc
        if g.is_empty:
            continue
        rec = sr.record.as_dict()
        props: dict = {"zone_id": str(rec.get(id_field)) if id_field and rec.get(id_field) is not None
                       else f"shp-{idx + 1}"}
        if _is_number(rec.get(value_field)):
            props["value"] = float(rec[value_field])
        feats.append({"type": "Feature", "geometry": mapping(g), "properties": props})
    if not feats:
        raise _invalid("no polygon records")
    return feats, warnings


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _ring(lsg: ET.Element) -> list[tuple[float, float]]:
    pts = []
    for pnt in lsg:
        if _local(pnt.tag) != "PNT":
            continue
        try:
            pts.append((float(pnt.get("D")), float(pnt.get("C"))))
        except (TypeError, ValueError) as exc:
            raise _invalid("invalid PNT coordinates") from exc
    return pts


def parse_isoxml(data: bytes) -> tuple[list[dict], list[str]]:
    head = data[:4096].upper()
    if b"<!DOCTYPE" in head or b"<!ENTITY" in data.upper():
        raise _invalid("DTD and entities are not allowed")
    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        raise _invalid("malformed XML") from exc

    feats: list[dict] = []
    for idx, tzn in enumerate(e for e in root.iter() if _local(e.tag) == "TZN"):
        polys = []
        for pln in (c for c in tzn if _local(c.tag) == "PLN"):
            rings = [(c.get("A"), _ring(c)) for c in pln if _local(c.tag) == "LSG"]
            ext = next((r for kind, r in rings if kind == "1"), None)
            if ext is None or len(ext) < 3:
                continue
            holes = [r for kind, r in rings if kind == "2" and len(r) >= 3]
            poly = Polygon(ext, holes)
            if not poly.is_empty:
                polys.append(poly)
        if not polys:
            continue
        geom = polys[0] if len(polys) == 1 else MultiPolygon(polys)
        props: dict = {"zone_id": f"TZN{tzn.get('A')}" if tzn.get("A") is not None else f"tzn-{idx + 1}"}
        pdv = next((c for c in tzn if _local(c.tag) == "PDV"), None)
        if pdv is not None:
            try:
                v = float(pdv.get("B"))
                if math.isfinite(v):
                    props["value"] = v
            except (TypeError, ValueError):
                pass
        feats.append({"type": "Feature", "geometry": mapping(geom), "properties": props})
    if not feats:
        raise _invalid("no TZN treatment zones with polygons")
    return feats, []
