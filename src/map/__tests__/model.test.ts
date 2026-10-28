import { describe, expect, it } from 'vitest';
import { buildSources, changedSources, layerSpecs, planBounds, SOURCE_IDS, VRA_PALETTE, vraClassColors, VRA_UNCOVERED_COLOR } from '../model';
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
    expect(s.warnings.features).toHaveLength(2);
    expect(s.warnings.features.map(f => f.properties?.part).sort()).toEqual(['anchor', 'shape']);
    const anchor = s.warnings.features.find(f => f.properties?.part === 'anchor')!;
    expect(anchor.geometry.type).toBe('Point'); expect(anchor.properties).toMatchObject({ n: 1, code: 'MANUAL_TURN' });
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
  it('draws the safety margin as a real buffer of marginM metres around the zone', () => {
    const f = buildSources(base)['zones-margin'].features;
    expect(f).toHaveLength(1);
    const xs = (f[0].geometry as any).coordinates[0].map((c: number[]) => c[0]);
    const grow = 1 - Math.min(...xs); // zone starts at lon 1
    expect(grow).toBeGreaterThan(1.5e-5);
    expect(grow).toBeLessThan(2.2e-5); // 2 m is about 1.8e-5 deg
  });
  it('draws the margin dashed red, below the zone border so it never covers it', () => {
    const specs = layerSpecs() as any[];
    const margin = specs.find((l) => l.id === 'zones-margin-line');
    expect(margin.paint['line-color']).toBe('#DC2626');
    expect(margin.paint['line-dasharray']).toBeTruthy();
    const ids = specs.map((l) => l.id);
    expect(ids.indexOf('zones-margin-line')).toBeLessThan(ids.indexOf('zones-line'));
  });
  it('handles null margin, null validation and MultiLineString routes', () => {
    expect(buildSources({ ...base, marginM: null })['zones-margin'].features).toHaveLength(0);
    const route = { type: 'MultiLineString', coordinates: [[[0, 0], [1, 1]], [[2, 2], [3, 3]]] };
    const plan: any = { route, swaths: [], access_path: null, return_path: null, exit_point: { type: 'Point', coordinates: [3, 3] }, access_point: null, validation: null };
    const m = { ...base, parcel: null, plan };
    const s = buildSources(m);
    expect(s.warnings.features).toHaveLength(0);
    expect(s.route.features[0].geometry).toEqual(route);
    expect(planBounds(m)).toEqual([0, 0, 3, 3]);
  });
  it('anchors polygon and point warnings on one point', () => {
    const plan: any = { route: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, swaths: [], access_path: null, return_path: null, exit_point: { type: 'Point', coordinates: [1, 1] }, access_point: null,
      validation: { ok: true, checks: [], fallbacks_applied: [], warnings: [{ code: 'A', geometry: sq(0, 0, 2, 4), params: {} }, { code: 'B', geometry: { type: 'Point', coordinates: [5, 5] }, params: {} }] } };
    const f = buildSources({ ...base, plan }).warnings.features;
    expect(f.filter(x => x.properties?.part === 'anchor').map(x => (x.geometry as any).coordinates)).toEqual([[1, 2], [5, 5]]);
    expect(f.filter(x => x.properties?.part === 'shape')).toHaveLength(1);
  });
  it('draws a failed-request focus geometry as a synthetic warning and fits to it', () => {
    const focus: any = { type: 'Point', coordinates: [20, 30] };
    const s = buildSources({ ...base, focus });
    expect(s.warnings.features).toHaveLength(1);
    expect(s.warnings.features[0].properties).toMatchObject({ n: 0, code: 'ERROR', selected: true, part: 'anchor' });
    expect(planBounds({ ...base, focus })).toEqual([20, 30, 20, 30]);
    const line: any = { type: 'LineString', coordinates: [[1, 1], [2, 2]] };
    expect(buildSources({ ...base, focus: line }).warnings.features.map(f => f.properties?.part).sort()).toEqual(['anchor', 'shape']);
  });
});

