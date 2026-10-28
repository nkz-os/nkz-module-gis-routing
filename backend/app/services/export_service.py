"""Export routing operations to ISOXML 11783-10, GeoJSON, and GPX formats."""
import json
import math
from datetime import datetime

from app.services.coverage.errors import PlanError


class RouteExporter:
    def to_geojson(self, operation: dict) -> str:
        ab_line = self._parse_geojson(operation.get("ab_line_geojson", "{}"))
        features = []
        coords_list = ab_line.get("coordinates", [])
        if ab_line.get("type") == "LineString":
            coords_list = [coords_list]
        for i, coords in enumerate(coords_list):
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "swath_index": i,
                        "operation_type": operation.get("operation_type", ""),
                        "implement_width": operation.get("implement_width", 0),
                        "name": operation.get("name", ""),
                    },
                }
            )
        return json.dumps({"type": "FeatureCollection", "features": features}, indent=2)

    def to_gpx(self, operation: dict) -> str:
        ab_line = self._parse_geojson(operation.get("ab_line_geojson", "{}"))
        name = self._xml_escape(operation.get("name", "Operation"))
        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gpx version="1.1" creator="nkz-module-gis-routing" xmlns="http://www.topografix.com/GPX/1/1">',
            f"  <trk><name>{name}</name>",
        ]
        coords_list = ab_line.get("coordinates", [])
        if ab_line.get("type") == "LineString":
            coords_list = [coords_list]
        for coords in coords_list:
            parts.append("    <trkseg>")
            for c in coords:
                parts.append(f'      <trkpt lat="{c[1]}" lon="{c[0]}"></trkpt>')
            parts.append("    </trkseg>")
        parts.append("  </trk></gpx>")
        return "\n".join(parts)

    # ISO 11783-10 element/attribute codes, checked against the AEF/isobus.net
    # TaskFile XSD v4.3 (Common_V4-3: PFD, PLN, LSG, PNT, GGP, GPN, TSK, TZN, PDV,
    # FRM, CTR; ISO11783_TaskData root). The data has no XML namespace.
    #   root: VersionMajor=4 VersionMinor=3 DataTransferOrigin=1 (FMIS)
    #   PFD A id, C designator, D area m2 | PLN A=1 boundary, 2 treatment zone
    #   LSG A=1 exterior, 2 interior, 5 guidance pattern | PNT A=2 other, 6 guidance A,
    #   7 guidance B, C north, D east (9 decimals) | GPN A id, B designator, C=1 AB
    #   TSK A id, B designator, C/D/E refs, G=1 planned
    # ASSUMPTION: LSG C (guidance line width) is in millimetres, as the XSD names it
    # LineStringWidth without a unit; ISO 11783-10 gives mm for lengths.
    # ASSUMPTION: polygon rings are written without repeating the first point.
    def to_isoxml(self, operation: dict) -> str:
        farm = self._xml_escape(self._cut(operation.get("farm_name", "NKZ Farm")))
        parcel_name = self._cut(operation.get("parcel_name", "Parcel"))
        op_type = self._cut(operation.get("operation_type", "spraying"))
        width_mm = self._width_mm(operation.get("implement_width"))
        lines = self._guidance_lines(operation)
        boundary = self._boundary_plns(operation.get("parcel_geometry"))
        area = self._area_m2(operation.get("parcel_geometry"))
        zones = self._treatment_zones(operation.get("prescription"))
        out = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<ISO11783_TaskData VersionMajor="4" VersionMinor="3" '
            'ManagementSoftwareManufacturer="nkz-module-gis-routing" '
            'ManagementSoftwareVersion="1" DataTransferOrigin="1">',
            f'  <CTR A="CTR1" B="NKZ Farmer"/>',
            f'  <FRM A="FRM1" B="{farm}" I="CTR1"/>',
            f'  <PFD A="PFD1" C="{self._xml_escape(parcel_name)}" D="{area}" E="CTR1" F="FRM1">',
        ]
        out += boundary
        out.append('    <GGP A="GGP1" B="Guidance lines">')
        for i, (label, pts) in enumerate(lines):
            w = f' C="{width_mm}"' if width_mm else ""
            out += [
                f'      <GPN A="GPN{i + 1}" B="{self._xml_escape(self._cut(label))}" C="1">',
                f'        <LSG A="5"{w}>',
                f'          <PNT A="6" C="{self._f(pts[0][1])}" D="{self._f(pts[0][0])}"/>',
                f'          <PNT A="7" C="{self._f(pts[1][1])}" D="{self._f(pts[1][0])}"/>',
                "        </LSG>",
                "      </GPN>",
            ]
        out.append("    </GGP>")
        out.append("  </PFD>")
        out.append(f'  <TSK A="TSK1" B="{self._xml_escape(self._cut(op_type + " - " + parcel_name))}" '
                   f'C="CTR1" D="FRM1" E="PFD1" G="1">')
        out.append(zones.rstrip("\n"))
        out.append("  </TSK>")
        out.append("</ISO11783_TaskData>")
        return "\n".join(x for x in out if x != "")

    @staticmethod
    def _f(v) -> str:
        return f"{float(v):.9f}"

    @staticmethod
    def _cut(text, n: int = 32) -> str:
        return str(text)[:n]

    @staticmethod
    def _width_mm(width) -> int:
        try:
            w = float(width)
        except (TypeError, ValueError):
            return 0
        return int(round(w * 1000)) if math.isfinite(w) and w > 0 else 0

    def _guidance_lines(self, operation: dict) -> list:
        """(label, [A, B]) per guidance line: one per stored swath, else one per route line."""
        out = []
        swaths = operation.get("swaths")
        if isinstance(swaths, list) and swaths:
            for n, f in enumerate(swaths):
                geom = (f or {}).get("geometry") if isinstance(f, dict) else None
                props = (f or {}).get("properties") or {} if isinstance(f, dict) else {}
                for c in self._line_parts(geom):
                    idx = props.get("index", n)
                    out.append((f"{props.get('kind') or 'swath'} {idx}", [c[0], c[-1]]))
            return out
        ab = self._parse_geojson(operation.get("ab_line_geojson", "{}"))
        for i, c in enumerate(self._line_parts(ab)):
            out.append((f"{operation.get('operation_type', '')} A-B {i + 1}", [c[0], c[-1]]))
        return out

    @staticmethod
    def _line_parts(geom) -> list:
        if not isinstance(geom, dict):
            return []
        coords = geom.get("coordinates") or []
        parts = [coords] if geom.get("type") == "LineString" else (
            coords if geom.get("type") == "MultiLineString" else [])
        res = []
        for c in parts:
            try:
                if len(c) >= 2 and tuple(c[0][:2]) != tuple(c[-1][:2]):
                    float(c[0][0]), float(c[0][1]), float(c[-1][0]), float(c[-1][1])
                    res.append(c)
            except (TypeError, ValueError, IndexError):
                continue
        return res

    def _boundary_plns(self, geom) -> list:
        out = []
        for rings in self._polygon_parts(geom):
            out.append('    <PLN A="1">')
            for r, ring in enumerate(rings):
                out.append(f'      <LSG A="{1 if r == 0 else 2}">')
                for c in ring[:-1]:
                    out.append(f'        <PNT A="2" C="{self._f(c[1])}" D="{self._f(c[0])}"/>')
                out.append("      </LSG>")
            out.append("    </PLN>")
        return out

    @classmethod
    def _polygon_parts(cls, geom) -> list:
        """Usable polygons as lists of closed rings (exterior first)."""
        if not isinstance(geom, dict):
            return []
        if geom.get("type") == "Polygon":
            parts = [geom.get("coordinates") or []]
        elif geom.get("type") == "MultiPolygon":
            parts = geom.get("coordinates") or []
        else:
            return []
        res = []
        for rings in parts:
            rings = [r if (len(r) > 1 and r[0] == r[-1]) else list(r) + [r[0]]
                     for r in rings if len(r) >= 3]
            rings = [r for r in rings if len(r) >= 4]
            if rings and cls._ring_ok(rings[0]):
                res.append(rings)
        return res

    def _area_m2(self, geom) -> int:
        parts = self._polygon_parts(geom)
        if not parts:
            return 0
        from pyproj import Transformer
        from shapely.geometry import Polygon
        from shapely.ops import transform
        from app.services.routing.base import get_utm_crs
        c0 = parts[0][0][0]
        to_utm = Transformer.from_crs("EPSG:4326", get_utm_crs(c0[0], c0[1]), always_xy=True).transform
        total = 0.0
        for rings in parts:
            poly = transform(to_utm, Polygon(rings[0], rings[1:]))
            total += poly.area if poly.is_valid else poly.buffer(0).area
        return int(round(total))

    # ISO 11783-11 DDI database: DDI 1 Setpoint Volume Per Area, mm3/m2,
    # resolution 0.01; DDI 6 Setpoint Mass Per Area, mg/m2, resolution 1.
    # PDV B is the raw value (physical / resolution):
    #   1 l/ha  = 100 mm3/m2 -> 100 / 0.01 = 10000 per l/ha
    #   1 kg/ha = 100 mg/m2  -> 100 / 1    = 100 per kg/ha
    # ASSUMPTION: PLN A=2 treatment zone, LSG A=1 exterior / 2 interior,
    # PNT A=2 other (ISO 11783-10, not checked against the XSD yet).
    _DDI = {"l_ha": "0001", "kg_ha": "0006"}
    _PDV_PER_UNIT = {"l_ha": 10000, "kg_ha": 100}

    def _treatment_zones(self, rx) -> str:
        """TZN blocks for the stored prescription.

        No prescription (None / "" / "null") -> "". A prescription that is
        present but malformed raises INVALID_VRA: a tractor must never run a
        file whose VRA was silently dropped.
        """
        if rx is None or (isinstance(rx, str) and rx.strip() in ("", "null")):
            return ""
        try:
            return self._build_zones(rx)
        except PlanError:
            raise
        except (TypeError, ValueError, KeyError, IndexError, AttributeError) as exc:
            raise PlanError("INVALID_VRA", "stored prescription is malformed",
                            {"reason": type(exc).__name__}) from exc

    def _build_zones(self, rx) -> str:
        def bad(reason: str, **params):
            raise PlanError("INVALID_VRA", f"stored prescription is invalid: {reason}",
                            {"reason": reason, **params})

        if isinstance(rx, str):
            try:
                rx = json.loads(rx)
            except json.JSONDecodeError:
                bad("not_json")
        if not isinstance(rx, dict):
            bad("not_object")
        unit = rx.get("unit")
        if unit not in self._DDI:
            bad("unknown_unit", unit=str(unit))
        zones = rx.get("zones")
        if isinstance(zones, str):
            try:
                zones = json.loads(zones)
            except json.JSONDecodeError:
                bad("zones_not_json")
        if not isinstance(zones, dict) or not isinstance(zones.get("features"), list):
            bad("zones_invalid")
        classes = rx.get("classes")
        if not isinstance(classes, list) or not classes:
            bad("classes_missing")
        by_class: dict = {}
        for f in zones["features"]:
            ci = (f.get("properties") or {}).get("class_index")
            if ci is None:
                continue
            by_class.setdefault(int(ci), []).append(f.get("geometry") or {})
        norm = []
        seen = set()
        for cls in classes:
            if not isinstance(cls, dict) or isinstance(cls.get("index"), bool) \
                    or not isinstance(cls.get("index"), int) or not 0 <= cls["index"] <= 254:
                bad("class_index_invalid")
            rate = cls.get("rate")
            if isinstance(rate, bool) or not isinstance(rate, (int, float)) \
                    or not math.isfinite(rate) or rate < 0:
                bad("rate_invalid", class_index=cls["index"])
            if cls["index"] in seen:
                bad("class_index_duplicate", class_index=cls["index"])
            seen.add(cls["index"])
            norm.append(cls)
        out = []
        for cls in sorted(norm, key=lambda c: c["index"]):
            idx = cls["index"]
            value = int(round(float(cls["rate"]) * self._PDV_PER_UNIT[unit]))
            label = self._xml_escape(f"Class {idx + 1} ({cls.get('min_pct')}-{cls.get('max_pct')}%)")
            out.append(f'    <TZN A="{idx}" B="{label}">')
            out.append(f'      <PDV A="{self._DDI[unit]}" B="{value}"/>')
            for geom in by_class.get(idx, []):
                if geom.get("type") == "Polygon":
                    parts = [geom.get("coordinates") or []]
                elif geom.get("type") == "MultiPolygon":
                    parts = geom.get("coordinates") or []
                else:
                    continue
                for rings in parts:
                    # A closed ring needs >= 4 points; a polygon without a
                    # usable exterior is skipped whole.
                    rings = [r if (len(r) > 1 and r[0] == r[-1]) else list(r) + [r[0]]
                             for r in rings if len(r) >= 3]
                    rings = [r for r in rings if len(r) >= 4]
                    if not rings or not self._ring_ok(rings[0]):
                        continue
                    out.append('      <PLN A="2">')
                    for r, ring in enumerate(rings):
                        out.append(f'        <LSG A="{1 if r == 0 else 2}">')
                        for c in ring[:-1]:
                            out.append(f'          <PNT A="2" C="{self._f(c[1])}" D="{self._f(c[0])}"/>')
                        out.append("        </LSG>")
                    out.append("      </PLN>")
            out.append("    </TZN>")
        return "\n".join(out) + "\n"

    @staticmethod
    def _ring_ok(ring) -> bool:
        return len({(c[0], c[1]) for c in ring}) >= 3

    def _parse_geojson(self, value) -> dict:
        if isinstance(value, str):
            try:
                return json.loads(value)
            except (json.JSONDecodeError, TypeError):
                return {}
        return value or {}

    def _xml_escape(self, text: str) -> str:
        return (
            str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
        )
