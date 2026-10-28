import type { PathAlternative } from './api';

// XML 1.0 forbids most control characters, even escaped.
const xml = (s: string) =>
  s.replace(/[\x00-\x08\x0B\x0C\x0E-\x1F]/g, '').replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');

/** Elevation-bearing vertices: the profile when it carries z, else the plain geometry. */
function vertices(alt: PathAlternative): number[][] {
  const prof = alt.elevation_profile;
  return prof && prof.length >= 2 && prof.every((p) => p.length >= 3) ? prof : alt.geometry.coordinates;
}

// GPX 1.1 XML namespace (a schema identifier, not a host the module calls).
const GPX_NS = 'http://www.topografix.com/GPX/1/1'; // hygiene:allow GPX 1.1 namespace

export function toGpx(alt: PathAlternative, name: string): string {
  const pts = vertices(alt)
    .map((p) => `      <trkpt lat="${p[1]}" lon="${p[0]}">${p.length >= 3 && Number.isFinite(p[2]) ? `<ele>${p[2]}</ele>` : ''}</trkpt>`)
    .join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="nkz-module-gis-routing" xmlns="${GPX_NS}">
  <trk>
    <name>${xml(name)}</name>
    <trkseg>
${pts}
    </trkseg>
  </trk>
</gpx>
`;
}

export function toGeoJson(alt: PathAlternative): GeoJSON.Feature<GeoJSON.LineString> {
  return {
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: vertices(alt) },
    properties: {
      id: alt.id,
      label: alt.label,
      distance_m: alt.distance_m,
      cumulative_climb_m: alt.cumulative_climb_m,
      max_slope_deg_found: alt.max_slope_deg_found ?? null,
    },
  };
}

/** Browser download of a text file through a Blob. */
export function downloadText(filename: string, mime: string, content: string): void {
  downloadBlob(filename, new Blob([content], { type: mime }));
}

/** Browser download of a Blob under a file name. */
export function downloadBlob(filename: string, blob: Blob): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
