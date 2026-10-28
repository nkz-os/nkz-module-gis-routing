import type {
  Distribution, GenerateRequest, GenerateResponse, ParcelConfig, Plan, Prescription, VraConfig, VraRequest,
} from '../services/api';
import { featureCollectionToZones, type Zone } from '../services/geo';

export type StepId = 'parcel' | 'zones' | 'access' | 'machine' | 'pattern' | 'vra';
export type Phase =
  | 'empty' | 'parcel_loaded' | 'configuring' | 'ready'
  | 'generating' | 'generated' | 'saving' | 'saved' | 'failed';

export interface MachineConfig {
  tractorId: string | null;
  implementId: string | null;
  operationType: string;
  widthM: number | null;
  widthSource: 'machine' | 'manual' | null;
  turningRadiusM: number | null;
  radiusSource: 'machine' | 'manual' | null;
  overlapPct: number;
}

export interface PatternConfig {
  pattern: 'auto' | 'boustrophedon' | 'snake' | 'spiral' | 'headland-only';
  headingMode: 'auto' | 'contour' | 'manual';
  headingDeg: number;
  headlandPasses: 1 | 2 | 3;
  returnToAccess: boolean;
}

export interface VraState {
  config: VraConfig;
  distribution: Distribution | null;
  prescription: Prescription | null;
  status: 'idle' | 'loading' | 'ready' | 'error';
  /** Id of the latest prescription request; older in-flight results are ignored. */
  requestId: number;
  error: { code: string; detail: string; params: Record<string, unknown> } | null;
}

export interface WorkState {
  phase: Phase;
  activeStep: StepId;
  stale: boolean;
  parcel: { id: string; name: string; geometry: GeoJSON.Polygon } | null;
  parcelRequestId: number;
  zones: Zone[];
  accessPoint: GeoJSON.Point | null;
  accessIssue: 'outside' | 'in_zone' | null;
  machine: MachineConfig;
  pattern: PatternConfig;
  result: {
    plan: Plan; kind: 'valid' | 'with_warnings'; operationId: string | null;
    /** Stored plan this result displays; Save persists it by id. */
    planId: string | null;
    /** VRA request the plan was generated with (null = none); Save regenerates when it differs. */
    vraKey: string | null;
  } | null;
  /** vraKey of the generate request in flight. */
  generatingVraKey: string | null;
  vra: VraState;
  error: { code: string; detail: string; params: Record<string, unknown> } | null;
}

export type WorkEvent =
  | { type: 'PARCEL_SELECTED'; id: string; requestId: number }
  | { type: 'PARCEL_LOADED'; requestId: number; id: string; name: string; geometry: GeoJSON.Polygon; config: ParcelConfig }
  | { type: 'STEP_ACTIVATED'; step: StepId }
  | { type: 'ZONES_CHANGED'; zones: Zone[] }
  | { type: 'ACCESS_CHANGED'; point: GeoJSON.Point | null; issue: 'outside' | 'in_zone' | null }
  | { type: 'MACHINE_CHANGED'; machine: Partial<MachineConfig> }
  | { type: 'PATTERN_CHANGED'; pattern: Partial<PatternConfig> }
  | { type: 'VRA_CONFIG_CHANGED'; config: Partial<VraConfig> }
  | { type: 'VRA_REQUESTED'; parcelRequestId: number; requestId: number }
  | { type: 'VRA_DISTRIBUTION_LOADED'; parcelRequestId: number; distribution: Distribution }
  | { type: 'VRA_PRESCRIPTION_RESULT'; parcelRequestId: number; requestId: number; prescription: Prescription }
  | { type: 'VRA_FAILED'; parcelRequestId: number; requestId?: number; error: NonNullable<WorkState['error']> }
  | { type: 'GENERATE_REQUESTED' }
  | { type: 'GENERATED'; response: GenerateResponse }
  | { type: 'GENERATE_FAILED'; error: WorkState['error'] }
  | { type: 'SAVE_REQUESTED' }
  | { type: 'SAVE_RESULT'; operationId: string; regenerated?: GenerateResponse }
  | { type: 'SAVE_FAILED'; error: WorkState['error'] }
  | { type: 'DISMISS_ERROR' };

