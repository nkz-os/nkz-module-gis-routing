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

    def to_isoxml(self, operation: dict) -> str:
        ab_line = self._parse_geojson(operation.get("ab_line_geojson", "{}"))
        farm = self._xml_escape(operation.get("farm_name", "NKZ Farm"))
        parcel = self._xml_escape(operation.get("parcel_name", "Parcel"))
        op_type = self._xml_escape(operation.get("operation_type", "spraying"))
        width = self._xml_escape(operation.get("implement_width", 24.0))
        coords_list = ab_line.get("coordinates", [])
        if ab_line.get("type") == "LineString":
            coords_list = [coords_list]
        lsg = []
        for i, c in enumerate(coords_list):
            if len(c) < 2:
                continue
            lsg.append(
                f'    <LSG A="{c[0][1]}" B="{c[0][0]}" C="{c[-1][1]}" D="{c[-1][0]}" LSGID="LSG{i+1}"/>'
            )
        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ISO11783TaskData version="4" managementSoftware="nkz-module-gis-routing" xmlns="http://www.isobus.net/xml/ISO11783_TaskData">\n'
            f'  <FRM A="{farm}" FRMID="FRM1"/>\n  <CTR A="NKZ Farmer" CTRID="CTR1"/>\n'
            f'  <TSK TSKID="TSK1" FRMID="FRM1" CTRID="CTR1" TSKNAME="{op_type} - {parcel}" TSKSTATUS="1">\n'
            f'    <GPN GPNID="GPN1" GPNDESIGN="{op_type} A-B lines" GPNTYPE="AB" WIDTH="{width}">\n'
            f"{chr(10).join(lsg)}\n    </GPN>\n{self._treatment_zones(operation.get('prescription'))}"
            f"  </TSK>\n</ISO11783TaskData>"
        )

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
                            out.append(f'          <PNT A="2" C="{c[1]}" D="{c[0]}"/>')
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
