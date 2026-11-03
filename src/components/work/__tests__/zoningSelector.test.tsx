import React, { useReducer } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { initialWorkState, toVraRequest, workReducer, type WorkState } from '../../../state/workMachine';
import { useVraSync } from '../../../state/useVraSync';
import { StepVra } from '../StepVra';

vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select value={p.value} onChange={(e) => p.onValueChange(e.target.value)} disabled={p.disabled}>
      {p.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  const Slider = (p: any) => (
    <input type="range" aria-label={p.label} min={p.min} max={p.max} step={p.step} value={p.value}
      disabled={p.disabled} onChange={(e) => p.onChange(Number(e.target.value))} />
  );
  return { ...actual, Select, Slider };
});

vi.mock('../../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api')>();
  return {
    ...actual,
    api: {
      getDistribution: vi.fn(), requestZones: vi.fn(), prescription: vi.fn(), ingestExternalZones: vi.fn(),
      listZonings: vi.fn(), getZoningZones: vi.fn(),
    },
  };
});
import { api } from '../../../services/api';

const poly = (x = 0, s = 0.001): GeoJSON.Polygon => ({
  type: 'Polygon', coordinates: [[[x, 0], [x + s, 0], [x + s, s], [x, s], [x, 0]]],
});
const dist = (means: number[]) => ({
  source: 'orion' as const, variable: 'NDVI',
  zones: means.map((m, i) => ({ id: `z${i}`, mean: m, area_ha: 2, geometry: poly(i) })),
  missing: [],
  percentiles: Array.from({ length: 21 }, (_, i) => 0.2 + i * 0.03),
});
const MANUAL = 'manual-1a2b3c4d';
const T1 = 'urn:ngsi-ld:AgriManagementZone:tenant-a:p1:manual-1a2b3c4d-1';
const T2 = 'urn:ngsi-ld:AgriManagementZone:tenant-a:p1:manual-1a2b3c4d-2';
const ZONINGS = [
  { run_id: MANUAL, method: 'manual', date: '2026-06-01T10:00:00+00:00', zone_count: 2, labels: ['T1', 'T2'], is_default: false },
  { run_id: 'veg-new', method: 'vegetationIndex', date: '2026-05-01T00:00:00Z', zone_count: 4, labels: [], is_default: true },
  { run_id: 'veg-old', method: 'vegetationIndex', date: '2025-05-01T00:00:00Z', zone_count: 3, labels: [], is_default: false },
];
const zonePresc = () => ({
  unit: 'kg_ha' as const, product: 'N',
  classes: [
    { index: 0, zone_id: T1, label: 'T1', min_pct: null, max_pct: null, rate: 120, area_ha: 1.5, product_total: 180 },
    { index: 1, zone_id: T2, label: 'T2', min_pct: null, max_pct: null, rate: 80, area_ha: 2, product_total: 160 },
  ],
  zones: { type: 'FeatureCollection' as const, features: [] },
  swath_segments: { type: 'FeatureCollection' as const, features: [] },
  warnings: [],
});

function baseState(cfg: Partial<WorkState['vra']['config']> = {}): WorkState {
  return {
    ...initialWorkState,
    phase: 'generated',
    activeStep: 'vra',
    parcel: { id: 'p1', name: 'Alpha', geometry: poly(0, 0.01) },
    parcelRequestId: 1,
    result: { plan: { swaths: [], prescription: null } as any, kind: 'valid', operationId: null, planId: null, vraKey: null },
    vra: { ...initialWorkState.vra, config: { ...initialWorkState.vra.config, enabled: true, ...cfg } },
  };
}

let latest: WorkState;
const Harness: React.FC<{ initial: WorkState }> = ({ initial }) => {
  const [state, dispatch] = useReducer(workReducer, initial);
  latest = state;
  const sync = useVraSync(state, dispatch);
  return <StepVra state={state} dispatch={dispatch} sync={sync} />;
};

async function flush(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}
async function mount(initial: WorkState) {
  render(<Harness initial={initial} />);
  await flush(0);
}
const selector = () => screen.getByLabelText('Zonificación') as HTMLSelectElement;

