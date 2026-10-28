import { describe, expect, it, vi } from 'vitest';
import { workReducer, initialWorkState, currentVraKey } from '../workMachine';
import { savePlan } from '../savePlan';

const geom = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]] } as const;
const resp = (id: string, rx: any = null) => ({ success: true, operation_id: null, persisted: false, plan_id: id,
  plan: { pattern: 'boustrophedon', validation: { ok: true, checks: [], fallbacks_applied: [], warnings: [] }, prescription: rx } as any });
const rx: any = { unit: 'kg_ha', product: 'P', classes: [], zones: { type: 'FeatureCollection', features: [] }, warnings: [] };
const vraCfg = { enabled: true, classes: [0, 33, 67].map((m, i) => ({ minPct: m, maxPct: [33, 67, 100][i], rate: 10 * (i + 1) })) };

function generatedState(withRx: boolean) {
  let s: any = workReducer(workReducer(initialWorkState, { type: 'PARCEL_SELECTED', id: 'p1', requestId: 1 }),
    { type: 'PARCEL_LOADED', requestId: 1, id: 'p1', name: 'P1', geometry: geom as any, config: { accessPoint: null, exclusionZones: null } });
  s = workReducer(s, { type: 'MACHINE_CHANGED', machine: { widthM: 24, widthSource: 'manual', turningRadiusM: 6, radiusSource: 'manual' } });
  s = workReducer(s, { type: 'VRA_CONFIG_CHANGED', config: vraCfg });
  if (withRx) s = workReducer(s, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: s.parcelRequestId, requestId: s.vra.requestId, prescription: rx });
  s = workReducer(s, { type: 'GENERATE_REQUESTED' });
  return workReducer(s, { type: 'GENERATED', response: resp('plan-1', withRx ? rx : null) });
}

describe('savePlan', () => {
  it('saves the displayed plan by id without regenerating', async () => {
    const generate = vi.fn(); const saveOperation = vi.fn().mockResolvedValue({ success: true, operation_id: 'op-1', persisted: true });
    const out = await savePlan(generatedState(false), { generate, saveOperation });
    expect(generate).not.toHaveBeenCalled();
    expect(saveOperation).toHaveBeenCalledWith({ kind: 'plan', plan_id: 'plan-1' });
    expect(out).toEqual({ operationId: 'op-1' });
  });

  it('regenerates once (persist:false, with the VRA) when the prescription was computed after generating', async () => {
    let s: any = generatedState(false);
    s = workReducer(s, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: s.parcelRequestId, requestId: s.vra.requestId, prescription: rx });
    const regen = resp('plan-2', rx);
    const generate = vi.fn().mockResolvedValue(regen);
    const saveOperation = vi.fn().mockResolvedValue({ success: true, operation_id: 'op-2', persisted: true });
    const out = await savePlan(s, { generate, saveOperation });
    expect(generate).toHaveBeenCalledTimes(1);
    expect(generate.mock.calls[0][0]).toMatchObject({ persist: false });
    expect(generate.mock.calls[0][0].vra).toBeTruthy();
    expect(saveOperation).toHaveBeenCalledWith({ kind: 'plan', plan_id: 'plan-2' });
    expect(out.operationId).toBe('op-2');
    expect(out.regenerated).toBe(regen);
    // The key is that of the request sent (the snapshot), so a later config edit cannot relabel the result.
    expect(out.vraKey).toBe(currentVraKey(s));
    expect(out.vraKey).not.toBeNull();
    const edited = { ...s, vra: { ...s.vra, prescription: null } };
    const next = workReducer({ ...s, phase: 'saving' }, { type: 'SAVE_RESULT', ...out });
    const afterEdit = workReducer({ ...edited, phase: 'saving' }, { type: 'SAVE_RESULT', ...out });
    expect(next.result?.vraKey).toBe(out.vraKey);
    expect(afterEdit.result?.vraKey).toBe(out.vraKey);
  });

  it('does not regenerate when the VRA is unchanged since generating', async () => {
    const generate = vi.fn(); const saveOperation = vi.fn().mockResolvedValue({ success: true, operation_id: 'op-3', persisted: true });
    await savePlan(generatedState(true), { generate, saveOperation });
    expect(generate).not.toHaveBeenCalled();
  });

  it('rejects an unpersisted answer', async () => {
    const saveOperation = vi.fn().mockResolvedValue({ success: true, operation_id: '', persisted: false });
    await expect(savePlan(generatedState(false), { generate: vi.fn(), saveOperation })).rejects.toThrow();
  });

  it('a plan too large to save (plan_id null) fails with the coded error and never calls save', async () => {
    let s: any = generatedState(false);
    s = { ...s, result: { ...s.result, planId: null } };
    const generate = vi.fn(); const saveOperation = vi.fn();
    await expect(savePlan(s, { generate, saveOperation })).rejects.toMatchObject({ code: 'PLAN_TOO_LARGE_TO_SAVE' });
    expect(generate).not.toHaveBeenCalled();
    expect(saveOperation).not.toHaveBeenCalled();
  });
});
