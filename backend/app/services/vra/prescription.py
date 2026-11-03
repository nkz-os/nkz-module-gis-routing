"""Class-based VRA prescription: class polygons and per-swath rate segments (pure)."""
from __future__ import annotations

import math

from shapely import make_valid
from shapely.geometry import LineString, MultiPolygon, Polygon, mapping
from shapely.ops import transform as shp_transform, unary_union

from app.services.coverage.errors import PlanError
from app.services.vra.classify import ZoneValue, assign_by_position, valid_zones

UNITS = ("kg_ha", "l_ha")
_MIN_LEN_M = 1e-6
_PCT_TOL = 1e-6


def _bad(detail: str, **params) -> PlanError:
    return PlanError("INVALID_VRA", detail, params)


def _num(c: dict, key: str, i: int) -> float:
    v = c.get(key) if isinstance(c, dict) else None
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        raise _bad("Class field missing or not a number", index=i, field=key)
    return float(v)


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, abs_tol=_PCT_TOL)


def _validate(classes: list[dict], unit: str, zones: list[ZoneValue]) -> None:
    n = len(classes)
    if not 2 <= n <= 5:
        raise _bad("VRA needs 2 to 5 classes", count=n)
    if unit not in UNITS:
        raise _bad("Unsupported VRA unit", unit=unit)
    for i, c in enumerate(classes):
        for key in ("min_pct", "max_pct", "rate"):
            _num(c, key, i)
    if not _close(classes[0]["min_pct"], 0) or not _close(classes[-1]["max_pct"], 100):
        raise _bad("Classes must cover 0 to 100 percent")
    for i, c in enumerate(classes):
        if not c["min_pct"] < c["max_pct"] or _close(c["min_pct"], c["max_pct"]):
            raise _bad("Class range must be increasing", index=i)
        if i + 1 < n and not _close(c["max_pct"], classes[i + 1]["min_pct"]):
            raise _bad("Classes must be contiguous", index=i)
        if c["rate"] < 0:
            raise _bad("Rate must be zero or positive", index=i)
    if not valid_zones(zones):
        raise _bad("No zone has a value")


def _polygonal(geom):
    """Repair and keep only the polygonal part (Polygon | MultiPolygon) or None."""
    if geom is None or geom.is_empty:
        return None
    if not geom.is_valid:
        geom = make_valid(geom)
    if isinstance(geom, (Polygon, MultiPolygon)):
        parts = [geom]
    elif hasattr(geom, "geoms"):
        parts = [p for g in geom.geoms for p in _flat_polys(g)]
        return _polygonal(unary_union(parts)) if parts else None
    else:
        return None
    return geom if not geom.is_empty else None


def _flat_polys(g):
    if isinstance(g, (Polygon, MultiPolygon)):
        return [g]
    if hasattr(g, "geoms"):
        return [p for x in g.geoms for p in _flat_polys(x)]
    return []


def _lines(geom) -> list[LineString]:
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if hasattr(geom, "geoms"):
        return [p for g in geom.geoms for p in _lines(g)]
    return []  # points / polygons from touching geometries carry no length


def build_prescription(*, zones, classes, unit, product, invert, swaths_utm,
                       parcel_utm, to_utm, to_wgs) -> dict:
    _validate(classes, unit, zones)
    n = len(classes)
    warnings: list[dict] = []

    # Repair zone geometry in UTM; zones with nothing polygonal are skipped.
    usable: list[ZoneValue] = []
    zone_utm: list = []
    for z in valid_zones(zones):
        g = _polygonal(shp_transform(to_utm, z.geometry))
        if g is None:
            warnings.append({"code": "VRA_ZONE_INVALID", "params": {"zone_id": z.id}})
            continue
        usable.append(z)
        zone_utm.append(g)
    parcel = _polygonal(parcel_utm)
    if parcel is None:
        raise _bad("Parcel geometry is not usable")

    assigned = assign_by_position(usable, classes)
    if usable and len({z.mean for z in usable}) == 1:
        warnings.append({"code": "VRA_DEGENERATE", "params": {}})

    rates = [float(c["rate"]) for c in classes]
    if invert:
        rates = rates[::-1]

    # Class polygons in UTM, lower index wins overlaps, clipped to the parcel.
    groups = [[zone_utm[i] for i, c in assigned.items() if c == k] for k in range(n)]
    polys = _exclusive_polys(groups, parcel)
    meta = [{"min_pct": c["min_pct"], "max_pct": c["max_pct"]} for c in classes]
    return _render(meta, polys, rates, unit=unit, product=product, swaths_utm=swaths_utm,
                   to_wgs=to_wgs, warnings=warnings)


