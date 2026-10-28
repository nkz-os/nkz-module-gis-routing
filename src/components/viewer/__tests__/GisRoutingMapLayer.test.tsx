import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../../../i18n';
import { VRA_PALETTE } from '../../../map/model';

const viewer: any = {};
vi.mock('@nekazari/sdk', async (importOriginal) => {
  const actual = await importOriginal<Record<string, any>>();
  const { createInstance } = await import('i18next');
  const i18n = createInstance();
  i18n.init({ lng: 'es', fallbackLng: 'en', defaultNS: 'gis-routing', resources: {}, interpolation: { escapeValue: false } });
  return {
  ...actual,
  i18n,
  useTranslation: (ns?: string) => ({ t: i18n.getFixedT(null, ns ?? 'gis-routing'), i18n }),
  useViewer: () => ({ cesiumViewer: viewer, selectedEntityId: 'parcel-1' }),
  };
});
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
      RED: color('red'), WHITE: color('white'), BLACK: color('black'),
    },
    LabelStyle: { FILL_AND_OUTLINE: 1 }, VerticalOrigin: { BOTTOM: 1, TOP: 2, CENTER: 3 },
    ScreenSpaceEventHandler: Handler, ScreenSpaceEventType: { LEFT_CLICK: 'click', MOUSE_MOVE: 'move', LEFT_DOUBLE_CLICK: 'dbl' },
    defined: (x: any) => x !== undefined && x !== null,
    EllipsoidTerrainProvider: Ellipsoid,
    StripeMaterialProperty: class { constructor(public o: any) {} },
    StripeOrientation: { HORIZONTAL: 0, VERTICAL: 1 },
    HeightReference: { CLAMP_TO_GROUND: 1 },
  };
  viewer.terrainProvider = new Ellipsoid();
}

const added: any[] = [];
beforeEach(() => {
  added.length = 0; colorCalls.length = 0; inputActions = {};
  viewer.entities = {
    add: vi.fn((o: any) => { added.push(o); return o; }), removeById: vi.fn(),
    getById: (id: string) => added.find((a) => a.id === id),
  };
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

describe('A-B machine width', () => {
  const states: any[] = [];
  const onState = (e: Event) => states.push((e as CustomEvent).detail);
  beforeEach(() => {
    states.length = 0;
    window.addEventListener('nekazari:pf:stateChange', onState);
    vi.mocked(api.startPathCalculation).mockResolvedValue({ job_id: 'j1' });
  });
  afterEach(() => window.removeEventListener('nekazari:pf:stateChange', onState));

  async function pick(widthM: number | null) {
    render(<GisRoutingMapLayer />);
    await act(async () => { window.dispatchEvent(new CustomEvent(EV.transitWidth, { detail: { widthM } })); });
    await act(async () => { window.dispatchEvent(new CustomEvent(EV.transitStart)); });
    await act(async () => { inputActions.click({ position: [1, 1] }); });
    await act(async () => { inputActions.click({ position: [2, 2] }); });
  }

  it('sends the width chosen in the panel, not a fixed one', async () => {
    await pick(6);
    expect(vi.mocked(api.startPathCalculation).mock.calls[0][0]).toMatchObject({ machine_width_m: 6 });
  });

  it('without a width it reports MACHINE_WIDTH_MISSING and asks nothing of the backend', async () => {
    await pick(null);
    expect(api.startPathCalculation).not.toHaveBeenCalled();
    expect(states[states.length - 1]).toMatchObject({ state: 'done', error: { code: 'MACHINE_WIDTH_MISSING' } });
  });
});

describe('A-B polling', () => {
  const states: any[] = [];
  const onState = (e: Event) => states.push((e as CustomEvent).detail);

  async function startAB(widthM: number | null = 6) {
    render(<GisRoutingMapLayer />);
    await act(async () => { window.dispatchEvent(new CustomEvent(EV.transitWidth, { detail: { widthM } })); });
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

const squareAt = (x: number) => [[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]];
const cfg = () => ({
  accessPoint: { type: 'Point', coordinates: [0.5, 0] },
  exclusionZones: { type: 'FeatureCollection', features: [
    { type: 'Feature', properties: {}, geometry: { type: 'Polygon', coordinates: [squareAt(0)] } },
    { type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: [[squareAt(10)], [squareAt(20)]] } },
  ] },
}) as any;

describe('gate and NO-GO on the 3D map', () => {
  it('draws them as soon as a parcel is selected, with the gate icon, the hatch and a border', async () => {
    vi.mocked(api.getParcelConfig).mockResolvedValue(cfg());
    const { findByTestId } = render(<GisRoutingMapLayer />);
    await findByTestId('map-legend');
    expect(api.getParcelConfig).toHaveBeenCalledWith('parcel-1');
    const gate = added.find((a) => a.id.includes('access'));
    expect(gate.billboard.image.startsWith('data:image/svg+xml')).toBe(true);
    expect(gate.label.text).toBe('Portón');
    const zones = added.filter((a) => a.id.includes('zone'));
    expect(zones).toHaveLength(3); // Polygon + both parts of the MultiPolygon
    for (const z of zones) {
      expect(z.polygon.material.o).toMatchObject({ repeat: expect.any(Number) });
      expect(z.polygon.stRotation).toBeCloseTo(Math.PI / 4);
      expect(z.polyline.width).toBeGreaterThanOrEqual(3);
      expect(z.polyline.clampToGround).toBe(true);
    }
    expect(zones.filter((z) => z.label?.text === 'NO-GO')).toHaveLength(2); // one label per zone feature
  });

  it('draws no gate icon when the parcel has none', async () => {
    vi.mocked(api.getParcelConfig).mockResolvedValue({ accessPoint: null, exclusionZones: cfg().exclusionZones } as any);
    const { findByTestId } = render(<GisRoutingMapLayer />);
    await findByTestId('map-legend');
    expect(added.some((a) => a.billboard)).toBe(false);
  });

  it('keeps the current gate and zones visible after a plan is drawn; the plan snapshot is not drawn over them', async () => {
    vi.mocked(api.getParcelConfig).mockResolvedValue(cfg());
    vi.mocked(api.getOperationPlan).mockResolvedValue({
      type: 'FeatureCollection', properties: { plan_version: 1 },
      features: [feat('access_point', { type: 'Point', coordinates: [0, 0] }), feat('exclusion_zone', { type: 'Polygon', coordinates: [sq] })],
    } as any);
    const { findByTestId } = render(<GisRoutingMapLayer />);
    await findByTestId('map-legend');
    const cfgEntities = added.filter((a) => a.id.startsWith('gis-cfg'));
    expect(cfgEntities.length).toBeGreaterThan(0);
    await act(async () => {
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, { detail: { operation_id: 'op-1', geometry: null } }));
    });
    expect(cfgEntities.every((e) => e.show !== false)).toBe(true);
    for (const e of added.filter((a) => a.id.startsWith('gis-plan-exclusion_zone') || a.id.startsWith('gis-plan-access_point'))) {
      expect(e.show).toBe(false);
    }
    // A zone added to the parcel afterwards is shown too.
    vi.mocked(api.getParcelConfig).mockResolvedValue(cfg());
    await act(async () => { window.dispatchEvent(new CustomEvent('nekazari:gis-routing:parcelConfig:hide')); });
    await act(async () => {});
    expect(added.filter((a) => a.id.startsWith('gis-cfg')).every((e) => e.show !== false)).toBe(true);
  });

  it('draws the plan snapshot of the gate and zones when the parcel config cannot be read', async () => {
    vi.mocked(api.getParcelConfig).mockRejectedValue(new Error('down'));
    vi.mocked(api.getOperationPlan).mockResolvedValue({
      type: 'FeatureCollection', properties: { plan_version: 1 },
      features: [feat('access_point', { type: 'Point', coordinates: [0, 0] }), feat('exclusion_zone', { type: 'Polygon', coordinates: [sq] })],
    } as any);
    render(<GisRoutingMapLayer />);
    await act(async () => {
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, { detail: { operation_id: 'op-1', geometry: null } }));
    });
    const snapshot = added.filter((a) => a.id.startsWith('gis-plan-exclusion_zone') || a.id.startsWith('gis-plan-access_point'));
    expect(snapshot.length).toBeGreaterThan(0);
    expect(snapshot.every((e) => e.show !== false)).toBe(true);
  });
});

