import { describe, expect, it } from 'vitest';
import { workReducer, initialWorkState, canGenerate, stepStatus, buildGenerateRequest } from '../workMachine';
const geom = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] } as const;
const loaded = (s = initialWorkState, requestId = 1) => workReducer(
  workReducer(s, { type: 'PARCEL_SELECTED', id: 'p1', requestId }),
  { type: 'PARCEL_LOADED', requestId, id: 'p1', name: 'P1', geometry: geom as any, config: { accessPoint: null, exclusionZones: null } });
const machineReady = (s: any) => workReducer(s, { type: 'MACHINE_CHANGED', machine: { widthM: 24, widthSource: 'manual', turningRadiusM: 6, radiusSource: 'manual' } });
const plan = (ok: boolean, warnings: any[] = []) => ({ success: true, operation_id: null, persisted: false,
  plan: { pattern: 'boustrophedon', validation: { ok, checks: [], fallbacks_applied: [], warnings }, route: { type: 'LineString', coordinates: [] }, swaths: [], metrics: {} } as any });

describe('workReducer', () => {
  it('starts empty and loads a parcel into configuring/zones', () => {
    expect(initialWorkState.phase).toBe('empty');
    const s = loaded();
    expect(s.phase).toBe('configuring'); expect(s.activeStep).toBe('zones'); expect(s.parcel?.id).toBe('p1');
  });
  it('ignores stale PARCEL_LOADED', () => {
    let s = workReducer(initialWorkState, { type: 'PARCEL_SELECTED', id: 'p1', requestId: 1 });
    s = workReducer(s, { type: 'PARCEL_SELECTED', id: 'p2', requestId: 2 });
    s = workReducer(s, { type: 'PARCEL_LOADED', requestId: 1, id: 'p1', name: 'P1', geometry: geom as any, config: { accessPoint: null, exclusionZones: null } });
    expect(s.parcel).toBeNull(); expect(s.phase).toBe('empty');
  });
  it('becomes ready only with width and radius and no blocking issue', () => {
    const s = loaded();
    expect(canGenerate(s)).toBe(false);
    const r = machineReady(s);
    expect(r.phase).toBe('ready'); expect(canGenerate(r)).toBe(true);
    const blocked = workReducer(r, { type: 'ACCESS_CHANGED', point: { type: 'Point', coordinates: [5, 5] }, issue: 'outside' });
    expect(blocked.phase).toBe('configuring'); expect(stepStatus(blocked, 'access')).toBe('warning');
  });
  it('GENERATED with ok=false → with_warnings; ok and no warnings → valid', () => {
    const r = workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' });
    expect(r.phase).toBe('generating');
    expect(workReducer(r, { type: 'GENERATED', response: plan(false) }).result?.kind).toBe('with_warnings');
    expect(workReducer(r, { type: 'GENERATED', response: plan(true, [{ code: 'MANUAL_TURN', geometry: null, params: {} }]) }).result?.kind).toBe('with_warnings');
    const v = workReducer(r, { type: 'GENERATED', response: plan(true) });
    expect(v.phase).toBe('generated'); expect(v.result?.kind).toBe('valid'); expect(v.stale).toBe(false);
  });
  it('a config change after generating marks the result stale and keeps it', () => {
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    const s = workReducer(g, { type: 'PATTERN_CHANGED', pattern: { pattern: 'snake' } });
    expect(s.phase).toBe('ready'); expect(s.stale).toBe(true); expect(s.result).not.toBeNull();
  });
  it('SAVE_RESULT persisted=false → failed(PERSIST_FAILED) keeping the plan', () => {
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    const s = workReducer(workReducer(g, { type: 'SAVE_REQUESTED' }), { type: 'SAVE_RESULT', response: { ...plan(true), persisted: false, operation_id: null } });
    expect(s.phase).toBe('failed'); expect(s.error?.code).toBe('PERSIST_FAILED'); expect(s.result).not.toBeNull();
    const ok = workReducer(workReducer(g, { type: 'SAVE_REQUESTED' }), { type: 'SAVE_RESULT', response: { ...plan(true), persisted: true, operation_id: 'urn:op:1' } });
    expect(ok.phase).toBe('saved'); expect(ok.result?.operationId).toBe('urn:op:1');
  });
  it('GENERATE_REQUESTED is ignored unless ready; DISMISS_ERROR returns to generated when a plan exists', () => {
    const c = loaded();
    expect(workReducer(c, { type: 'GENERATE_REQUESTED' }).phase).toBe('configuring');
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    const f = workReducer(workReducer(g, { type: 'SAVE_REQUESTED' }), { type: 'SAVE_FAILED', error: { code: 'ENGINE_FAILURE', detail: 'x', params: {} } });
    expect(workReducer(f, { type: 'DISMISS_ERROR' }).phase).toBe('generated');
  });
  it('buildGenerateRequest maps the state to the backend contract', () => {
    const r = machineReady(loaded());
    const body = buildGenerateRequest(workReducer(r, { type: 'PATTERN_CHANGED', pattern: { headingMode: 'manual', headingDeg: 45, headlandPasses: 2, returnToAccess: true } }), false);
    expect(body).toMatchObject({ parcel_id: 'p1', pattern: 'auto', persist: false, return_to_access: true,
      pattern_config: { width_m: 24, overlap_pct: 0, headland_passes: 2, heading_objective: 'efficiency', heading_deg: 45, turning_radius_m: 6 } });
    expect(buildGenerateRequest(r, true).pattern_config).not.toHaveProperty('heading_deg');
    expect(buildGenerateRequest(workReducer(r, { type: 'PATTERN_CHANGED', pattern: { headingMode: 'contour' } }), true).pattern_config.heading_objective).toBe('contour');
  });
  it('stepStatus: vra disabled, active step reported, zones warning on invalid polygon', () => {
    const s = machineReady(loaded());
    expect(stepStatus(s, 'vra')).toBe('disabled'); expect(stepStatus(s, 'zones')).toBe('active'); expect(stepStatus(s, 'parcel')).toBe('done');
    const z = workReducer(s, { type: 'ZONES_CHANGED', zones: [{ id: 'z1', polygon: geom as any, areaHa: 1, valid: false }] });
    expect(stepStatus(z, 'zones')).toBe('warning'); expect(canGenerate(z)).toBe(false);
  });
});
