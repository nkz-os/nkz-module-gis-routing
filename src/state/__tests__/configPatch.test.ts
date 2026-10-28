import { describe, expect, it } from 'vitest';
import { buildConfigPatch } from '../configPatch';

const z = (id: string, o = 0) => ({ id, ring: [[o, 0], [o + 1, 0], [o + 1, 1], [o, 0]] });

describe('buildConfigPatch', () => {
  it('sends only the gate when only the gate changed', () => {
    const p = buildConfigPatch({ gate: null, zones: [z('a')] }, { gate: [1, 2], zones: [z('a')] });
    expect(p).toEqual({ accessPoint: { type: 'Point', coordinates: [1, 2] } });
    expect('exclusionZones' in p).toBe(false);
  });

  it('sends only the zones when only the zones changed', () => {
    const p = buildConfigPatch({ gate: [1, 2], zones: [z('a')] }, { gate: [1, 2], zones: [z('a'), z('b', 3)] });
    expect('accessPoint' in p).toBe(false);
    expect(p.exclusionZones!.features).toHaveLength(2);
  });

  it('sends an empty collection only when the user deleted every zone', () => {
    const p = buildConfigPatch({ gate: null, zones: [z('a')] }, { gate: null, zones: [] });
    expect(p).toEqual({ exclusionZones: { type: 'FeatureCollection', features: [] } });
  });

  it('never sends an empty collection when there were no zones', () => {
    expect(buildConfigPatch({ gate: null, zones: [] }, { gate: [1, 2], zones: [] }))
      .toEqual({ accessPoint: { type: 'Point', coordinates: [1, 2] } });
  });

  it('sends an explicit null when the gate was removed', () => {
    const p = buildConfigPatch({ gate: [1, 2], zones: [] }, { gate: null, zones: [] });
    expect(p).toEqual({ accessPoint: null });
  });

  it('is empty when nothing changed', () => {
    expect(buildConfigPatch({ gate: [1, 2], zones: [z('a')] }, { gate: [1, 2], zones: [z('a')] })).toEqual({});
  });

  it('keeps the original geometry of untouched MultiPolygon zones when zones change', () => {
    const geometry = { type: 'MultiPolygon' as const, coordinates: [[z('a').ring], [z('b', 5).ring]] };
    const p = buildConfigPatch({ gate: null, zones: [] }, { gate: null, zones: [{ id: 'a', ring: z('a').ring, geometry }, z('c', 9)] });
    expect(p.exclusionZones!.features[0].geometry).toEqual(geometry);
    expect(p.exclusionZones!.features[1].geometry.type).toBe('Polygon');
  });
});