export const initialVraState: VraState = {
  config: {
    enabled: false, source: 'orion', variable: 'NDVI', unit: 'kg_ha', product: '',
    classes: [
      { minPct: 0, maxPct: 33, rate: null },
      { minPct: 33, maxPct: 67, rate: null },
      { minPct: 67, maxPct: 100, rate: null },
    ],
  },
  distribution: null, prescription: null, status: 'idle', requestId: 0, error: null,
};

export const initialWorkState: WorkState = {
  phase: 'empty',
  activeStep: 'parcel',
  stale: false,
  parcel: null,
  parcelRequestId: 0,
  zones: [],
  accessPoint: null,
  accessIssue: null,
  machine: {
    tractorId: null, implementId: null, operationType: 'spraying',
    widthM: null, widthSource: null, turningRadiusM: null, radiusSource: null, overlapPct: 0,
  },
  pattern: { pattern: 'auto', headingMode: 'auto', headingDeg: 0, headlandPasses: 1, returnToAccess: false },
  result: null,
  generatingVraKey: null,
  vra: initialVraState,
  error: null,
};

export function canGenerate(s: WorkState): boolean {
  return (
    s.parcel !== null &&
    (s.machine.widthM ?? 0) > 0 &&
    (s.machine.turningRadiusM ?? 0) > 0 &&
    s.accessIssue === null &&
    s.zones.every((z) => z.valid) &&
    s.phase !== 'generating' &&
    s.phase !== 'saving'
  );
}

// Phases in which configuration edits are accepted.
// ASSUMPTION: 'saved' behaves like 'generated' (editing after save makes the result stale).
const EDITABLE: ReadonlySet<Phase> = new Set<Phase>(['configuring', 'ready', 'generated', 'failed', 'saved']);

function afterEdit(prev: WorkState, next: WorkState): WorkState {
  if (!EDITABLE.has(prev.phase)) return prev;
  const phase: Phase = canGenerate(next) ? 'ready' : 'configuring';
  return { ...next, phase, stale: prev.result !== null ? true : next.stale, error: null };
}

function resultFrom(response: GenerateResponse, vraKey: string | null): NonNullable<WorkState['result']> {
  const v = response.plan.validation;
  const clean = v !== null && v.ok && v.warnings.length === 0;
  return {
    plan: response.plan, kind: clean ? 'valid' : 'with_warnings', operationId: response.operation_id,
    planId: response.plan_id ?? null, vraKey,
  };
}

/** The VRA request a generate would carry now (see buildGenerateRequest), serialised for comparison. */
export function currentVraKey(s: WorkState): string | null {
  const vra = s.vra.prescription !== null ? toVraRequest(s.vra.config) : null;
  return vra ? JSON.stringify(vra) : null;
}

/** True when the stored plan was generated with a different VRA than the one on screen. */
export function savedPlanVraDiffers(s: WorkState): boolean {
  return s.result !== null && s.result.vraKey !== currentVraKey(s);
}

// Request form of the VRA config, or null when disabled or any rate is not a number >= 0.
export function toVraRequest(c: VraConfig): VraRequest | null {
  if (!c.enabled) return null;
  if (c.source === 'external' && !c.externalFeatures) return null;
  const ok = c.classes.length > 0
    && c.classes.every((k) => typeof k.rate === 'number' && Number.isFinite(k.rate) && k.rate >= 0);
  if (!ok) return null;
  return {
    enabled: true, source: c.source, variable: c.variable, unit: c.unit, product: c.product,
    // Inversion is applied to the entered rates (StepVra); the backend never inverts.
    invert: false,
    classes: c.classes.map((k) => ({
      min_pct: k.minPct, max_pct: k.maxPct, rate: k.rate as number, ...(k.label ? { label: k.label } : {}),
    })),
    ...(c.source === 'external' && c.externalFeatures ? { external_features: c.externalFeatures } : {}),
  };
}

/**
 * Why Save would drop or misstate the VRA, or null when it is safe: enabled but incomplete
 * (a rate missing, external source without features), or enabled and complete but with no
 * prescription yet (still computing or failed). Never save a plan without the VRA the user sees.
 */