beforeAll(async () => { await i18n.changeLanguage('es'); });
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  (api.getDistribution as any).mockResolvedValue(dist([0.3, 0.5, 0.7]));
  (api.listZonings as any).mockResolvedValue({ zonings: ZONINGS });
  (api.getZoningZones as any).mockResolvedValue({ data: { zones: [
    { id: T1, label: 'T1', rank: 1, area_ha: 1.5, geometry: poly(0) },
    { id: T2, label: 'T2', rank: 2, area_ha: 2, geometry: poly(1) },
  ] } });
  (api.prescription as any).mockResolvedValue({ prescription: zonePresc() });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('zoning selector', () => {
  it('preselects the default automatic zoning and lists manual ones with their date', async () => {
    await mount(baseState());
    expect(api.listZonings).toHaveBeenCalledWith('p1');
    expect(selector().value).toBe('veg-new');
    const texts = [...selector().options].map((o) => o.textContent);
    expect(texts[0]).toBe('Manual · 2026-06-01 (2 zonas)');
    expect(texts[1]).toBe('Índice de vegetación · 2026-05-01 (4 zonas) · por defecto');
  });

  it('an older automatic zoning reloads its distribution and is sent with the request', async () => {
    await mount(baseState({ classes: [
      { minPct: 0, maxPct: 50, rate: 1 }, { minPct: 50, maxPct: 100, rate: 2 }] }));
    fireEvent.change(selector(), { target: { value: 'veg-old' } });
    await flush(0);
    expect(api.getDistribution).toHaveBeenLastCalledWith('p1', 'veg-old');
    expect(latest.vra.config.zoningRunId).toBe('veg-old');
    expect(latest.vra.config.zoneRates).toBeUndefined();
    await flush(500);
    expect((api.prescription as any).mock.calls.at(-1)[0].vra.zoning_run_id).toBe('veg-old');
  });

  it('a manual zoning switches to one rate per zone and sends zone_rates', async () => {
    await mount(baseState());
    fireEvent.change(selector(), { target: { value: MANUAL } });
    await flush(0);
    expect(api.getZoningZones).toHaveBeenCalledWith('p1', MANUAL);
    expect(screen.queryByTestId('vra-histogram')).toBeNull();
    expect(screen.queryByTestId('vra-missing')).toBeNull();
    expect(screen.getAllByTestId('vra-zone-row')).toHaveLength(2);
    expect(toVraRequest(latest.vra.config)).toBeNull(); // rates still empty
    fireEvent.change(screen.getByLabelText('Dosis de la zona T1'), { target: { value: '120' } });
    fireEvent.change(screen.getByLabelText('Dosis de la zona T2'), { target: { value: '80' } });
    await flush(500);
    const vra = (api.prescription as any).mock.calls.at(-1)[0].vra;
    expect(vra.zoning_run_id).toBe(MANUAL);
    expect(vra.zone_rates).toEqual({ [T1]: 120, [T2]: 80 });
    expect(vra.classes).toEqual([]);
    await flush(0);
    expect(screen.getByTestId('vra-zone-total').textContent).toContain('340');
  });

  it('back to the default zoning leaves per-zone mode', async () => {
    await mount(baseState());
    fireEvent.change(selector(), { target: { value: MANUAL } });
    await flush(0);
    fireEvent.change(selector(), { target: { value: 'veg-new' } });
    await flush(0);
    expect(latest.vra.config.zoneRates).toBeUndefined();
    expect(latest.vra.config.zoningRunId).toBeNull();
    expect(screen.getAllByTestId('vra-row').length).toBeGreaterThan(0);
  });
});

describe('toVraRequest with per-zone rates', () => {
  const cfg = (zoneRates: Record<string, number | null>) => ({
    ...initialWorkState.vra.config, enabled: true, zoningRunId: MANUAL, zoneRates,
  });
  it('is null until every zone has a rate', () => {
    expect(toVraRequest(cfg({ [T1]: 1, [T2]: null }))).toBeNull();
    expect(toVraRequest(cfg({}))).toBeNull();
  });
  it('carries zone_rates and no classes when complete', () => {
    const r = toVraRequest(cfg({ [T1]: 1, [T2]: 0 }))!;
    expect(r.zone_rates).toEqual({ [T1]: 1, [T2]: 0 });
    expect(r.classes).toEqual([]);
    expect(r.zoning_run_id).toBe(MANUAL);
  });
});
