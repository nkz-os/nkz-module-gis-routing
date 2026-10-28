"""Class-based VRA prescription: class polygons and per-swath rate segments (pure)."""
from __future__ import annotations

from shapely.geometry import LineString, MultiLineString, mapping
from shapely.ops import transform as shp_transform, unary_union

from app.services.coverage.errors import PlanError
from app.services.vra.classify import ZoneValue, assign_classes, valid_zones

UNITS = ("kg_ha", "l_ha")
_MIN_LEN_M = 1e-6


def _bad(detail: str, **params) -> PlanError:
    return PlanError("INVALID_VRA", detail, params)


def _validate(classes: list[dict], unit: str, zones: list[ZoneValue]) -> None:
    n = len(classes)
    if not 2 <= n <= 5:
        raise _bad("VRA needs 2 to 5 classes", count=n)
    if unit not in UNITS:
        raise _bad("Unsupported VRA unit", unit=unit)
    if classes[0]["min_pct"] != 0 or classes[-1]["max_pct"] != 100:
        raise _bad("Classes must cover 0 to 100 percent")
    for i, c in enumerate(classes):
        if not c["min_pct"] < c["max_pct"]:
            raise _bad("Class range must be increasing", index=i)
        if i + 1 < n and c["max_pct"] != classes[i + 1]["min_pct"]:
            raise _bad("Classes must be contiguous", index=i)
        if c["rate"] is None or c["rate"] < 0:
            raise _bad("Rate must be zero or positive", index=i)
    if not valid_zones(zones):
        raise _bad("No zone has a value")


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

    assigned = assign_classes(zones, classes)
    vz = valid_zones(zones)
    if len({z.mean for z in vz}) == 1:
        warnings.append({"code": "VRA_DEGENERATE", "params": {}})
        assigned = {z.id: 0 for z in vz}

    rates = [float(c["rate"]) for c in classes]
    if invert:
        rates = rates[::-1]

    # Class polygons in UTM, lower index wins overlaps, clipped to the parcel.
    zone_utm = {z.id: shp_transform(to_utm, z.geometry) for z in vz}
    taken = None
    polys = []
    for k in range(n):
        members = [zone_utm[i] for i, c in assigned.items() if c == k]
        g = unary_union(members).intersection(parcel_utm) if members else None
        if g is not None and taken is not None:
            g = g.difference(taken)
        if g is not None and not g.is_empty:
            taken = g if taken is None else unary_union([taken, g])
        else:
            g = None
        polys.append(g)

    class_rows, zone_feats = [], []
    for k, c in enumerate(classes):
        g = polys[k]
        area_ha = g.area / 10000.0 if g is not None else 0.0
        class_rows.append({
            "index": k, "min_pct": c["min_pct"], "max_pct": c["max_pct"],
            "rate": rates[k], "area_ha": round(area_ha, 2),
            "product_total": round(area_ha * rates[k], 2),
        })
        if g is not None:
            zone_feats.append({
                "type": "Feature",
                "geometry": mapping(shp_transform(to_wgs, g)),
                "properties": {"class_index": k, "rate": rates[k]},
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


def _seg(swath_index, class_index, rate, line, to_wgs) -> dict:
    return {
        "type": "Feature",
        "geometry": mapping(shp_transform(to_wgs, line)),
        "properties": {"swath_index": swath_index, "class_index": class_index,
                       "rate": rate, "length_m": round(line.length, 2)},
    }
