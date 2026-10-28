"""The full operation as one GeoJSON FeatureCollection (pure; the API supplies the parcel).

Attributes are read in every form Orion may return them (short, nkz:, full IRI). An old
operation without the plan attributes yields what it has, flagged ``partial``.
"""
from __future__ import annotations

import logging

from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform as shp_transform

from app.services.parcel_constraints import _attr_value
from app.services.routing.base import get_utm_crs
from app.services.vra.prescription import _lines

logger = logging.getLogger(__name__)

PLAN_VERSION = 1
# Swath parts outside every prescription zone carry rate 0 (no dose), as in the ISOXML export.
OUTSIDE_RATE = 0
_MIN_LEN_M = 1e-6


def _feat(element: str, geometry, **props) -> dict:
    return {"type": "Feature", "geometry": geometry,
            "properties": {"element": element, **props}}


def _last_coord(geom: dict | None):
    if not isinstance(geom, dict):
        return None
    t, c = geom.get("type"), geom.get("coordinates")
    if not c:
        return None
    if t == "LineString":
        return list(c[-1])
    if t == "MultiLineString" and c[-1]:
        return list(c[-1][-1])
    return None


def _swath_features(swaths: list[dict], prescription: dict | None) -> list[dict]:
    zones = ((prescription or {}).get("zones") or {}).get("features") or []
    classes = []
    for z in zones:
        try:
            props = z.get("properties") or {}
            classes.append((props.get("class_index"), props.get("rate"), shape(z["geometry"])))
        except Exception:
            continue
    out = []
    for sw in swaths:
        props = sw.get("properties") or {} if isinstance(sw, dict) else {}
        index, kind = props.get("index"), props.get("kind")
        geom = sw.get("geometry") if isinstance(sw, dict) else None
        if not isinstance(geom, dict) or not geom.get("coordinates"):
            logger.warning("plan export skipped a swath without geometry: index=%s", index)
            continue
        if not classes:
            out.append(_feat("swath", geom, index=index, kind=kind))
            continue
        try:
            line = shape(geom)
        except Exception:
            logger.warning("plan export skipped an unreadable swath: index=%s", index)
            continue
        c = line.centroid
        crs = get_utm_crs(c.x, c.y)
        to_utm = Transformer.from_crs("EPSG:4326", crs, always_xy=True).transform
        to_wgs = Transformer.from_crs(crs, "EPSG:4326", always_xy=True).transform
        line_utm = shp_transform(to_utm, line)
        rest = line_utm
        for ci, rate, poly in sorted(classes, key=lambda t: (t[0] is None, t[0])):
            poly_utm = shp_transform(to_utm, poly)
            if not poly_utm.is_valid:
                poly_utm = poly_utm.buffer(0)
            for part in _lines(line_utm.intersection(poly_utm)):
                if part.length > _MIN_LEN_M:
                    out.append(_feat("swath", mapping(shp_transform(to_wgs, part)), index=index,
                                     kind=kind, class_index=ci, rate=rate))
            rest = rest.difference(poly_utm)
        for part in _lines(rest):
            if part.length > _MIN_LEN_M:
                out.append(_feat("swath", mapping(shp_transform(to_wgs, part)), index=index,
                                 kind=kind, class_index=None, rate=OUTSIDE_RATE))
    return out


def plan_feature_collection(entity: dict, parcel_geometry: dict | None = None,
                            parcel_unavailable: bool = False) -> dict:
    """FeatureCollection of every element of the stored operation.

    ``parcel_unavailable``: the operation names a parcel that could not be read; the plan is
    returned without its boundary and flagged ``partial``.
    """
    op_type = _attr_value(entity, "operationType")
    location = _attr_value(entity, "location")
    features: list[dict] = []

    if op_type == "transit":
        if location:
            features.append(_feat(
                "transit", location,
                elevation_profile=_attr_value(entity, "elevationProfile") or [],
                metrics=_attr_value(entity, "transitMetrics") or {}))
        partial = not location
    else:
        swaths_fc = _attr_value(entity, "swaths")
        swaths = (swaths_fc or {}).get("features") if isinstance(swaths_fc, dict) else None
        prescription = _attr_value(entity, "prescription")
        access_path = _attr_value(entity, "accessPath")
        access_point = _attr_value(entity, "accessPoint")
        return_path = _attr_value(entity, "returnPath")
        working_area = _attr_value(entity, "workingArea")
        zones_fc = _attr_value(entity, "exclusionZones")

        if location:
            features.append(_feat("route", location))
        features += _swath_features(swaths or [], prescription if isinstance(prescription, dict) else None)
        if access_path:
            features.append(_feat("access_path", access_path))
        if access_point:
            features.append(_feat("access_point", access_point))
        exit_point = _attr_value(entity, "exitPoint")
        if isinstance(exit_point, dict) and exit_point.get("coordinates"):
            features.append(_feat("exit_point", exit_point))
        else:
            # Old operations stored no exit point: the end of the route is the best they have.
            end = _last_coord(location)
            if end:
                features.append(_feat("exit_point", {"type": "Point", "coordinates": end}))
        if return_path:
            features.append(_feat("return_path", return_path))
        if isinstance(zones_fc, dict):
            for z in zones_fc.get("features") or []:
                if isinstance(z, dict) and z.get("geometry"):
                    features.append(_feat("exclusion_zone", z["geometry"],
                                          **{k: v for k, v in (z.get("properties") or {}).items()
                                             if k != "element"}))
        if parcel_geometry:
            features.append(_feat("parcel_boundary", parcel_geometry))
        if working_area:
            features.append(_feat("working_area", working_area))
        if isinstance(prescription, dict):
            unit = prescription.get("unit")
            for z in (prescription.get("zones") or {}).get("features") or []:
                p = z.get("properties") or {}
                features.append(_feat("prescription_zone", z.get("geometry"),
                                      class_index=p.get("class_index"), rate=p.get("rate"), unit=unit))
        partial = _attr_value(entity, "planVersion") is None or not swaths or parcel_unavailable
    properties = {"plan_version": PLAN_VERSION, "operation_id": entity.get("id"),
                  "operation_type": op_type, "partial": partial}
    if op_type != "transit" and isinstance(_attr_value(entity, "prescription"), dict):
        properties["outside_rate"] = OUTSIDE_RATE
    return {"type": "FeatureCollection", "features": features, "properties": properties}
