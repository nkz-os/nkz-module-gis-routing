"""Intersect A-B routing swaths with VRA management zones for prescription maps."""
from shapely.geometry import shape, MultiLineString, mapping


def intersect_swaths_with_zones(
    swaths: MultiLineString, zones: list[dict], base_rate: float, width_m: float
) -> dict:
    segments = []
    for swath_line in swaths.geoms:
        for zone in zones:
            zone_poly = shape(zone["geometry"])
            if not zone_poly.is_valid:
                zone_poly = zone_poly.buffer(0)
            zone_rate = zone["properties"].get("prescription_rate", 1.0)
            if zone_rate is None:
                zone_rate = 1.0
            intersection = swath_line.intersection(zone_poly)
            if intersection.is_empty:
                continue
            geoms = _to_geometry_list(intersection)
            for geom in geoms:
                if geom.length < 0.000001:
                    continue
                segments.append(
                    {
                        "type": "Feature",
                        "geometry": mapping(geom),
                        "properties": {
                            "length_m": round(geom.length * 111320, 2),
                            "rate": round(base_rate * zone_rate, 2),
                            "zone_id": zone["properties"].get("zone_id"),
                            "zone_class": zone["properties"].get("zone_class", ""),
                            "width_m": width_m,
                        },
                    }
                )
    return {"type": "FeatureCollection", "features": segments}


def _to_geometry_list(geom):
    if geom.geom_type == "LineString":
        return [geom]
    elif geom.geom_type == "MultiLineString":
        return list(geom.geoms)
    elif geom.geom_type == "GeometryCollection":
        return [
            g for g in geom.geoms if g.geom_type == "LineString"
        ]
    return []
