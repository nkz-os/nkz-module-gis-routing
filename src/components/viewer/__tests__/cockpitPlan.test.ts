import { describe, expect, it } from 'vitest';
import { planEntitySpecs } from '../cockpitPlan';
import { VRA_PALETTE, vraClassColors } from '../../../map/model';

const line = (c: number[][]) => ({ type: 'LineString', coordinates: c });
const sq = (o = 0): number[][] => [[o, 0], [o + 1, 0], [o + 1, 1], [o, 1], [o, 0]];
const f = (element: string, geometry: any, props: any = {}) =>
  ({ type: 'Feature', geometry, properties: { element, ...props } });
const fc = (features: any[]) => ({ type: 'FeatureCollection', features, properties: { plan_version: 1 } }) as any;

describe('planEntitySpecs', () => {
  it('draws every element of the plan', () => {
    const specs = planEntitySpecs(fc([
      f('route', line([[0, 0], [1, 1]])),
      f('swath', line([[0, 0], [1, 0]]), { index: 0 }),
      f('access_path', line([[0, 0], [0, 1]])),
      f('access_point', { type: 'Point', coordinates: [0, 0] }),
      f('exit_point', { type: 'Point', coordinates: [1, 1] }),
      f('exclusion_zone', { type: 'Polygon', coordinates: [sq()] }),
      f('parcel_boundary', { type: 'Polygon', coordinates: [sq()] }),
      f('working_area', { type: 'Polygon', coordinates: [sq()] }),
    ]));
    expect(specs.map((s) => s.element).sort()).toEqual([
      'access_path', 'access_point', 'exclusion_zone', 'exit_point', 'parcel_boundary', 'route', 'swath', 'working_area',
    ]);
    expect(new Set(specs.map((s) => s.id)).size).toBe(specs.length);
  });

  it('colours prescription polygons by class with the shared palette and labels the rate', () => {
    const specs = planEntitySpecs(fc([
      f('prescription_zone', { type: 'Polygon', coordinates: [sq(0)] }, { class_index: 0, rate: 40, unit: 'kg_ha' }),
      f('prescription_zone', { type: 'Polygon', coordinates: [sq(2)] }, { class_index: 1, rate: 80, unit: 'kg_ha' }),
    ]));
    const colors = vraClassColors(2);
    expect(specs[0].color).toBe(colors[0]);
    expect(specs[1].color).toBe(colors[1]);
    expect(VRA_PALETTE).toContain(specs[0].color);
    expect(specs[0].label).toBe('40 kg/ha');
    expect(specs[1].label).toBe('80 kg/ha');
    expect(specs[0].labelAt).toHaveLength(2);
  });

  it('survives a partial plan and unknown elements', () => {
    expect(planEntitySpecs(fc([f('route', line([[0, 0], [1, 1]])), f('mystery', null)]))).toHaveLength(1);
    expect(planEntitySpecs(fc([]))).toEqual([]);
    expect(planEntitySpecs(null as any)).toEqual([]);
  });

  it('keeps every part of a MultiPolygon and the holes', () => {
    const specs = planEntitySpecs(fc([f('exclusion_zone', {
      type: 'MultiPolygon', coordinates: [[sq(0)], [sq(5), sq(5).map(([x, y]) => [x + 0.2, y * 0.5 + 0.2])]],
    })]));
    expect(specs[0].polygons).toHaveLength(2);
    expect(specs[0].polygons![1].holes).toHaveLength(1);
  });
});
