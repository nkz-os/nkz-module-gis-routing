import { describe, expect, it } from 'vitest';
import { buildSources, layerSpecs, planBounds, SOURCE_IDS } from '../model';
const sq = (x0: number, y0: number, x1: number, y1: number, holes: number[][][] = []) => ({ type: 'Polygon', coordinates: [[[x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0]], ...holes] }) as any;
const base = { parcel: sq(0, 0, 10, 10, [[[4, 4], [6, 4], [6, 6], [4, 6], [4, 4]]]), zones: [{ id: 'z', polygon: sq(1, 1, 2, 2), areaHa: 1, valid: true }], marginM: 2, accessPoint: { type: 'Point', coordinates: [0, 5] } as any, accessIssue: null, plan: null, stale: false, hoveredSwath: null, selectedWarning: null };
describe('map model', () => {
  it('emits every source id, rings as separate features and zone attributes', () => {
    const s = buildSources(base);
    expect(Object.keys(s).sort()).toEqual([...SOURCE_IDS].sort());
    expect(s['parcel-rings'].features).toHaveLength(1);
    expect(s.zones.features[0].properties).toMatchObject({ id: 'z', valid: true });
    expect(s.markers.features.find(f => f.properties?.kind === 'access')).toBeTruthy();
    expect(s.swaths.features).toHaveLength(0); expect(s.route.features).toHaveLength(0);
  });
  it('maps a plan to swaths, route, access and numbered warnings', () => {
    const plan: any = { route: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, swaths: [{ index: 0, kind: 'work', geometry: { type: 'LineString', coordinates: [[0, 0], [1, 0]] } }, { index: 1, kind: 'headland', geometry: { type: 'LineString', coordinates: [[0, 1], [1, 1]] } }],
      access_path: { type: 'LineString', coordinates: [[0, 5], [0, 0]] }, return_path: null, exit_point: { type: 'Point', coordinates: [1, 1] }, access_point: null,
      validation: { ok: true, checks: [], fallbacks_applied: [], warnings: [{ code: 'MANUAL_TURN', geometry: { type: 'LineString', coordinates: [[0, 0], [0, 1]] }, params: {} }, { code: 'HEADLAND_WIDENED', geometry: null, params: {} }] } };
    const s = buildSources({ ...base, plan, stale: true, hoveredSwath: 1 });
    expect(s.swaths.features.map(f => f.properties)).toEqual([{ index: 0, kind: 'work', hovered: false }, { index: 1, kind: 'headland', hovered: true }]);
    expect(s.route.features[0].properties).toEqual({ stale: true });
    expect(s.access.features.map(f => f.properties?.kind)).toEqual(['access']);
    expect(s.warnings.features).toHaveLength(1); expect(s.warnings.features[0].properties).toMatchObject({ n: 1, code: 'MANUAL_TURN' });
    expect(s.markers.features.map(f => f.properties?.kind).sort()).toEqual(['access', 'exit']);
  });
  it('layer specs reference only known sources, in §5 order', () => {
    const specs = layerSpecs(); const ids = specs.map(l => (l as any).source);
    for (const id of ids) expect(SOURCE_IDS).toContain(id);
    expect(ids.indexOf('parcel')).toBeLessThan(ids.indexOf('zones')); expect(ids.lastIndexOf('zones')).toBeLessThan(ids.indexOf('swaths'));
    expect(ids.lastIndexOf('swaths')).toBeLessThan(ids.indexOf('route')); expect(ids.lastIndexOf('route')).toBeLessThan(ids.indexOf('markers'));
    expect(ids.lastIndexOf('markers')).toBeLessThan(ids.indexOf('warnings'));
  });
  it('planBounds follows the parcel', () => { expect(planBounds(base)).toEqual([0, 0, 10, 10]); expect(planBounds({ ...base, parcel: null })).toBeNull(); });
});
