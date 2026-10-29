import { describe, expect, it } from 'vitest';
import { gateEntityOptions, noGoEntityOptions, noGoHoleEntities } from '../cesiumStyle';

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

describe('markers sit on the terrain', () => {
  const CG: any = {
    ...C,
    HeightReference: { CLAMP_TO_GROUND: 'clamp' },
    VerticalOrigin: { BOTTOM: 'b', TOP: 't', CENTER: 'c' },
    Cartesian2: class { constructor(public x: number, public y: number) {} },
  };
  // A position at ellipsoid height 0 under terrain hundreds of metres high is drawn far from
  // the clicked spot once the camera tilts (depth test is off): clamp icon and label to the ground.
  it('clamps the gate icon and its label to the ground', () => {
    const e: any = gateEntityOptions(CG, 'g', -1.6, 42.8, 'Portón');
    expect(e.billboard.heightReference).toBe('clamp');
    expect(e.label.heightReference).toBe('clamp');
  });
  it('clamps the NO-GO label to the ground', () => {
    const e: any = noGoEntityOptions(CG, 'z', { outer, holes: [] }, [2, 2], 'NO-GO');
    expect(e.label.heightReference).toBe('clamp');
  });
});
