import { describe, expect, it } from 'vitest';
import { workReducer, initialWorkState, canGenerate, stepStatus, buildGenerateRequest, vraSaveBlocker, savedPlanVraDiffers } from '../workMachine';
const geom = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] } as const;
const loaded = (s = initialWorkState, requestId = 1) => workReducer(
  workReducer(s, { type: 'PARCEL_SELECTED', id: 'p1', requestId }),
  { type: 'PARCEL_LOADED', requestId, id: 'p1', name: 'P1', geometry: geom as any, config: { accessPoint: null, exclusionZones: null } });
const machineReady = (s: any) => workReducer(s, { type: 'MACHINE_CHANGED', machine: { widthM: 24, widthSource: 'manual', turningRadiusM: 6, radiusSource: 'manual' } });
const plan = (ok: boolean, warnings: any[] = []) => ({ success: true, operation_id: null, persisted: false, plan_id: 'plan-1',
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
  it('SAVE_RESULT keeps the displayed plan and records the operation id and its plan id', () => {
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    expect(g.result?.planId).toBe('plan-1');
    const s = workReducer(workReducer(g, { type: 'SAVE_REQUESTED' }), { type: 'SAVE_RESULT', operationId: 'urn:op:1' });
    expect(s.phase).toBe('saved'); expect(s.result?.operationId).toBe('urn:op:1');
    expect(s.result?.plan).toBe(g.result?.plan); expect(s.result?.planId).toBe('plan-1');
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

  it('GENERATED after PARCEL_SELECTED is ignored', () => {
    const g = workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' });
    const s = workReducer(workReducer(g, { type: 'PARCEL_SELECTED', id: 'p2', requestId: 2 }), { type: 'GENERATED', response: plan(true) });
    expect(s.phase).toBe('empty'); expect(s.result).toBeNull();
  });
  it('SAVE_RESULT outside saving is ignored', () => {
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    const s = workReducer(g, { type: 'SAVE_RESULT', operationId: 'urn:op:1' });
    expect(s).toBe(g);
  });
  it('buildGenerateRequest throws once generating', () => {
    const g = workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' });
    expect(() => buildGenerateRequest(g, false)).toThrow('not ready');
  });
  it('GENERATED with validation null → with_warnings', () => {
    const g = workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' });
    const r = plan(true); (r.plan as any).validation = null;
    expect(workReducer(g, { type: 'GENERATED', response: r }).result?.kind).toBe('with_warnings');
  });
  it('generated → invalid zone → configuring, stale, result kept', () => {
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    const s = workReducer(g, { type: 'ZONES_CHANGED', zones: [{ id: 'z1', polygon: geom as any, areaHa: 1, valid: false }] });
    expect(s.phase).toBe('configuring'); expect(s.stale).toBe(true); expect(s.result).not.toBeNull();
  });
  it('an edit from failed clears the error', () => {
    const g = workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' });
    const f = workReducer(g, { type: 'GENERATE_FAILED', error: { code: 'X', detail: 'x', params: {} } });
    expect(workReducer(f, { type: 'PATTERN_CHANGED', pattern: { pattern: 'snake' } }).error).toBeNull();
  });
  it('GENERATE_REQUESTED also starts from generated, saved and failed (single source for the button)', () => {
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    expect(workReducer(g, { type: 'GENERATE_REQUESTED' }).phase).toBe('generating');
    const f = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATE_FAILED', error: { code: 'ENGINE_FAILURE', detail: '', params: {} } });
    expect(f.phase).toBe('failed');
    const again = workReducer(f, { type: 'GENERATE_REQUESTED' });
    expect(again.phase).toBe('generating'); expect(again.error).toBeNull();
    const busy = workReducer(g, { type: 'SAVE_REQUESTED' });
    expect(canGenerate(busy)).toBe(false);
    expect(workReducer(busy, { type: 'GENERATE_REQUESTED' })).toBe(busy);
  });
  it('SAVE_RESULT with a regenerated plan shows that plan and its id', () => {
    const g = workReducer(workReducer(machineReady(loaded()), { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: plan(true) });
    const regen = { ...plan(true), plan_id: 'plan-2' };
    regen.plan = { ...regen.plan, pattern: 'spiral' };
    const s = workReducer(workReducer(g, { type: 'SAVE_REQUESTED' }), { type: 'SAVE_RESULT', operationId: 'urn:op:2', regenerated: regen });
    expect(s.result?.plan.pattern).toBe('spiral'); expect(s.result?.planId).toBe('plan-2'); expect(s.result?.operationId).toBe('urn:op:2');
  });
});

describe('VRA slice', () => {
  const full = (s: any, rates: (number | null)[] = [10, 20, 30]) => workReducer(s, { type: 'VRA_CONFIG_CHANGED', config: {
    enabled: true, classes: [0, 33, 67].map((m, i) => ({ minPct: m, maxPct: [33, 67, 100][i], rate: rates[i] as any })) } });
  const prescription = { unit: 'kg_ha', product: 'P', classes: [], zones: { type: 'FeatureCollection', features: [] },
    swath_segments: { type: 'FeatureCollection', features: [] }, warnings: [] } as any;
  const planWith = (p: any) => { const r = plan(true); (r.plan as any).prescription = p; return r; };
  const generated = (s: any, p: any) => workReducer(workReducer(s, { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: planWith(p) });

  it('has the default config', () => {
    const c = initialWorkState.vra.config;
    expect(c.enabled).toBe(false); expect(c.unit).toBe('kg_ha');
    expect(c.classes.map((k) => [k.minPct, k.maxPct, k.rate])).toEqual([[0, 33, null], [33, 67, null], [67, 100, null]]);
    expect(initialWorkState.vra.status).toBe('idle');
  });
  it('config change does not mark stale', () => {
    const g = generated(machineReady(loaded()), null);
    const s = workReducer(g, { type: 'VRA_CONFIG_CHANGED', config: { product: 'Z' } });
    expect(s.stale).toBe(false); expect(s.vra.config.product).toBe('Z'); expect(s.phase).toBe('generated');
  });
  it('GENERATED keeps config, takes or clears prescription', () => {
    const r = full(machineReady(loaded()));
    const withP = generated(r, prescription);
    expect(withP.vra.prescription).toBe(prescription); expect(withP.vra.config.enabled).toBe(true);
    const again = generated(workReducer(withP, { type: 'PATTERN_CHANGED', pattern: { pattern: 'snake' } }), null);
    expect(again.vra.prescription).toBeNull(); expect(again.vra.config.enabled).toBe(true);
  });
  it('SAVE_RESULT takes the plan prescription', () => {
    const g = generated(machineReady(loaded()), null);
    const s = workReducer(workReducer(g, { type: 'SAVE_REQUESTED' }), { type: 'SAVE_RESULT', operationId: 'urn:op:1', regenerated: { ...planWith(prescription), plan_id: 'plan-2' } });
    expect(s.vra.prescription).toBe(prescription);
  });
  it('savedPlanVraDiffers: a prescription computed after generating needs a regenerate; an unchanged one does not', () => {
    const none = generated(full(machineReady(loaded())), null);
    expect(savedPlanVraDiffers(none)).toBe(false);
    const withRx = workReducer(none, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: none.parcelRequestId, requestId: none.vra.requestId, prescription: prescription as any });
    expect(savedPlanVraDiffers(withRx)).toBe(true);
    const base = full(machineReady(loaded()));
    const rx = workReducer(base, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: base.parcelRequestId, requestId: base.vra.requestId, prescription: prescription as any });
    const withVra = generated(rx, prescription);
    expect(savedPlanVraDiffers(withVra)).toBe(false);
    const off = workReducer(withVra, { type: 'VRA_CONFIG_CHANGED', config: { enabled: false } });
    expect(savedPlanVraDiffers(off)).toBe(true);
  });
  it('distribution / prescription / failure events drive status', () => {
    const dist = { source: 'orion', variable: 'NDVI', zones: [], missing: [], percentiles: [] } as any;
    let s = workReducer(initialWorkState, { type: 'VRA_DISTRIBUTION_LOADED', parcelRequestId: 0, distribution: dist });
    expect(s.vra.distribution).toBe(dist);
    s = workReducer(s, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: 0, requestId: 0, prescription });
    expect(s.vra.prescription).toBe(prescription); expect(s.vra.status).toBe('ready');
    s = workReducer(s, { type: 'VRA_FAILED', parcelRequestId: 0, error: { code: 'INVALID_VRA', detail: 'x', params: {} } });
    expect(s.vra.status).toBe('error'); expect(s.vra.error?.code).toBe('INVALID_VRA');
    s = workReducer(s, { type: 'VRA_CONFIG_CHANGED', config: { product: 'A' } });
    expect(s.vra.error).toBeNull();
  });
  it('stepStatus vra: disabled / optional / complete', () => {
    expect(stepStatus(loaded(), 'vra')).toBe('disabled');
    const g = generated(machineReady(loaded()), null);
    expect(stepStatus(g, 'vra')).toBe('optional');
    expect(stepStatus(generated(full(machineReady(loaded())), prescription), 'vra')).toBe('complete');
  });
  it('buildGenerateRequest sends vra only when a prescription exists and the config is enabled and complete', () => {
    const base = machineReady(loaded());
    const withP = (s: any) => ({ ...s, vra: { ...s.vra, prescription } });
    expect(buildGenerateRequest(withP(base), false)).not.toHaveProperty('vra');
    expect(buildGenerateRequest(withP(full(base, [10, null, 30])), false)).not.toHaveProperty('vra');
    expect(buildGenerateRequest(withP(full(base, [10, -1, 30])), false)).not.toHaveProperty('vra');
    const off = workReducer(full(base), { type: 'VRA_CONFIG_CHANGED', config: { enabled: false } });
    expect(buildGenerateRequest(withP(off), false)).not.toHaveProperty('vra');
    // enabled and complete but no prescription yet: no vra (a new parcel must be able to generate)
    expect(buildGenerateRequest(full(base), false)).not.toHaveProperty('vra');
    const body = buildGenerateRequest(withP(workReducer(full(base, [0, 20, 30]), { type: 'VRA_CONFIG_CHANGED', config: { product: 'N', variable: 'NDVI' } })), true);
    expect(body.vra).toEqual({ enabled: true, source: 'orion', variable: 'NDVI', unit: 'kg_ha', product: 'N', invert: false,
      classes: [{ min_pct: 0, max_pct: 33, rate: 0 }, { min_pct: 33, max_pct: 67, rate: 20 }, { min_pct: 67, max_pct: 100, rate: 30 }] });
  });
  it('after a parcel change with VRA on, generate carries no vra and the VRA step becomes usable', () => {
    let s = generated(full(machineReady(loaded())), prescription);
    expect(s.vra.prescription).toBe(prescription);
    s = workReducer(s, { type: 'PARCEL_SELECTED', id: 'p2', requestId: 2 });
    s = workReducer(s, { type: 'PARCEL_LOADED', requestId: 2, id: 'p2', name: 'P2', geometry: geom as any, config: { accessPoint: null, exclusionZones: null } });
    s = machineReady(s);
    expect(s.vra.config.enabled).toBe(true); expect(s.vra.prescription).toBeNull();
    expect(buildGenerateRequest(s, false)).not.toHaveProperty('vra');
    const g = workReducer(workReducer(s, { type: 'GENERATE_REQUESTED' }), { type: 'GENERATED', response: planWith(null) });
    expect(g.phase).toBe('generated');
    expect(stepStatus(g, 'vra')).toBe('pending');
  });
  it('save is blocked while VRA is enabled but incomplete or its prescription is missing', () => {
    const g = generated(full(machineReady(loaded()), [10, null, 30]), null);
    expect(vraSaveBlocker(g)).toBe('incomplete');
    expect(workReducer(g, { type: 'SAVE_REQUESTED' })).toBe(g);
    const ext = generated(workReducer(full(machineReady(loaded())), { type: 'VRA_CONFIG_CHANGED', config: { source: 'external' } }), null);
    expect(vraSaveBlocker(ext)).toBe('incomplete');
    const complete = generated(full(machineReady(loaded())), null);
    expect(vraSaveBlocker(complete)).toBe('pending');
    expect(workReducer(complete, { type: 'SAVE_REQUESTED' })).toBe(complete);
    expect(vraSaveBlocker(generated(full(machineReady(loaded())), prescription))).toBeNull();
    expect(workReducer(generated(full(machineReady(loaded())), prescription), { type: 'SAVE_REQUESTED' }).phase).toBe('saving');
    const off = workReducer(complete, { type: 'VRA_CONFIG_CHANGED', config: { enabled: false } });
    expect(vraSaveBlocker(off)).toBeNull();
  });
  it('changing the number of classes drops the prescription computed for the old count', () => {
    const g = generated(full(machineReady(loaded())), prescription);
    const four = [0, 25, 50, 75].map((m, i) => ({ minPct: m, maxPct: [25, 50, 75, 100][i], rate: 1 }));
    expect(workReducer(g, { type: 'VRA_CONFIG_CHANGED', config: { classes: four } }).vra.prescription).toBeNull();
  });
  it('external source sends external_features', () => {
    const fc = { type: 'FeatureCollection', features: [] };
    const s = workReducer(full(machineReady(loaded())), { type: 'VRA_CONFIG_CHANGED', config: { source: 'external', externalFeatures: fc as any } });
    expect(buildGenerateRequest({ ...s, vra: { ...s.vra, prescription } }, false).vra?.external_features).toEqual(fc);
  });

  it('new parcel keeps rates but resets source and external features', () => {
    const fc = { type: 'FeatureCollection', features: [] } as any;
    let s = workReducer(full(machineReady(loaded())), { type: 'VRA_CONFIG_CHANGED', config: { source: 'external', externalFeatures: fc, product: 'N' } });
    s = workReducer(s, { type: 'PARCEL_SELECTED', id: 'p2', requestId: 2 });
    for (const t of [s, workReducer(s, { type: 'PARCEL_LOADED', requestId: 2, id: 'p2', name: 'P2', geometry: geom as any, config: { accessPoint: null, exclusionZones: null } })]) {
      expect(t.vra.config.source).toBe('orion'); expect(t.vra.config.externalFeatures).toBeUndefined();
      expect(t.vra.config.classes.map((k) => k.rate)).toEqual([10, 20, 30]); expect(t.vra.config.enabled).toBe(true);
      expect(t.vra.config.product).toBe('N'); expect(t.vra.distribution).toBeNull();
    }
  });
  it('ignores VRA results from a previous parcel', () => {
    const dist = { source: 'orion', variable: 'NDVI', zones: [], missing: [], percentiles: [] } as any;
    const s = workReducer(loaded(initialWorkState, 2), { type: 'VRA_REQUESTED', parcelRequestId: 2, requestId: 1 });
    expect(s.vra.status).toBe('loading');
    expect(workReducer(s, { type: 'VRA_DISTRIBUTION_LOADED', parcelRequestId: 1, distribution: dist })).toBe(s);
    expect(workReducer(s, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: 1, requestId: 1, prescription })).toBe(s);
    expect(workReducer(s, { type: 'VRA_FAILED', parcelRequestId: 1, requestId: 1, error: { code: 'X', detail: 'x', params: {} } })).toBe(s);
    expect(workReducer(s, { type: 'VRA_REQUESTED', parcelRequestId: 1, requestId: 9 })).toBe(s);
  });
  it('a newer prescription request supersedes an older in-flight one', () => {
    let s = workReducer(loaded(initialWorkState, 1), { type: 'VRA_REQUESTED', parcelRequestId: 1, requestId: 1 });
    s = workReducer(s, { type: 'VRA_REQUESTED', parcelRequestId: 1, requestId: 2 });
    expect(workReducer(s, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: 1, requestId: 1, prescription })).toBe(s);
    expect(workReducer(s, { type: 'VRA_FAILED', parcelRequestId: 1, requestId: 1, error: { code: 'X', detail: 'x', params: {} } })).toBe(s);
    const ok = workReducer(s, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: 1, requestId: 2, prescription });
    expect(ok.vra.status).toBe('ready'); expect(ok.vra.prescription).toBe(prescription);
  });
  it('GENERATED sets vra status ready or idle; enabled without prescription is pending', () => {
    const r = full(machineReady(loaded()));
    expect(generated(r, prescription).vra.status).toBe('ready');
    const g = generated(r, null);
    expect(g.vra.status).toBe('idle'); expect(stepStatus(g, 'vra')).toBe('pending');
  });
  it('external source without features sends no vra', () => {
    const s = workReducer(full(machineReady(loaded())), { type: 'VRA_CONFIG_CHANGED', config: { source: 'external' } });
    expect(buildGenerateRequest(s, false)).not.toHaveProperty('vra');
  });
});