def _exclusive_polys(groups: list[list], parcel) -> list:
    """One polygon per group, clipped to the parcel; earlier groups win overlaps."""
    taken = None
    polys = []
    for members in groups:
        g = _polygonal(unary_union(members).intersection(parcel)) if members else None
        if g is not None and taken is not None:
            g = _polygonal(g.difference(taken))
        if g is not None:
            taken = g if taken is None else _polygonal(unary_union([taken, g]))
        polys.append(g)
    return polys


def _render(meta: list[dict], polys: list, rates: list[float], *, unit, product, swaths_utm,
            to_wgs, warnings: list[dict]) -> dict:
    n = len(polys)
    class_rows, zone_feats = [], []
    for k in range(n):
        g = polys[k]
        area_ha = g.area / 10000.0 if g is not None else 0.0
        class_rows.append({
            "index": k, **meta[k],
            "rate": rates[k], "area_ha": round(area_ha, 2),
            "product_total": round(area_ha * rates[k], 2),
        })
        if g is not None:
            props = {"class_index": k, "rate": rates[k]}
            if "zone_id" in meta[k]:
                props.update(zone_id=meta[k]["zone_id"], label=meta[k]["label"])
            zone_feats.append({
                "type": "Feature",
                "geometry": mapping(shp_transform(to_wgs, g)),
                "properties": props,
            })

    seg_feats, uncovered = [], 0.0
    for sw in swaths_utm:
        rest = sw.geometry
        for k in range(n):
            g = polys[k]
            if g is None:
                continue
            for part in _lines(sw.geometry.intersection(g)):
                if part.length <= _MIN_LEN_M:
                    continue
                seg_feats.append(_seg(sw.index, k, rates[k], part, to_wgs))
            rest = rest.difference(g)
        for part in _lines(rest):
            if part.length <= _MIN_LEN_M:
                continue
            uncovered += part.length
            seg_feats.append(_seg(sw.index, None, None, part, to_wgs))
    if uncovered > 0:
        warnings.append({"code": "VRA_UNCOVERED", "params": {"length_m": round(uncovered, 2)}})

    return {
        "unit": unit, "product": product, "classes": class_rows,
        "zones": {"type": "FeatureCollection", "features": zone_feats},
        "swath_segments": {"type": "FeatureCollection", "features": seg_feats},
        "warnings": warnings,
    }


MAX_RATE_ZONES = 50


REST_LABEL = "Rest of parcel"
_MIN_REST_M2 = 1.0


