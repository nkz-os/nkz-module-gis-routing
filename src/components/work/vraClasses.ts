import type { Distribution, VraClass } from '../../services/api';

export const MIN_CLASSES = 2;
export const MAX_CLASSES = 5;
export const HISTOGRAM_BINS = 10;

/** n contiguous classes covering 0-100 in equal parts; rates of the previous classes are kept by index. */
export function equalClasses(n: number, prev: readonly VraClass[] = []): VraClass[] {
  const k = Math.max(MIN_CLASSES, Math.min(MAX_CLASSES, Math.floor(n)));
  return Array.from({ length: k }, (_, i) => ({
    minPct: Math.round((i * 100) / k),
    maxPct: Math.round(((i + 1) * 100) / k),
    rate: prev[i]?.rate ?? null,
  }));
}

/** Move the cut between class `cut` and `cut + 1` to `value`; it never reaches a neighbouring cut (1 % gap). */
export function moveCut(classes: readonly VraClass[], cut: number, value: number): VraClass[] {
  const lo = classes[cut].minPct + 1;
  const hi = classes[cut + 1].maxPct - 1;
  const v = Math.max(lo, Math.min(hi, Math.round(value)));
  return classes.map((c, i) => {
    if (i === cut) return { ...c, maxPct: v };
    if (i === cut + 1) return { ...c, minPct: v };
    return c;
  });
}

/** Value at a percentile rank (0-100) from the 21 values p0..p100 in steps of 5; null when unavailable. */
export function valueAtPct(percentiles: readonly number[], pct: number): number | null {
  if (percentiles.length !== 21) return null;
  const pos = Math.max(0, Math.min(100, pct)) / 5;
  const lo = Math.floor(pos);
  const hi = Math.min(20, lo + 1);
  return percentiles[lo] + (percentiles[hi] - percentiles[lo]) * (pos - lo);
}

export interface HistogramBin { x0: number; x1: number; areaHa: number }

/** Area (ha) per value bin over the zones that have a value. */
export function histogramBins(distribution: Distribution, nBins = HISTOGRAM_BINS): HistogramBin[] {
  const zones = distribution.zones;
  if (zones.length === 0) return [];
  const min = Math.min(...zones.map((z) => z.mean));
  const max = Math.max(...zones.map((z) => z.mean));
  if (min === max) return [{ x0: min, x1: max, areaHa: zones.reduce((a, z) => a + z.area_ha, 0) }];
  const width = (max - min) / nBins;
  const bins: HistogramBin[] = Array.from({ length: nBins }, (_, i) => ({
    x0: min + i * width, x1: min + (i + 1) * width, areaHa: 0,
  }));
  for (const z of zones) {
    const i = Math.min(nBins - 1, Math.floor((z.mean - min) / width));
    bins[i].areaHa += z.area_ha;
  }
  return bins;
}
