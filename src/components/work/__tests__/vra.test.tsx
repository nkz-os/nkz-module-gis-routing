import React, { useReducer } from 'react';
import { act, cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { initialWorkState, stepStatus, workReducer, type WorkState } from '../../../state/workMachine';
import { useVraSync } from '../../../state/useVraSync';
import { StepVra } from '../StepVra';
import { equalClasses, moveCut } from '../vraClasses';

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
    },
  };
});
import { api } from '../../../services/api';

const poly = (x = 0, s = 0.001): GeoJSON.Polygon => ({
  type: 'Polygon', coordinates: [[[x, 0], [x + s, 0], [x + s, s], [x, s], [x, 0]]],
});
const dist = (means: number[], missing: { id: string; reason: string }[] = []) => ({
  source: 'orion' as const, variable: 'NDVI',
  zones: means.map((m, i) => ({ id: `z${i}`, mean: m, area_ha: 2, geometry: poly(i) })),
  missing,
  percentiles: Array.from({ length: 21 }, (_, i) => 0.2 + i * 0.03),
});
const presc = (warnings: any[] = []) => ({
  unit: 'kg_ha' as const, product: 'N',
  classes: [0, 1, 2].map((i) => ({ index: i, min_pct: 0, max_pct: 0, rate: 1, area_ha: 2 + i, product_total: 10 * (i + 1) })),
  zones: { type: 'FeatureCollection' as const, features: [] },
  swath_segments: { type: 'FeatureCollection' as const, features: [] },
  warnings,
});

