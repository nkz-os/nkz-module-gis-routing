import React, { useEffect, useReducer } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { buildSources, vraLegendRows } from '../../../map/model';
import { MapLegend } from '../../../map/MapLegend';
import { initialWorkState, toVraRequest, workReducer, type WorkState } from '../../../state/workMachine';
import { useVraSync } from '../../../state/useVraSync';
import { zoneDisplayLabel, zoneLabelsFor } from '../../../state/zoneLabels';
import { StepVra } from '../StepVra';

vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select value={p.value} onChange={(e) => p.onValueChange(e.target.value)} disabled={p.disabled}>
      {p.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  return { ...actual, Select };
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
const RUN = 'md-1a2b3c4d';
const ID = (n: number) => `urn:ngsi-ld:AgriManagementZone:acme:p1:md-1a2b3c4d:L${n}`;
const ZONES = [
  { id: ID(1), label: 'high', rank: 1, level: 'high', area_ha: 1, geometry: poly(0) },
  { id: ID(2), label: 'mystery', rank: 2, level: null, area_ha: 1, geometry: poly(1) },
  { id: ID(4), label: 'critical', rank: 4, level: 'critical', area_ha: 1, geometry: poly(2) },
];
const ZONINGS = [
  { run_id: RUN, method: 'vegetationIndexMultiDate', date: '2026-06-01T00:00:00Z', zone_count: 3,
    labels: ['high', 'mystery', 'critical'], levels: ['high', null, 'critical'], is_default: true },
];
const presc = () => ({
  unit: 'kg_ha' as const, product: 'N',
  classes: ZONES.map((z, i) => ({ index: i, zone_id: z.id, label: `L${i}`, min_pct: null, max_pct: null,
    rate: 10 * (i + 1), area_ha: 1, product_total: 10 })),
  zones: { type: 'FeatureCollection' as const, features: [] },
  swath_segments: { type: 'FeatureCollection' as const, features: [] },
  warnings: [],
});

function perZoneState(zones = ZONES): WorkState {
  return {
    ...initialWorkState, phase: 'generated', activeStep: 'vra',
    parcel: { id: 'p1', name: 'Alpha', geometry: poly(0, 0.01) }, parcelRequestId: 1,
    result: { plan: { swaths: [], prescription: null } as any, kind: 'valid', operationId: null, planId: null, vraKey: null },
    vra: { ...initialWorkState.vra, config: { ...initialWorkState.vra.config, enabled: true, zoningRunId: RUN,
      zoneRates: Object.fromEntries(zones.map((z, i) => [z.id, 10 * (i + 1)])), restRate: 0 } },
  };
}

let latest: WorkState;
const Harness: React.FC<{ initial: WorkState; zones: typeof ZONES }> = ({ initial, zones }) => {
  const [state, dispatch] = useReducer(workReducer, initial);
  latest = state;
  const sync = useVraSync(state, dispatch);
  // As the FaST link does once it has read the zoning.
  useEffect(() => { sync.setRateZones(zones as any); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <StepVra state={state} dispatch={dispatch} sync={sync} />;
};
const flush = async (ms = 0) => { await act(async () => { await vi.advanceTimersByTimeAsync(ms); }); };
let rerenderHarness: () => void;
async function mount(zones = ZONES, zonings: any[] = ZONINGS) {
  (api.listZonings as any).mockResolvedValue({ zonings });
  const initial = perZoneState(zones);
  const r = render(<Harness initial={initial} zones={zones} />);
  rerenderHarness = () => r.rerender(<Harness initial={initial} zones={zones} />);
  await flush(0);
}
const lastVra = () => (api.prescription as any).mock.calls.at(-1)[0].vra;

beforeAll(async () => { await i18n.changeLanguage('es'); });
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  (api.getDistribution as any).mockResolvedValue({ source: 'orion', variable: 'NDVI', zones: [], missing: [], percentiles: [] });
  (api.prescription as any).mockResolvedValue({ prescription: presc() });
});
afterEach(async () => { cleanup(); vi.useRealTimers(); await i18n.changeLanguage('es'); });

describe('multi-date zoning on screen', () => {
  it('names the method in the zoning selector', async () => {
    await mount();
    const texts = [...(screen.getByLabelText('Zonificación') as HTMLSelectElement).options].map((o) => o.textContent);
    expect(texts[0]).toBe('Satélite multifecha · 2026-06-01 (3 zonas) · por defecto');
  });

  it('shows level texts in the per-zone table; an unknown level is generic, never raw', async () => {
    await mount();
    const rows = screen.getAllByTestId('vra-zone-row').map((r) => r.querySelector('td')!.textContent);
    expect(rows).toEqual(['Vigor alto', 'Zona 2', 'Vigor crítico']);
    expect(document.body.textContent).not.toContain('mystery');
  });

  it('sends the labels the screen shows, and again in the new language', async () => {
    await mount();
    await flush(500);
    expect(lastVra().zone_labels).toEqual({ [ID(1)]: 'Vigor alto', [ID(2)]: 'Zona 2', [ID(4)]: 'Vigor crítico' });
    expect(Object.keys(lastVra().zone_rates)).toEqual(Object.keys(lastVra().zone_labels));
    await act(async () => { await i18n.changeLanguage('en'); });
    rerenderHarness(); // the host re-renders on a language change; the test harness does it by hand
    await flush(600);
    expect(lastVra().zone_labels).toEqual({ [ID(1)]: 'High vigour', [ID(2)]: 'Zone 2', [ID(4)]: 'Critical vigour' });
    expect(latest.vra.config.zoneLabels?.[ID(1)]).toBe('High vigour');
  });

  it('a zoning not named by level sends no labels', async () => {
    const manual = [{ id: 'm1', label: 'T1', rank: 1, level: null, area_ha: 1, geometry: poly(0) }];
    await mount(manual, [{ run_id: RUN, method: 'manual', date: null, zone_count: 1, labels: ['T1'], is_default: false }]);
    await flush(500);
    expect(api.prescription).toHaveBeenCalled();
    expect(lastVra().zone_labels).toBeUndefined();
    expect(screen.getAllByTestId('vra-zone-row')[0].querySelector('td')!.textContent).toBe('T1');
  });
});

describe('zone labels helpers', () => {
  const t = (k: string, o?: Record<string, unknown>) => `${k}${o?.n !== undefined ? `:${o.n}` : ''}`;
  it('translates a known level whatever the method', () => {
    expect(zoneDisplayLabel(t, { id: 'a', label: 'x', rank: 1, level: 'low' }, 'vegetationIndex', 0)).toBe('work.vra.zoneLevel.low');
  });
  it('uses the generic label for an unknown level of a multi-date zoning (rank, else position)', () => {
    expect(zoneDisplayLabel(t, { id: 'a', label: 'high', rank: null, level: 'HIGH' }, 'vegetationIndexMultiDate', 2)).toBe('work.vra.zoneGeneric:3');
    expect(zoneDisplayLabel(t, { id: 'a', label: 'high', rank: 7, level: undefined }, 'vegetationIndexMultiDate', 0)).toBe('work.vra.zoneGeneric:7');
  });
  it('keeps the label of other zonings, falling back to the id tail', () => {
    expect(zoneDisplayLabel(t, { id: 'u:1:z9', label: null, rank: null }, 'manual', 0)).toBe('z9');
    expect(zoneDisplayLabel(t, { id: 'a', label: 'T1', rank: 1 }, 'manual', 0)).toBe('T1');
  });
  it('zoneLabelsFor is null when nothing is named by level', () => {
    expect(zoneLabelsFor(t, [{ id: 'a', label: 'T1', rank: 1 } as any], undefined)).toBeNull();
    expect(zoneLabelsFor(t, [], undefined)).toBeNull();
  });
});

describe('request and map', () => {
  it('toVraRequest sends zone_labels in per-zone mode only when given', () => {
    const base = { ...initialWorkState.vra.config, enabled: true, zoningRunId: RUN, zoneRates: { a: 1 }, restRate: 0 };
    expect(toVraRequest(base)!.zone_labels).toBeUndefined();
    expect(toVraRequest({ ...base, zoneLabels: {} })!.zone_labels).toBeUndefined();
    expect(toVraRequest({ ...base, zoneLabels: { a: 'Vigor alto' } })!.zone_labels).toEqual({ a: 'Vigor alto' });
    const classMode = { ...base, zoneRates: undefined, zoneLabels: { a: 'x' },
      classes: [{ minPct: 0, maxPct: 100, rate: 1 }] };
    expect(toVraRequest(classMode)!.zone_labels).toBeUndefined();
  });

  const sq = (x: number): any => ({ type: 'Polygon', coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]] });
  const rx: any = {
    unit: 'kg_ha', product: 'N', warnings: [],
    classes: [{ index: 0, zone_id: 'a', label: 'Vigor alto', rate: 10 }, { index: 1, zone_id: 'b', label: 'Vigor bajo', rate: 20 },
      { index: 2, zone_id: null, rest: true, label: 'Rest of parcel', rate: 5 }],
    zones: { type: 'FeatureCollection', features: [
      { type: 'Feature', geometry: sq(0), properties: { class_index: 0, rate: 10, zone_id: 'a', label: 'Vigor alto' } },
      { type: 'Feature', geometry: sq(2), properties: { class_index: 1, rate: 20, zone_id: 'b', label: 'Vigor bajo' } },
    ] },
    swath_segments: { type: 'FeatureCollection', features: [] },
  };
  const model: any = { parcel: null, zones: [], marginM: null, accessPoint: null, accessIssue: null, plan: null,
    stale: false, hoveredSwath: null, selectedWarning: null, vra: rx, vraRateLabel: (r: number) => `${r} kg/ha` };

  it('map labels carry the zone name only when asked', () => {
    const plain = buildSources(model)['vra-classes'].features.filter((f) => f.properties?.part === 'label');
    expect(plain.map((f) => f.properties?.label)).toEqual(['10 kg/ha', '20 kg/ha']);
    const named = buildSources({ ...model, vraZoneNames: true })['vra-classes'].features.filter((f) => f.properties?.part === 'label');
    expect(named.map((f) => f.properties?.label)).toEqual(['Vigor alto · 10 kg/ha', 'Vigor bajo · 20 kg/ha']);
  });

  it('legend rows: zone names with their colours, never the rest of the parcel', () => {
    expect(vraLegendRows(model)).toEqual([]);
    const rows = vraLegendRows({ ...model, vraZoneNames: true });
    expect(rows.map((r) => r.label)).toEqual(['Vigor alto', 'Vigor bajo']);
    expect(rows[0].color).not.toBe(rows[1].color);
    render(<MapLegend zones={rows} />);
    expect(screen.getAllByTestId('map-legend-zone').map((e) => e.textContent)).toEqual(['Vigor alto', 'Vigor bajo']);
  });
});