export function vraSaveBlocker(s: WorkState): 'incomplete' | 'pending' | null {
  if (!s.vra.config.enabled) return null;
  if (toVraRequest(s.vra.config) === null) return 'incomplete';
  return s.vra.prescription === null ? 'pending' : null;
}

function withPlanPrescription(s: WorkState, plan: Plan): VraState {
  const prescription = plan.prescription ?? null;
  return { ...s.vra, prescription, status: prescription ? 'ready' : 'idle', error: null };
}

// A new parcel keeps the user's classes/rates but never the previous parcel's external zones.
function vraForNewParcel(v: VraState): VraState {
  return {
    ...initialVraState, requestId: v.requestId,
    config: { ...v.config, source: 'orion', externalFeatures: undefined },
  };
}

export function workReducer(state: WorkState, event: WorkEvent): WorkState {
  switch (event.type) {
    case 'PARCEL_SELECTED':
      return {
        ...state, phase: 'empty', activeStep: 'parcel', parcelRequestId: event.requestId,
        parcel: null, result: null, error: null, stale: false,
        vra: vraForNewParcel(state.vra),
      };
    case 'PARCEL_LOADED': {
      if (event.requestId !== state.parcelRequestId) return state;
      return {
        ...state, phase: 'configuring', activeStep: 'zones', stale: false,
        parcel: { id: event.id, name: event.name, geometry: event.geometry },
        zones: featureCollectionToZones(event.config.exclusionZones),
        accessPoint: event.config.accessPoint, accessIssue: null,
        result: null, error: null, vra: vraForNewParcel(state.vra),
      };
    }
    case 'STEP_ACTIVATED':
      return { ...state, activeStep: event.step };
    case 'ZONES_CHANGED':
      return afterEdit(state, { ...state, zones: [...event.zones] });
    case 'ACCESS_CHANGED':
      return afterEdit(state, { ...state, accessPoint: event.point, accessIssue: event.issue });
    case 'MACHINE_CHANGED':
      return afterEdit(state, { ...state, machine: { ...state.machine, ...event.machine } });
    case 'PATTERN_CHANGED':
      return afterEdit(state, { ...state, pattern: { ...state.pattern, ...event.pattern } });
    case 'VRA_CONFIG_CHANGED': {
      // Deliberately not an "edit": changing the VRA config never marks the route stale.
      const config = { ...state.vra.config, ...event.config };
      const status = state.vra.status === 'error' ? 'idle' : state.vra.status;
      const sameCount = config.classes.length === state.vra.config.classes.length;
      if (config.enabled && toVraRequest(config) !== null && sameCount) {
        return { ...state, vra: { ...state.vra, config, error: null, status } };
      }
      // Disabled, incomplete or a different class count: what Save would send is "no VRA", so no prescription may stay
      // visible, and a result still in flight must be ignored (new requestId).
      return { ...state, vra: { ...state.vra, config, error: null, prescription: null,
        requestId: state.vra.requestId + 1, status: status === 'loading' ? 'idle' : status } };
    }
    case 'VRA_REQUESTED':
      if (event.parcelRequestId !== state.parcelRequestId) return state;
      return { ...state, vra: { ...state.vra, requestId: event.requestId, status: 'loading', error: null } };
    case 'VRA_DISTRIBUTION_LOADED':
      if (event.parcelRequestId !== state.parcelRequestId) return state;
      return { ...state, vra: { ...state.vra, distribution: event.distribution } };
    case 'VRA_PRESCRIPTION_RESULT':
      if (event.parcelRequestId !== state.parcelRequestId || event.requestId !== state.vra.requestId) return state;
      return { ...state, vra: { ...state.vra, prescription: event.prescription, status: 'ready', error: null } };
    case 'VRA_FAILED':
      if (event.parcelRequestId !== state.parcelRequestId) return state;
      if (event.requestId !== undefined && event.requestId !== state.vra.requestId) return state;
      return { ...state, vra: { ...state.vra, status: 'error', error: event.error } };
    case 'GENERATE_REQUESTED':
      // Any non-busy phase with a complete configuration may (re)generate.
      if (!canGenerate(state)) return state;
      return { ...state, phase: 'generating', error: null, generatingVraKey: currentVraKey(state) };
    case 'GENERATED':
      if (state.phase !== 'generating') return state;
      return {
        ...state, phase: 'generated', stale: false, result: resultFrom(event.response, state.generatingVraKey), error: null,
        vra: withPlanPrescription(state, event.response.plan),
      };
    case 'GENERATE_FAILED':
      if (state.phase !== 'generating') return state;
      return { ...state, phase: 'failed', error: event.error };
    case 'SAVE_REQUESTED':
      if (state.phase !== 'generated' || vraSaveBlocker(state) !== null) return state;
      return { ...state, phase: 'saving', error: null };
    case 'SAVE_RESULT': {
      if (state.phase !== 'saving' || state.result === null) return state;
      const { regenerated, operationId } = event;
      // A regenerated plan (VRA changed after generating) replaces the displayed one: it is the one stored.
      const result = regenerated
        ? { ...resultFrom(regenerated, currentVraKey(state)), operationId }
        : { ...state.result, operationId };
      return {
        ...state, phase: 'saved', stale: false, result, error: null,
        vra: regenerated ? withPlanPrescription(state, regenerated.plan) : state.vra,
      };
    }
    case 'SAVE_FAILED':
      if (state.phase !== 'saving') return state;
      return { ...state, phase: 'failed', error: event.error };
    case 'DISMISS_ERROR': {
      if (state.phase !== 'failed') return state;
      const phase: Phase = state.result ? 'generated' : canGenerate(state) ? 'ready' : 'configuring';
      return { ...state, phase, error: null };
    }
    default: {
      const _exhaustive: never = event;
      return _exhaustive;
    }
  }
}

