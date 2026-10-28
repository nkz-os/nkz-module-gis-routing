import type { PathAlternative } from './api';

const xml = (s: string) =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&apos;');

/** Elevation-bearing vertices: the profile when it carries z, else the plain geometry. */
function vertices(alt: PathAlternative): number[][] {
  const prof = alt.elevation_profile;
  return prof && prof.length >= 2 && prof.every((p) => p.length >= 3) ? prof : alt.geometry.coordinates;
}

export function toGpx(alt: PathAlternative, name: string): string {
  const pts = vertices(alt)
    .map((p) => `      <trkpt lat="${p[1]}" lon="${p[0]}">${p.length >= 3 && Number.isFinite(p[2]) ? `<ele>${p[2]}</ele>` : ''}</trkpt>`)
    .join('\n');
  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="nkz-module-gis-routing" xmlns="http://www.topografix.com/GPX/1/1">
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
  const url = URL.createObjectURL(new Blob([content], { type: mime }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
