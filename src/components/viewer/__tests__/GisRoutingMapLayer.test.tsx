import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { VRA_PALETTE } from '../../../map/model';

const viewer: any = {};
vi.mock('@nekazari/sdk', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useViewer: () => ({ cesiumViewer: viewer, selectedEntityId: 'parcel-1' }),
}));
vi.mock('../../../services/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  api: {
    getOperationPlan: vi.fn(), getParcelConfig: vi.fn(),
    startPathCalculation: vi.fn(), getPathResult: vi.fn(),
  },
}));
import { api } from '../../../services/api';
import { GisRoutingMapLayer } from '../GisRoutingMapLayer';
import { EV } from '../routingMode';

const colorCalls: string[] = [];
let inputActions: Record<string, (e: any) => void> = {};

function installCesium() {
  const color = (name: string) => { const c: any = { name }; c.withAlpha = () => c; return c; };
  class Handler {
    setInputAction(fn: any, type: string) { inputActions[type] = fn; }
    destroy() {}
    isDestroyed() { return false; }
  }
  class Ellipsoid {}
  (window as any).Cesium = {
    Cartesian3: { fromDegrees: (...a: number[]) => ({ a }), fromDegreesArray: (a: number[]) => ({ a }) },
    Cartesian2: class { constructor(public x: number, public y: number) {} },
    Cartographic: { fromCartesian: (c: any) => c },
    Math: { toDegrees: (x: number) => x },
    PolygonHierarchy: class { constructor(public p: any, public h: any) {} },
    Color: {
      fromCssColorString: (s: string) => { colorCalls.push(s); return color(s); },
      RED: color('red'), WHITE: color('white'),
    },
    LabelStyle: { FILL_AND_OUTLINE: 1 }, VerticalOrigin: { BOTTOM: 1, TOP: 2, CENTER: 3 },
    ScreenSpaceEventHandler: Handler, ScreenSpaceEventType: { LEFT_CLICK: 'click', MOUSE_MOVE: 'move', LEFT_DOUBLE_CLICK: 'dbl' },
    defined: (x: any) => x !== undefined && x !== null,
    EllipsoidTerrainProvider: Ellipsoid,
  };
  viewer.terrainProvider = new Ellipsoid();
}

const added: any[] = [];
beforeEach(() => {
  added.length = 0; colorCalls.length = 0; inputActions = {};
  viewer.entities = { add: vi.fn((o: any) => { added.push(o); return o; }), removeById: vi.fn() };
  viewer.isDestroyed = () => false;
  viewer.scene = { canvas: {}, pickPosition: (p: any) => p };
  installCesium();
  vi.mocked(api.getParcelConfig).mockResolvedValue({ accessPoint: null, exclusionZones: null } as any);
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.clearAllMocks(); });

const sq = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]];
const feat = (element: string, geometry: any, props: any = {}) =>
  ({ type: 'Feature', geometry, properties: { element, ...props } });

describe('cockpit plan drawing', () => {
  it('fetches the plan of the operation and draws swaths, access and coloured prescription zones', async () => {
    vi.mocked(api.getOperationPlan).mockResolvedValue({
      type: 'FeatureCollection', properties: { plan_version: 1 },
      features: [
        feat('swath', { type: 'LineString', coordinates: [[0, 0], [1, 0]] }),
        feat('access_path', { type: 'LineString', coordinates: [[0, 0], [0, 1]] }),
        feat('access_point', { type: 'Point', coordinates: [0, 0] }),
        feat('prescription_zone', { type: 'Polygon', coordinates: [sq] }, { class_index: 0, rate: 40, unit: 'kg_ha' }),
      ],
    } as any);
    render(<GisRoutingMapLayer />);
    await act(async () => {
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, { detail: { operation_id: 'op-1', geometry: null } }));
    });
    expect(api.getOperationPlan).toHaveBeenCalledWith('op-1');
    const ids = added.map((a) => a.id);
    expect(ids.some((i) => i.includes('swath'))).toBe(true);
    expect(ids.some((i) => i.includes('access_path'))).toBe(true);
    expect(ids.some((i) => i.includes('access_point'))).toBe(true);
    const presc = added.find((a) => a.id.includes('prescription_zone'));
    expect(presc.polygon).toBeTruthy();
    expect(presc.label.text).toBe('40 kg/ha');
    expect(colorCalls).toContain(VRA_PALETTE[0]);
  });

  it('keeps the legacy route when there is no operation id', async () => {
    render(<GisRoutingMapLayer />);
    await act(async () => {
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
        detail: { geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] } },
      }));
    });
    expect(api.getOperationPlan).not.toHaveBeenCalled();
    expect(added).toHaveLength(1);
  });

  it('falls back to the received route when the plan cannot be read', async () => {
    vi.mocked(api.getOperationPlan).mockRejectedValue(new Error('boom'));
    render(<GisRoutingMapLayer />);
    await act(async () => {
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
        detail: { operation_id: 'op-1', geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] } },
      }));
    });
    expect(added).toHaveLength(1);
  });
});

describe('A-B polling', () => {
  const states: any[] = [];
  const onState = (e: Event) => states.push((e as CustomEvent).detail);

  async function startAB() {
    render(<GisRoutingMapLayer />);
    await act(async () => { window.dispatchEvent(new CustomEvent(EV.transitStart)); });
    await act(async () => { inputActions.click({ position: [1, 1] }); });
    await act(async () => { inputActions.click({ position: [2, 2] }); });
  }

  beforeEach(() => {
    states.length = 0;
    window.addEventListener('nekazari:pf:stateChange', onState);
    vi.useFakeTimers();
    vi.mocked(api.startPathCalculation).mockResolvedValue({ job_id: 'j1' });
  });
  afterEach(() => window.removeEventListener('nekazari:pf:stateChange', onState));

  it('polls every second through queued and running until completed', async () => {
    vi.mocked(api.getPathResult)
      .mockResolvedValueOnce({ status: 'queued' } as any)
      .mockResolvedValueOnce({ status: 'running' } as any)
      .mockResolvedValue({ status: 'completed', alternatives: [] } as any);
    await startAB();
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(api.getPathResult).toHaveBeenCalledTimes(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(api.getPathResult).toHaveBeenCalledTimes(3);
    expect(states[states.length - 1]).toMatchObject({ state: 'done' });
    expect(states[states.length - 1].error).toBeUndefined();
  });

  it('keeps polling for 5 minutes, then reports JOB_TIMEOUT', async () => {
    vi.mocked(api.getPathResult).mockResolvedValue({ status: 'running' } as any);
    await startAB();
    await act(async () => { await vi.advanceTimersByTimeAsync(299_000); });
    expect(states[states.length - 1]).toMatchObject({ state: 'calculating' });
    await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });
    expect(states[states.length - 1]).toMatchObject({ state: 'done', error: { code: 'JOB_TIMEOUT' } });
    const calls = vi.mocked(api.getPathResult).mock.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(10_000); });
    expect(api.getPathResult).toHaveBeenCalledTimes(calls);
  });

  it('reports the failure code and params of a failed job', async () => {
    vi.mocked(api.getPathResult).mockResolvedValue(
      { status: 'failed', error: 'x', error_code: 'POINT_IN_ZONE', error_params: { point: 'A' } } as any);
    await startAB();
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(states[states.length - 1]).toMatchObject({ state: 'done', error: { code: 'POINT_IN_ZONE', params: { point: 'A' } } });
  });
});
