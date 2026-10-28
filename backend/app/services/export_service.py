"""Export routing operations to ISOXML 11783-10, GeoJSON, and GPX formats."""
import json
from datetime import datetime


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
        op_type = operation.get("operation_type", "spraying")
        width = operation.get("implement_width", 24.0)
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
        rx = self._parse_geojson(rx) if rx else {}
        ddi = self._DDI.get(rx.get("unit")) if rx else None
        if not ddi:
            return ""
        by_class: dict = {}
        for f in (rx.get("zones") or {}).get("features", []):
            ci = (f.get("properties") or {}).get("class_index")
            if ci is None:
                continue
            by_class.setdefault(int(ci), []).append(f.get("geometry") or {})
        out = []
        for cls in sorted(rx.get("classes") or [], key=lambda c: c["index"]):
            idx = int(cls["index"])
            value = int(round(float(cls["rate"]) * self._PDV_PER_UNIT[rx["unit"]]))
            label = self._xml_escape(f"Class {idx + 1} ({cls.get('min_pct')}-{cls.get('max_pct')}%)")
            out.append(f'    <TZN A="{idx}" B="{label}">')
            out.append(f'      <PDV A="{ddi}" B="{value}"/>')
            for geom in by_class.get(idx, []):
                if geom.get("type") == "Polygon":
                    parts = [geom.get("coordinates") or []]
                elif geom.get("type") == "MultiPolygon":
                    parts = geom.get("coordinates") or []
                else:
                    continue
                for rings in parts:
                    if not rings:
                        continue
                    out.append('      <PLN A="2">')
                    for r, ring in enumerate(rings):
                        pts = ring[:-1] if len(ring) > 1 and ring[0] == ring[-1] else ring
                        out.append(f'        <LSG A="{1 if r == 0 else 2}">')
                        for c in pts:
                            out.append(f'          <PNT A="2" C="{c[1]}" D="{c[0]}"/>')
                        out.append("        </LSG>")
                    out.append("      </PLN>")
            out.append("    </TZN>")
        return "\n".join(out) + "\n" if out else ""

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
