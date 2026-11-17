import { describe, expect, it } from 'vitest';
import { crossSlopeZones, maxCrossSlopePoint } from '../crossSlope';
import type { PathAlternative } from '../api';

const prof = (n: number) => Array.from({ length: n }, (_, i) => [i, 0, 100]);
const alt = (cross: number[] | undefined, at?: number[]): PathAlternative => ({
  id: 'fastest', label: 'f', distance_m: 1, cumulative_climb_m: 0,
  geometry: { type: 'LineString', coordinates: [[0, 0], [cross ? cross.length - 1 : 1, 0]] },
  elevation_profile: prof(cross ? cross.length : 2),
  ...(cross ? { cross_slope_profile: cross } : {}),
  ...(at ? { max_cross_slope_at: at, max_cross_slope_deg_found: Math.max(...(cross ?? [0])) } : {}),
});

describe('crossSlopeZones', () => {
  it('returns each run above the limit, widened by one point on each side', () => {
    const z = crossSlopeZones(alt([1, 2, 20, 21, 3, 4, 30, 5]), 15);
    expect(z).toEqual([[[1, 0], [2, 0], [3, 0], [4, 0]], [[5, 0], [6, 0], [7, 0]]]);
  });
  it('clamps the widening at both ends of the route', () => {
    expect(crossSlopeZones(alt([20, 1, 1, 25]), 15)).toEqual([[[0, 0], [1, 0]], [[2, 0], [3, 0]]]);
  });
  it('merges runs that touch after widening', () => {
    expect(crossSlopeZones(alt([1, 20, 1, 20, 1]), 15)).toEqual([[[0, 0], [1, 0], [2, 0], [3, 0], [4, 0]]]);
  });
  it('is empty at or below the limit, without a limit, or without the profile (older backend)', () => {
    expect(crossSlopeZones(alt([15, 15]), 15)).toEqual([]);
    expect(crossSlopeZones(alt([20, 20]), null)).toEqual([]);
    expect(crossSlopeZones(alt(undefined), 15)).toEqual([]);
  });
  it('ignores a profile whose length does not match the elevation profile', () => {
    const a = { ...alt([20, 20, 20]), elevation_profile: prof(2) };
    expect(crossSlopeZones(a, 15)).toEqual([]);
  });
});

describe('maxCrossSlopePoint', () => {
  it('returns the point and value of the maximum', () => {
    expect(maxCrossSlopePoint(alt([1, 22.4, 3], [1, 0]))).toEqual({ at: [1, 0], deg: 22.4 });
  });
  it('is null without the fields (older backend)', () => {
    expect(maxCrossSlopePoint(alt(undefined))).toBeNull();
  });
});