describe('language change', () => {
  it('does not clear a drawn plan or the parcel overlay', async () => {
    const { i18n } = await import('@nekazari/sdk');
    vi.mocked(api.getParcelConfig).mockResolvedValue(cfg());
    vi.mocked(api.getOperationPlan).mockResolvedValue({
      type: 'FeatureCollection', properties: { plan_version: 1 },
      features: [feat('swath', { type: 'LineString', coordinates: [[0, 0], [1, 1]] })],
    } as any);
    const { rerender, findByTestId } = render(<GisRoutingMapLayer />);
    await findByTestId('map-legend');
    await act(async () => {
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, { detail: { operation_id: 'op-1', geometry: null } }));
    });
    vi.mocked(viewer.entities.removeById).mockClear();
    await act(async () => { await i18n.changeLanguage('en'); });
    rerender(<GisRoutingMapLayer />);
    await act(async () => {});
    expect(viewer.entities.removeById).not.toHaveBeenCalled();
    await act(async () => { await i18n.changeLanguage('es'); });
  });
});


describe('plan saved on the Work page', () => {
  afterEach(() => sessionStorage.clear());
  it('is drawn in full when the cockpit mounts, from the stored operation', async () => {
    sessionStorage.setItem('nkz:gis-routing:lastSaved', JSON.stringify({
      geometry: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, prescriptionMap: null,
      operation_id: 'op-7', timestamp: Date.now() }));
    vi.mocked(api.getOperationPlan).mockResolvedValue({
      type: 'FeatureCollection', properties: { plan_version: 1 },
      features: [feat('swath', { type: 'LineString', coordinates: [[0, 0], [1, 1]] })],
    } as any);
    render(<GisRoutingMapLayer />);
    await act(async () => {});
    expect(api.getOperationPlan).toHaveBeenCalledWith('op-7');
    expect(added.some((a) => a.id.startsWith('gis-plan-swath'))).toBe(true);
  });
});
