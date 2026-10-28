import { describe, expect, it } from 'vitest';
import { areaHa, isValidPolygon, ringToPolygon, zonesToFeatureCollection, featureCollectionToZones, bboxOf } from '../geo';
const sq = (x0: number, y0: number, x1: number, y1: number) => ringToPolygon([[x0, y0], [x1, y0], [x1, y1], [x0, y1]]);
describe('geo', () => {
  it('closes rings and measures area in hectares', () => {
    const p = sq(-2.0, 43.0, -1.99877, 43.0009);       // ≈100 m × 100 m
    expect(p.coordinates[0][0]).toEqual(p.coordinates[0][4]);
    expect(areaHa(p)).toBeGreaterThan(0.95); expect(areaHa(p)).toBeLessThan(1.05);
  });
  it('flags a bow-tie as invalid', () => {
    expect(isValidPolygon(ringToPolygon([[0, 0], [1, 1], [1, 0], [0, 1]]))).toBe(false);
    expect(isValidPolygon(sq(0, 0, 1, 1))).toBe(true);
  });
  it('round-trips zones through a FeatureCollection keeping ids and dropping non-polygons', () => {
    const fc = zonesToFeatureCollection([{ id: 'a', polygon: sq(0, 0, 1, 1), areaHa: 1, valid: true }]);
    fc.features.push({ type: 'Feature', properties: { id: 'pt' }, geometry: { type: 'Point', coordinates: [0, 0] } } as any);
    const zones = featureCollectionToZones(fc);
    expect(zones.map(z => z.id)).toEqual(['a']);
    expect(featureCollectionToZones(null)).toEqual([]);
  });
  it('bbox of a polygon', () => { expect(bboxOf(sq(0, 1, 2, 3))).toEqual([0, 1, 2, 3]); });
});
