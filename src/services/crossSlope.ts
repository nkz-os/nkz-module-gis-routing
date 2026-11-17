import type { PathAlternative } from './api';

/**
 * Stretches of a route whose cross slope (terrain tilt across the direction of travel)
 * exceeds the slope limit, as lon/lat lines over the elevation profile. Each run of points
 * above the limit is widened by one point on each side so a single point still draws a
 * segment; runs that then touch are merged. Missing fields (older backend) give [].
 */
export function crossSlopeZones(alt: PathAlternative, limit: number | null | undefined): number[][][] {
  const cross = alt.cross_slope_profile;
  const prof = alt.elevation_profile;
  if (limit == null || !cross || cross.length !== prof.length) return [];
  const runs: [number, number][] = [];
  for (let i = 0; i < cross.length; i++) {
    if (cross[i] <= limit) continue;
    const from = Math.max(0, i - 1);
    let j = i;
    while (j + 1 < cross.length && cross[j + 1] > limit) j++;
    const to = Math.min(cross.length - 1, j + 1);
    const last = runs[runs.length - 1];
    if (last && from <= last[1]) last[1] = to;
    else runs.push([from, to]);
    i = j;
  }
  return runs.map(([a, b]) => prof.slice(a, b + 1).map((p) => [p[0], p[1]]));
}

/** Point and value of the route's maximum cross slope; null when the backend did not send it. */
export function maxCrossSlopePoint(alt: PathAlternative): { at: number[]; deg: number } | null {
  if (!alt.max_cross_slope_at || alt.max_cross_slope_deg_found === undefined) return null;
  return { at: alt.max_cross_slope_at, deg: alt.max_cross_slope_deg_found };
}
