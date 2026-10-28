import type { PathAlternative, PathAlternativeId, PathRequest } from '../services/api';

export type LonLat = [number, number];

export const DEFAULT_MAX_SLOPE_DEG = 15;
export const MAX_SLOPE_LIMIT_DEG = 45;

export interface TransitError { code: string; detail: string; params: Record<string, unknown> }

export interface TransitResult {
  jobId: string;
  alternatives: PathAlternative[];
  report: { max_slope_deg_found?: number; search_margin_m?: number; warnings?: { code: string; params?: Record<string, unknown> }[] };
}

export type TransitPhase = 'idle' | 'calculating' | 'ready' | 'failed' | 'saving';

export interface TransitState {
  a: LonLat | null;
  b: LonLat | null;
  machineId: string | null;
  widthM: number | null;
  maxSlopeDeg: number;
  /** Map click target: the next click places this point. */
  picking: 'a' | 'b' | null;
  phase: TransitPhase;
  jobStatus: 'queued' | 'running' | null;
  result: TransitResult | null;
  selected: PathAlternativeId | null;
  /** The inputs changed after the result was computed. */
  stale: boolean;
  error: TransitError | null;
  parcelId: string | null;
  /** The user picked the parcel (an automatic default no longer overrides it). */
  parcelManual: boolean;
  /** Saved operation id per alternative of the current result. */
  saved: Partial<Record<PathAlternativeId, string>>;
  /** Destination parcel each saved route was saved for: a route may be saved again for another parcel. */
  savedParcel: Partial<Record<PathAlternativeId, string>>;
}

export type TransitEvent =
  | { type: 'PICK'; which: 'a' | 'b' | null }
  | { type: 'POINT_SET'; which: 'a' | 'b'; point: LonLat | null }
  | { type: 'MACHINE_SET'; machineId: string | null; widthM: number | null }
  | { type: 'WIDTH_SET'; widthM: number | null }
  | { type: 'SLOPE_SET'; maxSlopeDeg: number }
  | { type: 'CALC_STARTED' }
  | { type: 'JOB_STATUS'; status: 'queued' | 'running' }
  | { type: 'CALC_DONE'; result: TransitResult }
  | { type: 'CALC_FAILED'; error: TransitError }
  | { type: 'SELECT'; id: PathAlternativeId }
  | { type: 'PARCEL_SET'; parcelId: string | null; auto?: boolean }
  | { type: 'SAVE_STARTED' }
  | { type: 'SAVE_DONE'; operationId: string }
  | { type: 'SAVE_FAILED'; error: TransitError }
  | { type: 'DISMISS_ERROR' };

export const initialTransitState: TransitState = {
  a: null, b: null, machineId: null, widthM: null, maxSlopeDeg: DEFAULT_MAX_SLOPE_DEG,
  picking: null, phase: 'idle', jobStatus: null, result: null, selected: null, stale: false,
  error: null, parcelId: null, parcelManual: false, saved: {}, savedParcel: {},
};

const busy = (s: TransitState) => s.phase === 'calculating' || s.phase === 'saving';
const same = (p: LonLat | null, q: LonLat | null) => (p === null || q === null ? p === q : p[0] === q[0] && p[1] === q[1]);

/** An input that feeds the calculation changed: the shown result no longer answers it. */
function inputsChanged(s: TransitState): TransitState {
  if (s.phase === 'failed') return { ...s, phase: 'idle', error: null, jobStatus: null };
  return s.result ? { ...s, stale: true } : s;
}

export function validSlope(deg: number): boolean {
  return Number.isFinite(deg) && deg > 0 && deg <= MAX_SLOPE_LIMIT_DEG;
}

export function canCalculate(s: TransitState): boolean {
  return s.a !== null && s.b !== null && s.widthM !== null && s.widthM > 0 && validSlope(s.maxSlopeDeg) && !busy(s);
}

export function canSave(s: TransitState): boolean {
  return s.phase === 'ready' && !s.stale && s.result !== null && s.selected !== null &&
    s.parcelId !== null &&
    (s.saved[s.selected] === undefined || s.savedParcel[s.selected] !== s.parcelId);
}

export function transitReducer(s: TransitState, e: TransitEvent): TransitState {
  switch (e.type) {
    case 'PICK':
      return busy(s) ? s : { ...s, picking: e.which };
    case 'POINT_SET': {
      if (busy(s)) return s;
      if (same(s[e.which], e.point)) return { ...s, picking: null };
      return inputsChanged({ ...s, [e.which]: e.point, picking: null });
    }
    case 'MACHINE_SET': {
      if (busy(s)) return s;
      if (s.machineId === e.machineId && s.widthM === e.widthM) return s;
      return inputsChanged({ ...s, machineId: e.machineId, widthM: e.widthM });
    }
    case 'WIDTH_SET': {
      if (busy(s) || s.widthM === e.widthM) return s;
      // A hand-typed width no longer describes the picked machine.
      return inputsChanged({ ...s, widthM: e.widthM, machineId: null });
    }
    case 'SLOPE_SET': {
      if (busy(s) || s.maxSlopeDeg === e.maxSlopeDeg) return s;
      return inputsChanged({ ...s, maxSlopeDeg: e.maxSlopeDeg });
    }
    case 'CALC_STARTED':
      if (!canCalculate(s)) return s;
      return { ...s, phase: 'calculating', jobStatus: 'queued', result: null, selected: null, stale: false, error: null, saved: {}, savedParcel: {}, picking: null };
    case 'JOB_STATUS':
      return s.phase === 'calculating' ? { ...s, jobStatus: e.status } : s;
    case 'CALC_DONE': {
      if (s.phase !== 'calculating') return s;
      const first = e.result.alternatives[0]?.id ?? null;
      return { ...s, phase: 'ready', jobStatus: null, result: e.result, selected: first, stale: false, error: null };
    }
    case 'CALC_FAILED':
      return s.phase === 'calculating' ? { ...s, phase: 'failed', jobStatus: null, error: e.error } : s;
    case 'SELECT':
      return s.result?.alternatives.some((a) => a.id === e.id) && !busy(s) ? { ...s, selected: e.id } : s;
    case 'PARCEL_SET':
      if (e.auto && s.parcelManual) return s;
      return { ...s, parcelId: e.parcelId, parcelManual: e.auto ? s.parcelManual : true };
    case 'SAVE_STARTED':
      return canSave(s) ? { ...s, phase: 'saving', error: null } : s;
    case 'SAVE_DONE':
      return s.phase === 'saving' && s.selected ? { ...s, phase: 'ready', saved: { ...s.saved, [s.selected]: e.operationId },
        savedParcel: { ...s.savedParcel, [s.selected]: s.parcelId ?? '' } } : s;
    case 'SAVE_FAILED':
      return s.phase === 'saving' ? { ...s, phase: 'ready', error: e.error } : s;
    case 'DISMISS_ERROR':
      return s.error ? { ...s, error: null, phase: s.phase === 'failed' ? 'idle' : s.phase } : s;
    default:
      return s;
  }
}

export function buildPathRequest(s: TransitState): PathRequest | null {
  if (!canCalculate(s) || !s.a || !s.b || s.widthM === null) return null;
  const req: PathRequest = { point_a: s.a, point_b: s.b, machine_width_m: s.widthM, max_slope_deg: s.maxSlopeDeg };
  if (s.machineId) req.machine_id = s.machineId;
  return req;
}
