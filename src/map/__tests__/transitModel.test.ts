import { describe, expect, it } from 'vitest';
import { buildTransitSources, changedTransitSources, transitLayerSpecs, TRANSIT_SOURCE_IDS, type TransitMapModel } from '../transitModel';
import type { PathAlternative } from '../../services/api';

const alt = (id: PathAlternative['id'], cross: number[]): PathAlternative => ({
  id, label: id, distance_m: 1, cumulative_climb_m: 0, max_cross_slope_deg_found: Math.max(...cross),
  geometry: { type: 'LineString', coordinates: [[0, 0], [3, 0]] },
  elevation_profile: cross.map((_, i) => [i, 0, 1]),
  cross_slope_profile: cross, max_cross_slope_at: [cross.indexOf(Math.max(...cross)), 0],
});
const base: TransitMapModel = {
  a: null, b: null, badPoint: null, focus: null, stale: false, hover: null, context: [],
  alternatives: [alt('least_slope', [1, 2, 3, 2]), alt('fastest', [1, 20, 1, 1])], selected: 'fastest', slopeLimit: 15,
};

describe('tr-cross source', () => {
  it('draws the zones and the max point of the selected route only', () => {
    const f = buildTransitSources(base)['tr-cross'].features;
    expect(f.filter((x) => x.properties!.kind === 'zone').map((x) => (x.geometry as GeoJSON.LineString).coordinates))
      .toEqual([[[0, 0], [1, 0], [2, 0]]]);
    const max = f.filter((x) => x.properties!.kind === 'max');
    expect(max).toHaveLength(1);
    expect((max[0].geometry as GeoJSON.Point).coordinates).toEqual([1, 0]);
    expect(max[0].properties!.deg).toBe(20);
    expect(max[0].properties!.high).toBe(true);
  });
  it('shows the max point even below the limit, with no zone', () => {
    const f = buildTransitSources({ ...base, selected: 'least_slope' })['tr-cross'].features;
    expect(f.map((x) => x.properties!.kind)).toEqual(['max']);
    expect(f[0].properties!.high).toBe(false);
  });
  it('is empty with no selection', () => {
    expect(buildTransitSources({ ...base, selected: null })['tr-cross'].features).toEqual([]);
  });
  it('is refreshed when the selection, alternatives or limit change', () => {
    expect(changedTransitSources(base, { ...base, selected: 'least_slope' })).toContain('tr-cross');
    expect(changedTransitSources(base, { ...base, slopeLimit: 20 })).toContain('tr-cross');
    expect(changedTransitSources(base, { ...base, hover: [0, 0] })).not.toContain('tr-cross');
  });
  it('has its layers drawn above the route lines', () => {
    expect(TRANSIT_SOURCE_IDS).toContain('tr-cross');
    const ids = transitLayerSpecs().map((l) => l.id);
    expect(ids.indexOf('tr-cross-line')).toBeGreaterThan(ids.indexOf('tr-alts-line'));
    expect(ids).toContain('tr-cross-point');
  });
});