function baseState(over: Partial<WorkState> = {}, vra: Partial<WorkState['vra']> = {}, cfg: Partial<WorkState['vra']['config']> = {}): WorkState {
  return {
    ...initialWorkState,
    phase: 'generated',
    activeStep: 'vra',
    parcel: { id: 'p1', name: 'Alpha', geometry: poly(0, 0.01) },
    parcelRequestId: 1,
    result: { plan: { swaths: [], prescription: null } as any, kind: 'valid', operationId: null },
    ...over,
    vra: {
      ...initialWorkState.vra, ...vra,
      config: { ...initialWorkState.vra.config, enabled: true, ...cfg },
    },
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

beforeAll(async () => { await i18n.changeLanguage('es'); });
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  (api.getDistribution as any).mockResolvedValue(dist([0.3, 0.5, 0.7, 0.9]));
  (api.prescription as any).mockResolvedValue({ prescription: presc() });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('vra helpers', () => {
  it('equalClasses splits 0-100 evenly and keeps rates by index', () => {
    const c = equalClasses(4, [{ minPct: 0, maxPct: 50, rate: 7 }, { minPct: 50, maxPct: 100, rate: null }]);
    expect(c.map((x) => [x.minPct, x.maxPct])).toEqual([[0, 25], [25, 50], [50, 75], [75, 100]]);
    expect(c.map((x) => x.rate)).toEqual([7, null, null, null]);
  });
  it('moveCut never crosses a neighbouring cut', () => {
    const c = equalClasses(3);
    expect(moveCut(c, 0, 90).map((x) => [x.minPct, x.maxPct])).toEqual([[0, 66], [66, 67], [67, 100]]);
    expect(moveCut(c, 1, 0).map((x) => [x.minPct, x.maxPct])).toEqual([[0, 33], [33, 34], [34, 100]]);
  });
});

describe('StepVra', () => {
  it('loads the distribution on open and renders histogram, cuts and one row per class', async () => {
    await mount(baseState());
    expect(api.getDistribution).toHaveBeenCalledWith('p1');
    expect(screen.getByTestId('vra-histogram')).toBeTruthy();
    expect(screen.getAllByTestId('vra-bar').length).toBeGreaterThan(0);
    expect(screen.getAllByTestId('vra-cut')).toHaveLength(2);
    expect(screen.getAllByTestId('vra-row')).toHaveLength(3);
  });

  it('lists zones without value outside the histogram', async () => {
    (api.getDistribution as any).mockResolvedValue(dist([0.3, 0.5], [{ id: 'zx', reason: 'no_mean_value' }]));
    await mount(baseState());
    expect(screen.getByTestId('vra-missing').textContent).toContain('zx: sin valor; regenera las zonas');
    expect(screen.getAllByTestId('vra-bar').length).toBeGreaterThan(0);
  });

  it('class count redistributes the cuts and adds rows', async () => {
    await mount(baseState());
    fireEvent.change(screen.getByLabelText('Número de clases'), { target: { value: '4' } });
    expect(screen.getAllByTestId('vra-row')).toHaveLength(4);
    expect(latest.vra.config.classes.map((c) => c.minPct)).toEqual([0, 25, 50, 75]);
    expect(screen.getAllByRole('slider')).toHaveLength(3);
  });

  it('a cut slider is clamped between its neighbours', async () => {
    await mount(baseState());
    fireEvent.change(screen.getByLabelText('Corte 1'), { target: { value: '80' } });
    expect(latest.vra.config.classes.map((c) => [c.minPct, c.maxPct])).toEqual([[0, 66], [66, 67], [67, 100]]);
  });

  it('invert toggles the config', async () => {
    await mount(baseState());
    fireEvent.click(screen.getByRole('button', { name: 'Invertir' }));
    expect(latest.vra.config.invert).toBe(true);
  });

  it('keeps the typed text in the rate field and stores a number', async () => {
    await mount(baseState());
    const input = screen.getByLabelText('Dosis de la clase 1') as HTMLInputElement;
    fireEvent.change(input, { target: { value: '0.5' } });
    expect(input.value).toBe('0.5');
    expect(latest.vra.config.classes[0].rate).toBe(0.5);
    fireEvent.change(input, { target: { value: '' } });
    expect(latest.vra.config.classes[0].rate).toBeNull();
  });

  it('debounces the prescription request by 500 ms and sends the latest config once', async () => {
    const withRates = baseState({}, {}, {
      classes: [{ minPct: 0, maxPct: 33, rate: 1 }, { minPct: 33, maxPct: 67, rate: 2 }, { minPct: 67, maxPct: 100, rate: 3 }],
    });
    await mount(withRates);
    expect(api.prescription).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Dosis de la clase 1'), { target: { value: '5' } });
    await flush(300);
    fireEvent.change(screen.getByLabelText('Dosis de la clase 1'), { target: { value: '6' } });
    await flush(499);
    expect(api.prescription).not.toHaveBeenCalled();
    await flush(1);
    expect(api.prescription).toHaveBeenCalledTimes(1);
    const arg = (api.prescription as any).mock.calls[0][0];
    expect(arg.parcelId).toBe('p1');
    expect(arg.vra.classes[0].rate).toBe(6);
    expect(latest.vra.prescription).not.toBeNull();
    // Editing the VRA config never marks the route stale and never regenerates it.
    expect(latest.stale).toBe(false);
    expect(latest.phase).toBe('generated');
  });

  it('does not request again for the config the route was generated with', async () => {
    const cfg = {
      classes: [{ minPct: 0, maxPct: 33, rate: 1 }, { minPct: 33, maxPct: 67, rate: 2 }, { minPct: 67, maxPct: 100, rate: 3 }],
    };
    const s = baseState({}, { prescription: presc() }, cfg);
    s.result = { plan: { swaths: [], prescription: presc() } as any, kind: 'valid', operationId: null };
    await mount(s);
    await flush(1000);
    expect(api.prescription).not.toHaveBeenCalled();
  });

  it('shows totals per class and overall', async () => {
    await mount(baseState({}, { prescription: presc() }));
    expect(screen.getByTestId('vra-total').textContent).toContain('60');
  });

  it('translates coded warnings and errors', async () => {
    await mount(baseState({}, {
      prescription: presc([{ code: 'VRA_UNCOVERED', params: { length_m: 12.5 } }, { code: 'VRA_DEGENERATE', params: {} }]),
      status: 'error', error: { code: 'INVALID_VRA', detail: '', params: {} },
    }));
    expect(screen.getByText('12.5 m de ruta quedan fuera de las zonas de manejo: no se aplica dosis')).toBeTruthy();
    expect(screen.getByText('Todas las zonas tienen el mismo valor: se aplica una sola clase')).toBeTruthy();
    expect(screen.getByRole('alert').textContent).toBe('La configuración de dosis variable no es válida');
  });

  it('is locked while generating', async () => {
    await mount(baseState({ phase: 'generating' }));
    expect((screen.getByLabelText('Número de clases') as HTMLSelectElement).disabled).toBe(true);
    expect((screen.getByLabelText('Dosis de la clase 1') as HTMLInputElement).disabled).toBe(true);
    expect((screen.getByRole('button', { name: 'Invertir' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('uploads an external file and keeps its zones in the config', async () => {
    const feature = { type: 'Feature', geometry: poly(0), properties: { zone_id: 'e1' } };
    (api.ingestExternalZones as any).mockResolvedValue({
      success: true, data: { count: 1, zones: [feature], distribution: { ...dist([0.4, 0.8]), source: 'external' } },
    });
    await mount(baseState({}, {}, { source: 'external' }));
    const file = new File(['{"type":"FeatureCollection"}'], 'z.geojson', { type: 'application/json' });
    (file as any).text = () => Promise.resolve('{"type":"FeatureCollection"}');
    fireEvent.change(screen.getByLabelText('Fichero de zonas (GeoJSON o CSV)'), { target: { files: [file] } });
    await flush(0);
    expect(api.ingestExternalZones).toHaveBeenCalledWith('geojson', '{"type":"FeatureCollection"}');
    expect(latest.vra.config.externalFeatures?.features).toEqual([feature]);
    expect(latest.vra.distribution?.source).toBe('external');
  });
});

describe('zone generation polling', () => {
  const empty = { source: 'orion' as const, variable: 'NDVI', zones: [], missing: [], percentiles: [] };

  it('requests 8 zones, polls every 5 s and shows the zones once they exist', async () => {
    (api.getDistribution as any).mockResolvedValue(empty);
    (api.requestZones as any).mockResolvedValue({});
    await mount(baseState());
    expect(screen.getByTestId('vra-nozones')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Generar zonas (8)' }));
    await flush(0);
    expect(api.requestZones).toHaveBeenCalledWith('p1', 8);
    expect(screen.getByText('Generando zonas…')).toBeTruthy();
    const before = (api.getDistribution as any).mock.calls.length;
    await flush(4999);
    expect((api.getDistribution as any).mock.calls.length).toBe(before);
    await flush(1);
    expect((api.getDistribution as any).mock.calls.length).toBe(before + 1);
    (api.getDistribution as any).mockResolvedValue(dist([0.3, 0.6]));
    await flush(5000);
    expect(screen.getAllByTestId('vra-row')).toHaveLength(3);
    expect(screen.queryByText('Generando zonas…')).toBeNull();
  });

  it('gives up after 2 minutes and offers a retry', async () => {
    (api.getDistribution as any).mockResolvedValue(empty);
    (api.requestZones as any).mockResolvedValue({});
    await mount(baseState());
    fireEvent.click(screen.getByRole('button', { name: 'Generar zonas (8)' }));
    await flush(0);
    const before = (api.getDistribution as any).mock.calls.length;
    await flush(120_000);
    expect((api.getDistribution as any).mock.calls.length).toBe(before + 24);
    expect(screen.getByText('La generación de zonas tarda demasiado.')).toBeTruthy();
    await flush(30_000);
    expect((api.getDistribution as any).mock.calls.length).toBe(before + 24);
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeTruthy();
  });

  it('reports a failed zone request with a translated error', async () => {
    (api.getDistribution as any).mockResolvedValue(empty);
    (api.requestZones as any).mockRejectedValue(new Error('boom'));
    await mount(baseState());
    fireEvent.click(screen.getByRole('button', { name: 'Generar zonas (8)' }));
    await flush(0);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(screen.getByRole('button', { name: 'Generar zonas (8)' })).toBeTruthy();
  });
});


const rated = (rates: (number | null)[]) => rates.map((rate, i) => ({ minPct: [0, 33, 67][i], maxPct: [33, 67, 100][i], rate }));

describe('prescription follows the config Save would send', () => {
  const withPresc = () => baseState({}, { prescription: presc(), status: 'ready' }, { classes: rated([1, 2, 3]) });

  it('disabling VRA clears the prescription; the step is optional, not complete', () => {
    const s = withPresc();
    expect(stepStatus(s, 'vra')).toBe('complete');
    const off = workReducer(s, { type: 'VRA_CONFIG_CHANGED', config: { enabled: false } });
    expect(off.vra.prescription).toBeNull();
    expect(stepStatus(off, 'vra')).toBe('optional');
  });

  it('clearing a rate clears the prescription', () => {
    const s = withPresc();
    const next = workReducer(s, { type: 'VRA_CONFIG_CHANGED', config: { classes: rated([1, null, 3]) } });
    expect(next.vra.prescription).toBeNull();
    expect(stepStatus(next, 'vra')).toBe('pending');
  });

  it('a result in flight when VRA is disabled is ignored', () => {
    let s = withPresc();
    s = workReducer(s, { type: 'VRA_REQUESTED', parcelRequestId: 1, requestId: s.vra.requestId + 1 });
    const inflight = s.vra.requestId;
    s = workReducer(s, { type: 'VRA_CONFIG_CHANGED', config: { enabled: false } });
    s = workReducer(s, { type: 'VRA_PRESCRIPTION_RESULT', parcelRequestId: 1, requestId: inflight, prescription: presc() });
    expect(s.vra.prescription).toBeNull();
    expect(s.vra.status).toBe('idle');
  });

  it('a valid edit keeps the prescription', () => {
    const next = workReducer(withPresc(), { type: 'VRA_CONFIG_CHANGED', config: { classes: rated([5, 2, 3]) } });
    expect(next.vra.prescription).not.toBeNull();
  });
});

describe('StepVra failure and source handling', () => {
  const cfg = { classes: rated([1, 2, 3]) };

  it('a failed prescription request shows the error and retries on demand', async () => {
    (api.prescription as any).mockRejectedValueOnce(new Error('boom'));
    await mount(baseState({}, {}, cfg));
    fireEvent.change(screen.getByLabelText('Dosis de la clase 1'), { target: { value: '9' } });
    await flush(500);
    expect(screen.getByRole('alert')).toBeTruthy();
    expect(api.prescription).toHaveBeenCalledTimes(1);
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    await flush(500);
    expect(api.prescription).toHaveBeenCalledTimes(2);
    expect(latest.vra.prescription).not.toBeNull();
  });

  it('shows poll errors while polling continues', async () => {
    (api.getDistribution as any).mockResolvedValue({ source: 'orion', variable: 'NDVI', zones: [], missing: [], percentiles: [] });
    (api.requestZones as any).mockResolvedValue({});
    await mount(baseState());
    fireEvent.click(screen.getByRole('button', { name: 'Generar zonas (8)' }));
    await flush(0);
    (api.getDistribution as any).mockRejectedValue(new Error('down'));
    await flush(5000);
    expect(screen.getByTestId('vra-pollerror')).toBeTruthy();
    expect(screen.getByText('Generando zonas…')).toBeTruthy();
  });

  it('external source without an upload hides the parcel zones and asks for a file', async () => {
    await mount(baseState({}, { distribution: dist([0.3, 0.6]) }, { source: 'external' }));
    expect(screen.queryByTestId('vra-histogram')).toBeNull();
    expect(screen.queryByTestId('vra-table')).toBeNull();
    expect(screen.getByTestId('vra-uploadprompt')).toBeTruthy();
  });
});
