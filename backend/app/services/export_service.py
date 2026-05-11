"""Export routing operations to ISOXML 11783-10, GeoJSON, and GPX formats."""

import json


class RouteExporter:
    def to_geojson(self, operation: dict) -> str:
        ab_line = self._parse_geojson(operation.get("ab_line_geojson", "{}"))
        maneuver_data = operation.get("maneuver_segments")
        features = []

        if maneuver_data:
            # Use maneuver segments: work + turn segments with type flag
            segments = json.loads(maneuver_data) if isinstance(maneuver_data, str) else maneuver_data
            for i, seg in enumerate(segments):
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": seg["coords"]},
                    "properties": {
                        "segment_index": i,
                        "segment_type": seg["type"],
                        "swath_index": seg.get("swath_index"),
                        "pass_index": seg.get("pass_index"),
                        "operation_type": operation.get("operation_type", ""),
                        "implement_width": operation.get("implement_width", 0),
                        "name": operation.get("name", ""),
                    },
                })
        else:
            # Fallback: raw swaths from ab_line_geojson
            coords_list = ab_line.get("coordinates", [])
            if ab_line.get("type") == "LineString":
                coords_list = [coords_list]
            for i, coords in enumerate(coords_list):
                features.append({
                    "type": "Feature",
                    "geometry": {"type": "LineString", "coordinates": coords},
                    "properties": {
                        "swath_index": i,
                        "operation_type": operation.get("operation_type", ""),
                        "implement_width": operation.get("implement_width", 0),
                        "name": operation.get("name", ""),
                    },
                })

        return json.dumps({"type": "FeatureCollection", "features": features}, indent=2)

    def to_gpx(self, operation: dict) -> str:
        name = self._xml_escape(operation.get("name", "Operation"))
        maneuver_data = operation.get("maneuver_segments")
        segments = None
        if maneuver_data:
            segments = json.loads(maneuver_data) if isinstance(maneuver_data, str) else maneuver_data

        parts = [
            '<?xml version="1.0" encoding="UTF-8"?>',
            '<gpx version="1.1" creator="nkz-module-gis-routing" xmlns="http://www.topografix.com/GPX/1/1">',
            f"  <trk><name>{name}</name>",
        ]

        if segments:
            # Continuous track with work/turn segments as separate <trkseg> elements
            for seg in segments:
                seg_type = seg.get("type", "work")
                swath_idx = seg.get("swath_index")
                label = f"work swath {swath_idx}" if swath_idx is not None else "turn"
                parts.append(f'    <trkseg>')
                parts.append(f'      <!-- {seg_type}: {label} -->')
                for c in seg["coords"]:
                    parts.append(f'      <trkpt lat="{c[1]}" lon="{c[0]}"></trkpt>')
                parts.append(f"    </trkseg>")
        else:
            # Fallback: raw swaths
            ab_line = self._parse_geojson(operation.get("ab_line_geojson", "{}"))
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
        farm = self._xml_escape(operation.get("farm_name", "NKZ Farm"))
        parcel = self._xml_escape(operation.get("parcel_name", "Parcel"))
        op_type = operation.get("operation_type", "spraying")
        width = operation.get("implement_width", 24.0)
        maneuver_data = operation.get("maneuver_segments")
        segments = None
        if maneuver_data:
            segments = json.loads(maneuver_data) if isinstance(maneuver_data, str) else maneuver_data

        lsg = []
        if segments:
            for i, seg in enumerate(segments):
                coords = seg["coords"]
                if len(coords) < 2:
                    continue
                seg_type = "1" if seg.get("type") == "work" else "0"
                lsg.append(
                    f'    <LSG A="{coords[0][1]}" B="{coords[0][0]}" '
                    f'C="{coords[-1][1]}" D="{coords[-1][0]}" '
                    f'LSGID="LSG{i + 1}" LSGTYPE="{seg_type}"/>'
                )
        else:
            ab_line = self._parse_geojson(operation.get("ab_line_geojson", "{}"))
            coords_list = ab_line.get("coordinates", [])
            if ab_line.get("type") == "LineString":
                coords_list = [coords_list]
            for i, c in enumerate(coords_list):
                if len(c) < 2:
                    continue
                lsg.append(
                    f'    <LSG A="{c[0][1]}" B="{c[0][0]}" '
                    f'C="{c[-1][1]}" D="{c[-1][0]}" LSGID="LSG{i + 1}"/>'
                )

        return (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<ISO11783TaskData version="4" '
            f'managementSoftware="nkz-module-gis-routing" '
            f'xmlns="http://www.isobus.net/xml/ISO11783_TaskData">\n'
            f'  <FRM A="{farm}" FRMID="FRM1"/>\n'
            f'  <CTR A="NKZ Farmer" CTRID="CTR1"/>\n'
            f'  <TSK TSKID="TSK1" FRMID="FRM1" CTRID="CTR1" '
            f'TSKNAME="{op_type} - {parcel}" TSKSTATUS="1">\n'
            f'    <GPN GPNID="GPN1" GPNDESIGN="{op_type} A-B lines" '
            f'GPNTYPE="AB" WIDTH="{width}">\n'
            f"{chr(10).join(lsg)}\n    </GPN>\n  </TSK>\n</ISO11783TaskData>"
        )

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