export function stepStatus(
  s: WorkState,
  step: StepId,
): 'pending' | 'active' | 'done' | 'warning' | 'disabled' | 'complete' | 'optional' {
  if (step === 'vra') {
    if (s.result === null) return 'disabled';
    if (!s.vra.config.enabled) return 'optional';
    return s.vra.prescription !== null && toVraRequest(s.vra.config) !== null ? 'complete' : 'pending';
  }
  if (step === 'zones' && s.zones.some((z) => !z.valid)) return 'warning';
  if (step === 'access' && s.accessIssue !== null) return 'warning';
  if (s.activeStep === step) return 'active';
  if (s.parcel === null) return 'pending';
  switch (step) {
    case 'parcel':
    case 'pattern':
      return 'done';
    case 'zones':
      return s.zones.length > 0 ? 'done' : 'pending';
    case 'access':
      return s.accessPoint !== null ? 'done' : 'pending';
    case 'machine':
      return (s.machine.widthM ?? 0) > 0 && (s.machine.turningRadiusM ?? 0) > 0 ? 'done' : 'pending';
    default: {
      const _exhaustive: never = step;
      return _exhaustive;
    }
  }
}

/**
 * Build the request from the state BEFORE dispatching GENERATE_REQUESTED/SAVE_REQUESTED:
 * once the phase is generating/saving, canGenerate is false and this throws.
 */
export function buildGenerateRequest(s: WorkState, persist: boolean): GenerateRequest {
  if (!canGenerate(s) || s.parcel === null) throw new Error('not ready');
  const { machine, pattern, parcel } = s;
  // Only when a prescription exists for the current plan: a parcel change must not lock generation.
  const vra = s.vra.prescription !== null ? toVraRequest(s.vra.config) : null;
  return {
    parcel_geometry: parcel.geometry,
    parcel_id: parcel.id,
    tractor_id: machine.tractorId,
    implement_id: machine.implementId,
    pattern: pattern.pattern,
    pattern_config: {
      width_m: machine.widthM!,
      overlap_pct: machine.overlapPct,
      headland_passes: pattern.headlandPasses,
      heading_objective: pattern.headingMode === 'contour' ? 'contour' : 'efficiency',
      turning_radius_m: machine.turningRadiusM!,
      ...(pattern.headingMode === 'manual' ? { heading_deg: pattern.headingDeg } : {}),
    },
    operation_type: machine.operationType,
    return_to_access: pattern.returnToAccess,
    persist,
    ...(vra ? { vra } : {}),
  };
}
