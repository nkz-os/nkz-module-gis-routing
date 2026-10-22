"""Intersect A-B routing swaths with VRA management zones for prescription maps."""
from pyproj import CRS, Transformer
from shapely.geometry import shape, MultiLineString, mapping

_UNIT_CONVERSION: dict[str, float] = {
    "l_ha": 1.0,
    "kg_ha": 1.0,
    "ml_ha": 0.001,
    "g_ha": 0.001,
}


def _utm_length_m(geom) -> float:
    """Compute accurate length in meters using local UTM projection."""
    centroid = geom.centroid
    utm_crs = _get_utm_crs(centroid.x, centroid.y)
    wgs84 = CRS.from_epsg(4326)
    to_utm = Transformer.from_crs(wgs84, utm_crs, always_xy=True).transform
    utm_coords = [to_utm(x, y) for x, y in geom.coords]
    from shapely.geometry import LineString
    utm_line = LineString(utm_coords)
    return utm_line.length


def _get_utm_crs(lon: float, lat: float) -> CRS:
    zone = int((lon + 180) / 6) + 1
    is_north = lat >= 0
    epsg_code = 32600 + zone if is_north else 32700 + zone
    return CRS.from_epsg(epsg_code)


def _smooth_boundary_rates(segments: list[dict]) -> list[dict]:
    """Apply edge blending: segments at zone boundaries get averaged rates."""
    for i, seg in enumerate(segments):
        if i == 0 or i == len(segments) - 1:
            continue
        prev_zone = segments[i - 1]["properties"].get("zone_id")
        curr_zone = seg["properties"].get("zone_id")
        next_zone = segments[i + 1]["properties"].get("zone_id")
        if prev_zone != curr_zone or curr_zone != next_zone:
            neighbors = [segments[i - 1], segments[i + 1]]
            avg_rate = sum(n["properties"]["rate"] for n in neighbors) / 2
            seg["properties"]["rate"] = round(
                seg["properties"]["rate"] * 0.7 + avg_rate * 0.3, 2,
            )
    return segments


def intersect_swaths_with_zones(
    swaths: MultiLineString, zones: list[dict], base_rate: float, width_m: float, rate_unit: str = "l_ha",
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
                            "length_m": round(_utm_length_m(geom), 2),
                            "rate": round(base_rate * zone_rate * _UNIT_CONVERSION.get(rate_unit, 1.0), 2),
                            "zone_id": zone["properties"].get("zone_id"),
                            "zone_class": zone["properties"].get("zone_class", ""),
                            "width_m": width_m,
                        },
                    }
                )
    if segments:
        segments = _smooth_boundary_rates(segments)
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
