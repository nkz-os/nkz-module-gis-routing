import { describe, expect, it } from 'vitest';
import {
  buildPathRequest, canCalculate, canSave, initialTransitState, transitReducer,
  type TransitEvent, type TransitResult, type TransitState,
} from '../transitMachine';
import type { PathAlternative } from '../../services/api';

const alt = (id: PathAlternative['id']): PathAlternative => ({
  id, label: id, distance_m: 100, cumulative_climb_m: 5,
  geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, elevation_profile: [[0, 0, 1], [1, 1, 2]],
});
const result: TransitResult = { jobId: 'job1', alternatives: [alt('least_slope'), alt('fastest')], report: {} };

const run = (events: TransitEvent[], from: TransitState = initialTransitState) => events.reduce(transitReducer, from);
const ready = (): TransitState => run([
  { type: 'POINT_SET', which: 'a', point: [0, 0] },
  { type: 'POINT_SET', which: 'b', point: [1, 1] },
  { type: 'WIDTH_SET', widthM: 3 },
  { type: 'CALC_STARTED' },
  { type: 'CALC_DONE', result },
]);

describe('transitReducer', () => {
  it('needs A, B and a width to calculate; slope must be in (0, 45]', () => {
    expect(canCalculate(initialTransitState)).toBe(false);
    const s = run([
      { type: 'POINT_SET', which: 'a', point: [0, 0] },
      { type: 'POINT_SET', which: 'b', point: [1, 1] },
      { type: 'WIDTH_SET', widthM: 3 },
    ]);
    expect(canCalculate(s)).toBe(true);
    expect(s.maxSlopeDeg).toBe(15);
    expect(canCalculate(transitReducer(s, { type: 'SLOPE_SET', maxSlopeDeg: 46 }))).toBe(false);
    expect(canCalculate(transitReducer(s, { type: 'SLOPE_SET', maxSlopeDeg: 0 }))).toBe(false);
  });

  it('builds the request with machine_id only when a machine is picked', () => {
    let s = run([
      { type: 'POINT_SET', which: 'a', point: [0, 0] },
      { type: 'POINT_SET', which: 'b', point: [1, 1] },
      { type: 'MACHINE_SET', machineId: 'm1', widthM: 4 },
    ]);
    expect(buildPathRequest(s)).toEqual({ point_a: [0, 0], point_b: [1, 1], machine_width_m: 4, max_slope_deg: 15, machine_id: 'm1' });
    s = transitReducer(s, { type: 'WIDTH_SET', widthM: 2.5 });
    expect(buildPathRequest(s)).toEqual({ point_a: [0, 0], point_b: [1, 1], machine_width_m: 2.5, max_slope_deg: 15 });
  });

  it('a second CALC_STARTED while calculating is ignored (one job)', () => {
    const s = ready();
    const c1 = transitReducer(s, { type: 'CALC_STARTED' });
    expect(c1.phase).toBe('calculating');
    expect(canCalculate(c1)).toBe(false);
    expect(transitReducer(c1, { type: 'CALC_STARTED' })).toBe(c1);
  });

  it('completes with the first alternative selected', () => {
    const s = ready();
    expect(s.phase).toBe('ready');
    expect(s.selected).toBe('least_slope');
    expect(transitReducer(s, { type: 'SELECT', id: 'fastest' }).selected).toBe('fastest');
  });

  it.each([
    ['A', { type: 'POINT_SET', which: 'a', point: [5, 5] }],
    ['B', { type: 'POINT_SET', which: 'b', point: [5, 5] }],
    ['slope', { type: 'SLOPE_SET', maxSlopeDeg: 10 }],
    ['machine', { type: 'MACHINE_SET', machineId: 'm2', widthM: 6 }],
    ['width', { type: 'WIDTH_SET', widthM: 9 }],
  ] as [string, TransitEvent][])('editing %s after a result marks it stale and blocks saving', (_n, ev) => {
    const s = transitReducer({ ...ready(), parcelId: 'p1' }, ev);
    expect(s.stale).toBe(true);
    expect(s.result).not.toBeNull();
    expect(canSave(s)).toBe(false);
    expect(canSave(transitReducer(s, { type: 'PARCEL_SET', parcelId: 'p1' }))).toBe(false);
  });

  it('setting the same point is not an edit', () => {
    expect(transitReducer(ready(), { type: 'POINT_SET', which: 'a', point: [0, 0] }).stale).toBe(false);
  });

  it('recalculating clears stale', () => {
    const s = run([{ type: 'SLOPE_SET', maxSlopeDeg: 10 }, { type: 'CALC_STARTED' }, { type: 'CALC_DONE', result }], ready());
    expect(s.stale).toBe(false);
    expect(s.phase).toBe('ready');
  });

  it('edits are ignored while calculating', () => {
    const c = transitReducer(ready(), { type: 'CALC_STARTED' });
    expect(transitReducer(c, { type: 'POINT_SET', which: 'a', point: [9, 9] })).toBe(c);
    expect(transitReducer(c, { type: 'SLOPE_SET', maxSlopeDeg: 5 })).toBe(c);
  });

  it('saving needs a parcel and is single-shot per alternative', () => {
    let s = ready();
    expect(canSave(s)).toBe(false);
    s = transitReducer(s, { type: 'PARCEL_SET', parcelId: 'p1' });
    expect(canSave(s)).toBe(true);
    s = transitReducer(s, { type: 'SAVE_STARTED' });
    expect(s.phase).toBe('saving');
    expect(transitReducer(s, { type: 'SAVE_STARTED' })).toBe(s);
    s = transitReducer(s, { type: 'SAVE_DONE', operationId: 'op-1' });
    expect(s.saved).toEqual({ least_slope: 'op-1' });
    expect(canSave(s)).toBe(false);
    expect(canSave(transitReducer(s, { type: 'SELECT', id: 'fastest' }))).toBe(true);
  });

  it('the same route can be saved again for another parcel, not twice for the same one', () => {
    let s = run([{ type: 'PARCEL_SET', parcelId: 'p1' }, { type: 'SAVE_STARTED' }, { type: 'SAVE_DONE', operationId: 'op-1' }], ready());
    expect(canSave(s)).toBe(false);
    s = transitReducer(s, { type: 'PARCEL_SET', parcelId: 'p2' });
    expect(canSave(s)).toBe(true);
    s = run([{ type: 'SAVE_STARTED' }, { type: 'SAVE_DONE', operationId: 'op-2' }], s);
    expect(s.saved).toEqual({ least_slope: 'op-2' });
    expect(canSave(s)).toBe(false);
  });

  it('a failed save keeps the result and allows retrying', () => {
    let s = run([{ type: 'PARCEL_SET', parcelId: 'p1' }, { type: 'SAVE_STARTED' }, { type: 'SAVE_FAILED', error: { code: 'PERSIST_FAILED', detail: '', params: {} } }], ready());
    expect(s.error?.code).toBe('PERSIST_FAILED');
    expect(s.result).not.toBeNull();
    s = transitReducer(s, { type: 'DISMISS_ERROR' });
    expect(canSave(s)).toBe(true);
  });

  it('an automatic parcel default never overrides a manual choice', () => {
    let s = transitReducer(initialTransitState, { type: 'PARCEL_SET', parcelId: 'p1', auto: true });
    expect(s.parcelId).toBe('p1');
    s = transitReducer(s, { type: 'PARCEL_SET', parcelId: 'p2' });
    s = transitReducer(s, { type: 'PARCEL_SET', parcelId: 'p3', auto: true });
    expect(s.parcelId).toBe('p2');
    s = transitReducer(s, { type: 'PARCEL_SET', parcelId: null });
    expect(s.parcelId).toBeNull();
  });

  it('a failed job keeps the error until an input changes', () => {
    let s = run([{ type: 'CALC_STARTED' }, { type: 'CALC_FAILED', error: { code: 'NO_PATH', detail: '', params: {} } }], ready());
    expect(s.phase).toBe('failed');
    s = transitReducer(s, { type: 'SLOPE_SET', maxSlopeDeg: 20 });
    expect(s.phase).toBe('idle');
    expect(s.error).toBeNull();
  });
});