describe('changedSources', () => {
  it('rebuilds everything on first model and only swaths on hover', () => {
    expect(changedSources(null, base as any)).toEqual([...SOURCE_IDS]);
    expect(changedSources(base as any, { ...base, hoveredSwath: 3 } as any)).toEqual(['swaths']);
    expect(changedSources(base as any, { ...base, selectedWarning: 1 } as any)).toEqual(['warnings']);
    expect(changedSources(base as any, base as any)).toEqual([]);
  });
  it('a new plan touches every plan-derived source but not parcel or zones', () => {
    const out = changedSources(base as any, { ...base, plan: {} } as any);
    expect(out).toEqual(expect.arrayContaining(['swaths', 'route', 'access', 'markers', 'warnings']));
    expect(out).not.toContain('parcel'); expect(out).not.toContain('zones');
  });

  describe('VRA classes', () => {
    const presc: any = {
      unit: 'kg_ha', product: 'N', warnings: [],
      classes: [{ index: 0 }, { index: 1 }, { index: 2 }],
      zones: { type: 'FeatureCollection', features: [
        { type: 'Feature', geometry: sq(0, 0, 4, 4), properties: { class_index: 0, rate: 80 } },
        { type: 'Feature', geometry: sq(4, 0, 8, 4), properties: { class_index: 2, rate: 120 } },
      ] },
      swath_segments: { type: 'FeatureCollection', features: [
        { type: 'Feature', geometry: { type: 'LineString', coordinates: [[0, 1], [3, 1]] }, properties: { swath_index: 3, class_index: 0, rate: 80, length_m: 3 } },
        { type: 'Feature', geometry: { type: 'LineString', coordinates: [[9, 1], [10, 1]] }, properties: { swath_index: 3, class_index: null, rate: null, length_m: 1 } },
      ] },
    };
    const plan: any = { route: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, swaths: [{ index: 3, kind: 'work', geometry: { type: 'LineString', coordinates: [[0, 1], [10, 1]] } }], access_path: null, return_path: null, exit_point: { type: 'Point', coordinates: [1, 1] }, access_point: null, validation: null };
    const withVra = { ...base, plan, vra: presc, vraRateLabel: (r: number) => `${r} u` };

    it('palette: n first steps spread over the ramp; grey for uncovered', () => {
      expect(VRA_PALETTE).toHaveLength(5);
      expect(vraClassColors(5)).toEqual([...VRA_PALETTE]);
      expect(vraClassColors(2)).toEqual([VRA_PALETTE[0], VRA_PALETTE[4]]);
      expect(vraClassColors(3)).toEqual([VRA_PALETTE[0], VRA_PALETTE[2], VRA_PALETTE[4]]);
      expect(vraClassColors(1)).toEqual([VRA_PALETTE[0]]);
      expect(new Set(vraClassColors(4)).size).toBe(4);
      expect(VRA_UNCOVERED_COLOR).not.toBe('');
    });
    it('no prescription: empty vra source and plain swaths', () => {
      const s = buildSources({ ...base, plan });
      expect(s['vra-classes'].features).toHaveLength(0);
      expect(s.swaths.features[0].properties).toEqual({ index: 3, kind: 'work', hovered: false });
    });
    it('emits a fill and a labelled anchor per class polygon', () => {
      const f = buildSources(withVra)['vra-classes'].features;
      const fills = f.filter(x => x.properties?.part === 'fill');
      const labels = f.filter(x => x.properties?.part === 'label');
      expect(fills.map(x => x.properties?.color)).toEqual([vraClassColors(3)[0], vraClassColors(3)[2]]);
      expect(labels.map(x => x.properties?.label)).toEqual(['80 u', '120 u']);
      expect(labels.every(x => x.geometry.type === 'Point')).toBe(true);
    });
    it('colours swath segments by class from the prescription; uncovered grey', () => {
      const f = buildSources({ ...withVra, hoveredSwath: 3 }).swaths.features;
      expect(f).toHaveLength(2);
      expect(f[0].properties).toMatchObject({ index: 3, kind: 'work', hovered: true, color: vraClassColors(3)[0] });
      expect(f[1].properties).toMatchObject({ index: 3, color: VRA_UNCOVERED_COLOR });
    });
    it('segments keep the plan swath kind (headland) with a fallback to work', () => {
      const p2: any = { ...plan, swaths: [{ index: 3, kind: 'headland', geometry: plan.swaths[0].geometry }] };
      const f = buildSources({ ...withVra, plan: p2 }).swaths.features;
      expect(f.map(x => x.properties?.kind)).toEqual(['headland', 'headland']);
      const g = buildSources({ ...withVra, plan: { ...plan, swaths: [] } }).swaths.features;
      expect(g.map(x => x.properties?.kind)).toEqual(['work', 'work']);
    });
    it('changedSources reacts to the prescription and drives swaths', () => {
      const a = { ...base, plan };
      expect(changedSources(a, withVra)).toEqual(expect.arrayContaining(['vra-classes', 'swaths']));
      expect(changedSources(withVra, { ...withVra, hoveredSwath: 3 })).toEqual(['swaths']);
    });
    it('class-coloured swaths get a wider dark casing underneath; headland stays thinner', () => {
      const specs = layerSpecs() as any[];
      const ci = specs.findIndex(l => l.id === 'swaths-casing'); const li = specs.findIndex(l => l.id === 'swaths-line');
      expect(ci).toBeGreaterThanOrEqual(0); expect(ci).toBeLessThan(li);
      expect(specs[ci].source).toBe('swaths'); expect(specs[ci].type).toBe('line');
      expect(specs[ci].filter).toEqual(['has', 'color']);
      expect(specs[ci].paint['line-color']).toBe('#111827');
      const wc = specs[ci].paint['line-width']; const wl = specs[li].paint['line-width'];
      // [case, hovered, H, [==, kind, headland], Hc, Wc]
      expect(wc[5]).toBeGreaterThan(wl[5]); expect(wc[4]).toBeGreaterThan(wl[4]); expect(wc[4]).toBeLessThan(wc[5]);
    });
    it('vra class fills sit between zones-margin and swaths; the dose labels sit above the swaths', () => {
      const specs = layerSpecs() as any[];
      const ids = specs.map(l => l.source);
      const label = specs.findIndex((l) => l.id === 'vra-classes-label');
      expect(ids.indexOf('vra-classes')).toBeGreaterThan(ids.lastIndexOf('zones-margin'));
      expect(specs.findIndex((l) => l.id === 'vra-classes-line')).toBeLessThan(ids.indexOf('swaths'));
      expect(label).toBeGreaterThan(ids.lastIndexOf('swaths'));
    });
    it('dose labels are large, with a thick dark halo, and never dropped for overlap', () => {
      const l = (layerSpecs() as any[]).find((x) => x.id === 'vra-classes-label');
      expect(l.layout['text-size']).toBeGreaterThanOrEqual(14);
      expect(l.layout['text-allow-overlap']).toBe(true);
      expect(l.paint['text-halo-width']).toBeGreaterThanOrEqual(2.5);
    });
  });
});
