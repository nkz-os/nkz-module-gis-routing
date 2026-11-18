/**
 * Where the implement works relative to the tractor's turning point: the same rules as the
 * backend (coverage/machine_geometry.py). Frame ISO 11783-10: X forward, Y right, metres.
 * An absent value is a gap (listed in `missing`), a stored 0 is a value.
 */
export interface PairGeometry { d: number | null; e: number; missing: string[] }

const val = (m: any, key: string): number | null => {
  const v = m?.[key];
  if (v === null || v === undefined || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

export function pairGeometry(tractor: any | null, implement: any | null): PairGeometry | null {
  if (!tractor && !implement) return null;
  const working = implement ?? tractor;
  const missing: string[] = [];
  let hitch: number | null = 0;
  if (implement) {
    const front = String(implement.mountPosition || 'rear') === 'front';
    const key = front ? 'frontHitchOffsetX' : 'hitchOffsetX';
    hitch = val(tractor, key);
    if (hitch === null) missing.push(key);
  }
  const ox = val(working, 'implementOffsetX');
  if (ox === null) missing.push('implementOffsetX');
  if (tractor && val(tractor, 'trackWidth') === null && val(implement, 'trackWidth') === null) missing.push('trackWidth');
  return {
    d: hitch !== null && ox !== null ? hitch + ox : null,
    e: val(working, 'implementOffsetY') ?? 0,
    missing,
  };
}