def build_zone_rate_prescription(*, zones, zone_rates: dict, rest_rate, unit, product, swaths_utm,
                                 parcel_utm, to_utm, to_wgs) -> dict:
    """One rate per zone (zonings without values, e.g. manual treatment zones).

    ``zones``: dicts ``{id, label, rank, geometry}`` (shapely, WGS84) of ONE zoning.
    Every zone needs a rate and every rate a zone. Lower rank wins overlaps; the
    output has the class-mode shape with one row per zone, so exports and the map
    treat it the same way. The part of the parcel outside every zone gets
    ``rest_rate`` (required, may be 0) as one more row flagged ``rest``.
    """
    if unit not in UNITS:
        raise _bad("Unsupported VRA unit", unit=unit)
    if not zones:
        raise _bad("The zoning has no zones")
    if len(zones) > MAX_RATE_ZONES:
        raise _bad("Too many zones for per-zone rates", count=len(zones), max=MAX_RATE_ZONES)
    ids = [z["id"] for z in zones]
    missing = sorted(i for i in ids if i not in zone_rates)
    if missing:
        raise _bad("Every zone needs a rate", missing=missing)
    id_set = set(ids)
    unknown = sorted(k for k in zone_rates if k not in id_set)
    if unknown:
        raise _bad("Rate given for a zone outside the zoning", unknown=unknown)
    for zid in ids:
        v = zone_rates[zid]
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0:
            raise _bad("Rate must be zero or positive", zone_id=zid)
    if isinstance(rest_rate, bool) or not isinstance(rest_rate, (int, float)) \
            or not math.isfinite(rest_rate) or rest_rate < 0:
        raise _bad("The rest of the parcel needs a rate", field="rest_rate")
    parcel = _polygonal(parcel_utm)
    if parcel is None:
        raise _bad("Parcel geometry is not usable")

    warnings: list[dict] = []
    ordered = sorted(zones, key=lambda z: (z.get("rank") is None, z.get("rank") or 0, z["id"]))
    groups = []
    for z in ordered:
        g = _polygonal(shp_transform(to_utm, z["geometry"])) if z.get("geometry") is not None else None
        if g is None:
            warnings.append({"code": "VRA_ZONE_INVALID", "params": {"zone_id": z["id"]}})
        groups.append([g] if g is not None else [])
    # The whole parcel as a last group: what no zone took is the rest of the parcel.
    polys = _exclusive_polys(groups + [[parcel]], parcel)
    meta = [{"zone_id": z["id"], "label": z.get("label") or z["id"].rsplit(":", 1)[-1],
             "min_pct": None, "max_pct": None} for z in ordered]
    rates = [float(zone_rates[z["id"]]) for z in ordered]
    rest = polys.pop()
    if rest is not None and rest.area >= _MIN_REST_M2:
        polys.append(rest)
        meta.append({"zone_id": None, "label": REST_LABEL, "rest": True, "min_pct": None, "max_pct": None})
        rates.append(float(rest_rate))
    return _render(meta, polys, rates, unit=unit, product=product, swaths_utm=swaths_utm,
                   to_wgs=to_wgs, warnings=warnings)


def _seg(swath_index, class_index, rate, line, to_wgs) -> dict:
    return {
        "type": "Feature",
        "geometry": mapping(shp_transform(to_wgs, line)),
        "properties": {"swath_index": swath_index, "class_index": class_index,
                       "rate": rate, "length_m": round(line.length, 2)},
    }


_SIMPLIFY_M = 0.25
_COORD_DECIMALS = 7


def _round_geom(geom):
    return shp_transform(
        lambda x, y, z=None: (round(x, _COORD_DECIMALS), round(y, _COORD_DECIMALS)), geom)


def persistable_prescription(rx: dict) -> dict:
    """Compact copy of a prescription for storage in the operation entity.

    Drops ``swath_segments`` (recomputable from the stored swaths and zones) and
    simplifies the class polygons by 0.25 m in UTM (topology preserved) so the
    entity stays under the broker's body limit. The input is not modified.
    """
    from pyproj import Transformer
    from shapely.geometry import shape

    from app.services.routing.base import get_utm_crs

    out = {k: v for k, v in rx.items() if k != "swath_segments"}
    feats = []
    for f in (rx.get("zones") or {}).get("features", []):
        g = shape(f["geometry"])
        if g.is_empty:
            feats.append(f)
            continue
        c = g.centroid
        crs = get_utm_crs(c.x, c.y)
        to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
        to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
        simple = shp_transform(to_utm, g).simplify(_SIMPLIFY_M, preserve_topology=True)
        feats.append({**f, "geometry": mapping(_round_geom(shp_transform(to_wgs, simple)))})
    out["zones"] = {"type": "FeatureCollection", "features": feats}
    return out
