import { describe, expect, it } from 'vitest';
import { noGoEntityOptions, noGoHoleEntities } from '../cesiumStyle';

const C: any = {
  Cartesian3: { fromDegrees: (...a: number[]) => ({ a }), fromDegreesArray: (a: number[]) => a },
  PolygonHierarchy: class { constructor(public p: any, public h: any) {} },
  Color: { fromCssColorString: (s: string) => ({ s, withAlpha: () => ({ s }) }) },
};
const outer = [[0, 0], [4, 0], [4, 4], [0, 4], [0, 0]];
const hole = [[1, 1], [2, 1], [2, 2], [1, 2], [1, 1]];

describe('NO-GO with holes', () => {
  it('hands Cesium the hole ring without its closing duplicate', () => {
    const e: any = noGoEntityOptions(C, 'z', { outer, holes: [hole] });
    expect(e.polygon.hierarchy.h[0].p).toHaveLength(8); // 4 vertices
  });
  it('gives every hole its own red border, so the inner edge is outlined too', () => {
    const borders = noGoHoleEntities(C, 'z', { outer, holes: [hole, hole] });
    expect(borders.map((b: any) => b.id)).toEqual(['z-hole-0', 'z-hole-1']);
    for (const b of borders as any[]) {
      expect(b.polyline.clampToGround).toBe(true);
      expect(b.polyline.width).toBeGreaterThanOrEqual(3);
      expect(b.polyline.positions).toHaveLength(10); // closed ring: 5 points
    }
  });
});
