import { describe, expect, it } from 'vitest';
import { toGeoJson, toGpx } from '../exportTransit';
import type { PathAlternative } from '../api';

const alt: PathAlternative = {
  id: 'fastest', label: 'Fastest', distance_m: 120.5, cumulative_climb_m: 3, max_slope_deg_found: 7,
  geometry: { type: 'LineString', coordinates: [[-1.5, 42.1], [-1.4, 42.2]] },
  elevation_profile: [[-1.5, 42.1, 400], [-1.4, 42.2, 410]],
};

describe('exportTransit', () => {
  it('writes a GPX track with elevations and an escaped name', () => {
    const gpx = toGpx(alt, 'A & <B>');
    expect(gpx).toContain('<name>A &amp; &lt;B&gt;</name>');
    expect(gpx).toContain('<trkpt lat="42.1" lon="-1.5"><ele>400</ele></trkpt>');
    expect(gpx.match(/<trkpt /g)).toHaveLength(2);
  });

  it('falls back to the geometry when there is no profile', () => {
    const gpx = toGpx({ ...alt, elevation_profile: [] }, 'x');
    expect(gpx).toContain('<trkpt lat="42.2" lon="-1.4"></trkpt>');
  });

  it('writes the chosen alternative as a LineString feature', () => {
    const f = toGeoJson(alt);
    expect(f.geometry.coordinates).toEqual([[-1.5, 42.1, 400], [-1.4, 42.2, 410]]);
    expect(f.properties).toMatchObject({ id: 'fastest', distance_m: 120.5, max_slope_deg_found: 7 });
  });
});
