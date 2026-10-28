import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor, act } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { WorkScreen, computeAccessIssue } from '../WorkScreen';
import App from '../../../App';

// Radix Select needs pointer APIs jsdom lacks: swap it for a native <select>.
vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select value={p.value} onChange={(e) => p.onValueChange(e.target.value)} disabled={p.disabled}>
      {p.options.map((o: any) => (
        <option key={o.value} value={o.value}>{o.label}</option>
      ))}
    </select>
  );
  return { ...actual, Select };
});

vi.mock('../../../map/MapCanvas', () => ({
  MapCanvas: (props: any) => {
    (window as any).__mapTest = props;
    return <div data-testid="map" />;
  },
}));

let transitMounts = 0;
vi.mock('../../transit/TransitScreen', () => ({
  TransitScreen: (props: any) => {
    const [id] = React.useState(() => ++transitMounts);
    return (
    <div data-testid="pf" data-mount={id}>Rutas A-B|{String(props.workContext.parcelId)}|{String(props.workContext.machineWidthM)}|{String(props.workContext.turningRadiusM)}</div>
    );
  },
}));

vi.mock('../../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api')>();
  return {
    ...actual,
    api: {
      listParcels: vi.fn(),
      getParcelGeometry: vi.fn(),
      getParcelConfig: vi.fn(),
      listEquipment: vi.fn(),
      generate: vi.fn(),
      saveOperation: vi.fn(),
      saveParcelConfig: vi.fn(),
      downloadExport: vi.fn(),
      getDistribution: vi.fn(), prescription: vi.fn(), requestZones: vi.fn(),
    },
  };
});
vi.mock('../../../services/exportTransit', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()), downloadBlob: vi.fn(),
}));
import { downloadBlob } from '../../../services/exportTransit';
import { api, ApiError } from '../../../services/api';

const poly = (s = 0.01): GeoJSON.Polygon => ({
  type: 'Polygon',
  coordinates: [[[0, 0], [s, 0], [s, s], [0, s], [0, 0]]],
});
const point: GeoJSON.Point = { type: 'Point', coordinates: [0.005, 0.005] };
const emptyFc = { type: 'FeatureCollection', features: [] };

const planFixture = (): any => ({
  pattern: 'boustrophedon', curve_type: 'dubins', swath_count: 12, headland_passes: 1,
  route: { type: 'LineString', coordinates: [[0, 0], [1, 1]] }, swaths: [],
  access_path: null, return_path: null, access_point: null, exit_point: point,
  working_area: poly(), unreached_parts: [],
  metrics: {
    worked_distance_m: 15676.2, non_working_distance_m: 0, access_distance_m: 0,
    access_leg_distance_m: 0, return_distance_m: 0, field_efficiency: 0.9274,
    covered_area_ha: 37.5, parcel_area_ha: 37.5, working_area_ha: 37.5,
  },
  validation: { ok: true, checks: [], fallbacks_applied: [], warnings: [] },
  exclusion_zones: emptyFc, prescription: null,
});

// The export-format select is also a combobox and renders first: find the parcel one by its option.
const parcelSelect = async () => (await screen.findByText('Alpha (3.2 ha)')).closest('select') as HTMLSelectElement;
const mapProps = () => (window as any).__mapTest;

/** Select the parcel, pick the implement (prefills width and radius) and wait for 'ready'. */
async function loadAndConfigure() {
  render(<WorkScreen />);
  const select = await parcelSelect();
  fireEvent.change(select, { target: { value: 'p1' } });
  await waitFor(() => expect(screen.getByRole('button', { name: /Zonas/ }).getAttribute('aria-expanded')).toBe('true'));
  fireEvent.click(screen.getByRole('button', { name: /Máquina/ }));
  const impl = (await screen.findByText('Sprayer')).closest('select') as HTMLSelectElement;
  fireEvent.change(impl, { target: { value: 'i1' } });
  await waitFor(() => expect((screen.getByRole('button', { name: /Generar ruta/i }) as HTMLButtonElement).disabled).toBe(false));
}

beforeAll(async () => {
  await i18n.changeLanguage('es');
});
beforeEach(() => {
  vi.clearAllMocks();
  (window as any).__mapTest = undefined;
  (api.listParcels as any).mockResolvedValue([{ id: 'p1', name: 'Alpha', area: 3.2 }]);
  (api.getParcelGeometry as any).mockResolvedValue({ id: 'p1', name: 'Alpha', geometry: poly() });
  (api.getParcelConfig as any).mockResolvedValue({ accessPoint: null, exclusionZones: emptyFc });
  (api.saveParcelConfig as any).mockResolvedValue({});
  (api.listEquipment as any).mockResolvedValue([
    { id: 'i1', name: 'Sprayer', category: 'implement', implementWidth: 24, minTurningRadius: 6 },
  ]);
});
afterEach(cleanup); // vitest globals are off, so RTL does not auto-clean

describe('computeAccessIssue', () => {
  it('flags outside, in a valid zone, or none', () => {
    const zone = { id: 'z', polygon: poly(0.002), areaHa: 1, valid: true };
    expect(computeAccessIssue({ type: 'Point', coordinates: [1, 1] }, poly(), [])).toBe('outside');
    expect(computeAccessIssue({ type: 'Point', coordinates: [0.001, 0.001] }, poly(), [zone])).toBe('in_zone');
    expect(computeAccessIssue({ type: 'Point', coordinates: [0.001, 0.001] }, poly(), [{ ...zone, valid: false }])).toBeNull();
    expect(computeAccessIssue(point, poly(), [zone])).toBeNull();
  });
});

describe('WorkScreen', () => {
  it('shows the empty state until a parcel is loaded, then the step list with zones active', async () => {
    render(<WorkScreen />);
    expect(screen.getByText('Selecciona una parcela para empezar')).toBeTruthy();
    const select = await parcelSelect();
    fireEvent.change(select, { target: { value: 'p1' } });
    await waitFor(() => expect(screen.queryByText('Selecciona una parcela para empezar')).toBeNull());
    expect(screen.getByRole('button', { name: /Zonas/ }).getAttribute('aria-expanded')).toBe('true');
  });

  it('generate: verifies config, calls api.generate with persist:false and renders the result strip', async () => {
    (api.generate as any).mockResolvedValue({ success: true, operation_id: null, persisted: false, plan_id: 'plan-1', plan: planFixture() });
    await loadAndConfigure();
    fireEvent.click(screen.getByRole('button', { name: /Generar ruta/i }));
    await screen.findByText(/12 pasadas/);
    expect(api.generate).toHaveBeenCalledTimes(1);
    expect((api.generate as any).mock.calls[0][0]).toMatchObject({ persist: false, parcel_id: 'p1' });
  });

  it('a 422 ACCESS_IN_ZONE renders the translated error with show-on-map', async () => {
    const err = new ApiError(422, {
      code: 'ACCESS_IN_ZONE', detail: 'gate in zone', params: { point },
    });
    (api.generate as any).mockRejectedValue(err);
    await loadAndConfigure();
    fireEvent.click(screen.getByRole('button', { name: /Generar ruta/i }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('El punto de acceso está dentro de una zona excluida');
    fireEvent.click(screen.getByRole('button', { name: 'Ver en el mapa' }));
    await waitFor(() => expect(mapProps().model.focus).toEqual(point));
  });

  it('save: persists the reviewed plan by id without a second /generate', async () => {
    (api.generate as any).mockResolvedValue({ success: true, operation_id: null, persisted: false, plan_id: 'plan-1', plan: planFixture() });
    (api.saveOperation as any).mockResolvedValue({ success: true, operation_id: 'op-12345678', persisted: true });
    await loadAndConfigure();
    fireEvent.click(screen.getByRole('button', { name: /Generar ruta/i }));
    await screen.findByText(/12 pasadas/);
    fireEvent.click(screen.getByRole('button', { name: 'Enviar al tractor' }));
    await screen.findByText('Guardada (12345678)');
    expect(api.generate).toHaveBeenCalledTimes(1);
    expect((api.generate as any).mock.calls[0][0].persist).toBe(false);
    expect(api.saveOperation).toHaveBeenCalledWith({ kind: 'plan', plan_id: 'plan-1' });
    expect(screen.getByText('op-12345678')).toBeTruthy();
  });

  async function savedPlan() {
    (api.generate as any).mockResolvedValue({ success: true, operation_id: null, persisted: false, plan_id: 'plan-1', plan: planFixture() });
    (api.saveOperation as any).mockResolvedValue({ success: true, operation_id: 'op-12345678', persisted: true });
    await loadAndConfigure();
    fireEvent.click(screen.getByRole('button', { name: /Generar ruta/i }));
    await screen.findByText(/12 pasadas/);
    fireEvent.click(screen.getByRole('button', { name: 'Enviar al tractor' }));
    await screen.findByText('Guardada (12345678)');
  }

  it('a saved plan is handed to the cockpit through sessionStorage', async () => {
    sessionStorage.removeItem('nkz:gis-routing:lastSaved');
    await savedPlan();
    const stored = JSON.parse(sessionStorage.getItem('nkz:gis-routing:lastSaved') ?? 'null');
    expect(stored.operation_id).toBe('op-12345678');
    expect(stored.geometry).toEqual({ type: 'LineString', coordinates: [[0, 0], [1, 1]] });
    expect(typeof stored.timestamp).toBe('number');
  });

  it('export downloads the file through fetch, not a new tab', async () => {
    await savedPlan();
    const blob = new Blob(['x']);
    (api.downloadExport as any).mockResolvedValue({ blob, filename: 'op.xml' });
    const open = vi.spyOn(window, 'open');
    fireEvent.click(screen.getByRole('button', { name: 'Exportar' }));
    await waitFor(() => expect(downloadBlob).toHaveBeenCalledWith('op.xml', blob));
    expect(api.downloadExport).toHaveBeenCalledWith('op-12345678', 'isoxml');
    expect(open).not.toHaveBeenCalled();
  });

  it('a refused export shows its coded error and downloads nothing', async () => {
    await savedPlan();
    (api.downloadExport as any).mockRejectedValue(new ApiError(422, { code: 'IMPLEMENT_WIDTH_MISSING', detail: 'x', params: {} }));
    fireEvent.click(screen.getByRole('button', { name: 'Exportar' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toMatch(/ancho/i);
    expect(downloadBlob).not.toHaveBeenCalled();
  });

  it('clicking a warning on the strip focuses its geometry and bumps fitKey', async () => {
    const turn: GeoJSON.LineString = { type: 'LineString', coordinates: [[0.001, 0.001], [0.002, 0.002]] };
    const plan = planFixture();
    plan.validation.warnings = [{ code: 'MANUAL_TURN', geometry: turn, params: { from_swath: 1, to_swath: 2 } }];
    (api.generate as any).mockResolvedValue({ success: true, operation_id: null, persisted: false, plan });
    await loadAndConfigure();
    fireEvent.click(screen.getByRole('button', { name: /Generar ruta/i }));
    await screen.findByText(/12 pasadas/);
    const before = mapProps().fitKey;
    fireEvent.click(screen.getByRole('button', { name: 'Ver en el mapa' }));
    await waitFor(() => expect(mapProps().model.focus).toEqual(turn));
    expect(mapProps().fitKey).not.toBe(before);
  });

  it('map callbacks: a drawn zone containing the gate flags the access issue', async () => {
    render(<WorkScreen />);
    const select = await parcelSelect();
    fireEvent.change(select, { target: { value: 'p1' } });
    await waitFor(() => expect(mapProps().model.parcel).not.toBeNull());
    act(() => mapProps().onAccessPlaced(point));
    await waitFor(() => expect(mapProps().model.accessPoint).toEqual(point));
    expect(mapProps().model.accessIssue).toBeNull();
    act(() => mapProps().onZoneDrawn(poly(0.008)));
    await waitFor(() => expect(mapProps().model.accessIssue).toBe('in_zone'));
    expect(mapProps().model.zones).toHaveLength(1);
  });
});

describe('WorkScreen request flow', () => {
  const okResponse = () => ({ success: true, operation_id: null, persisted: false, plan_id: 'plan-1', plan: planFixture() });
  const clickGenerate = () => fireEvent.click(screen.getByRole('button', { name: /Generar ruta|Regenerar/i }));

  it('a double click on Generar sends one request (state machine locks before any await)', async () => {
    let resolve!: (v: unknown) => void;
    (api.generate as any).mockImplementation(() => new Promise((r) => { resolve = r; }));
    await loadAndConfigure();
    const btn = screen.getByRole('button', { name: /Generar ruta/i });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(api.generate).toHaveBeenCalledTimes(1));
    expect(screen.getByRole('button', { name: /Generar ruta/i })).toBeDisabled();
    expect(mapProps().locked).toBe(true);
    await act(async () => { resolve(okResponse()); });
    await screen.findByText(/12 pasadas/);
    expect(api.generate).toHaveBeenCalledTimes(1);
    expect(mapProps().locked).toBe(false);
  });

  it('Generar works again straight from a failed generation (no Reintentar needed)', async () => {
    (api.generate as any)
      .mockRejectedValueOnce(new ApiError(500, { code: 'ENGINE_FAILURE', detail: 'x' }))
      .mockResolvedValueOnce(okResponse());
    await loadAndConfigure();
    clickGenerate();
    await screen.findByRole('alert');
    clickGenerate();
    await screen.findByText(/12 pasadas/);
    expect(api.generate).toHaveBeenCalledTimes(2);
  });

  it('a failed self-check blocks generation with a coded error', async () => {
    await loadAndConfigure();
    (api.getParcelConfig as any).mockRejectedValue(new Error('down'));
    clickGenerate();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('No se pudo verificar la configuración guardada');
    expect(api.generate).not.toHaveBeenCalled();
  });

  it('a failed self-check also blocks saving', async () => {
    (api.generate as any).mockResolvedValue(okResponse());
    await loadAndConfigure();
    clickGenerate();
    await screen.findByText(/12 pasadas/);
    (api.getParcelConfig as any).mockRejectedValue(new Error('down'));
    fireEvent.click(screen.getByRole('button', { name: 'Enviar al tractor' }));
    await screen.findByRole('alert');
    expect(api.generate).toHaveBeenCalledTimes(1);
  });

  it('an error without a backend code shows the HTTP status, not an engine fault', async () => {
    (api.generate as any).mockRejectedValue(new ApiError(401, { detail: 'Invalid token' }));
    await loadAndConfigure();
    clickGenerate();
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('HTTP 401');
    expect(alert.textContent).toContain('Invalid token');
    expect(alert.textContent).not.toContain('Error interno del motor');
  });

  it('a double click on Enviar sends one save', async () => {
    let resolve!: (v: unknown) => void;
    (api.generate as any).mockResolvedValue(okResponse());
    (api.saveOperation as any).mockImplementation(() => new Promise((r) => { resolve = r; }));
    await loadAndConfigure();
    clickGenerate();
    await screen.findByText(/12 pasadas/);
    const btn = screen.getByRole('button', { name: 'Enviar al tractor' });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await waitFor(() => expect(api.saveOperation).toHaveBeenCalledTimes(1));
    await act(async () => { resolve({ success: true, operation_id: 'op-12345678', persisted: true }); });
    await screen.findByText('Guardada (12345678)');
    expect(api.saveOperation).toHaveBeenCalledTimes(1);
  });

  it('Save regenerates once when the VRA changed since generating, saves the new plan and announces it', async () => {
    const presc = {
      unit: 'kg_ha', product: 'N',
      classes: [0, 1, 2].map((i) => ({ index: i, min_pct: 0, max_pct: 0, rate: 1, area_ha: 1, product_total: 1 })),
      zones: emptyFc, swath_segments: emptyFc, warnings: [],
    };
    (api.getDistribution as any).mockResolvedValue({
      source: 'orion', variable: 'NDVI', missing: [], percentiles: Array.from({ length: 21 }, (_, i) => 0.2 + i * 0.03),
      zones: [0.3, 0.5, 0.7, 0.9].map((m, i) => ({ id: `z${i}`, mean: m, area_ha: 1, geometry: poly() })),
    });
    (api.prescription as any).mockResolvedValue({ prescription: presc });
    (api.generate as any)
      .mockResolvedValueOnce({ success: true, operation_id: null, persisted: false, plan_id: 'plan-1', plan: planFixture() })
      .mockResolvedValueOnce({ success: true, operation_id: null, persisted: false, plan_id: 'plan-2', plan: { ...planFixture(), prescription: presc } });
    (api.saveOperation as any).mockResolvedValue({ success: true, operation_id: 'op-12345678', persisted: true });
    await loadAndConfigure();
    clickGenerate();
    await screen.findByText(/12 pasadas/);

    fireEvent.click(screen.getByRole('button', { name: /VRA/ }));
    fireEvent.click(await screen.findByLabelText('Aplicar dosis variable'));
    for (const n of [1, 2, 3]) fireEvent.change(await screen.findByLabelText(`Dosis de la clase ${n}`), { target: { value: String(n) } });
    await waitFor(() => expect(api.prescription).toHaveBeenCalled(), { timeout: 3000 });
    await waitFor(() => expect((screen.getByRole('button', { name: 'Enviar al tractor' }) as HTMLButtonElement).disabled).toBe(false));

    fireEvent.click(screen.getByRole('button', { name: 'Enviar al tractor' }));
    await screen.findByText('Guardada (12345678)');
    expect(api.generate).toHaveBeenCalledTimes(2);
    expect((api.generate as any).mock.calls[1][0]).toMatchObject({ persist: false, vra: expect.objectContaining({ enabled: true }) });
    expect(api.saveOperation).toHaveBeenCalledTimes(1);
    expect(api.saveOperation).toHaveBeenCalledWith({ kind: 'plan', plan_id: 'plan-2' });
    expect(screen.getByText('Plan regenerado con la dosis actual antes de guardar')).toBeTruthy();
  });

  it('an expired plan shows the translated error and Generar de nuevo regenerates', async () => {
    (api.generate as any).mockResolvedValue(okResponse());
    (api.saveOperation as any).mockRejectedValue(new ApiError(410, { code: 'PLAN_EXPIRED', detail: 'gone' }));
    await loadAndConfigure();
    clickGenerate();
    await screen.findByText(/12 pasadas/);
    fireEvent.click(screen.getByRole('button', { name: 'Enviar al tractor' }));
    const alert = await screen.findByRole('alert');
    expect(alert.textContent).toContain('caducado');
    fireEvent.click(screen.getByRole('button', { name: 'Generar de nuevo' }));
    await waitFor(() => expect(api.generate).toHaveBeenCalledTimes(2));
  });

  it('removing the entrance: verify sees a cleared broker (no re-PUT); a stale broker gets an explicit null', async () => {
    (api.getParcelConfig as any).mockResolvedValue({ accessPoint: point, exclusionZones: emptyFc });
    (api.generate as any).mockResolvedValue(okResponse());
    render(<WorkScreen />);
    fireEvent.change(await parcelSelect(), { target: { value: 'p1' } });
    await waitFor(() => expect(mapProps().model.accessPoint).toEqual(point));
    fireEvent.click(screen.getByRole('button', { name: /Máquina/ }));
    fireEvent.change((await screen.findByText('Sprayer')).closest('select') as HTMLSelectElement, { target: { value: 'i1' } });
    fireEvent.click(screen.getByRole('button', { name: /Entrada/ }));
    fireEvent.click(await screen.findByRole('button', { name: 'Quitar entrada' }));
    await waitFor(() => expect(mapProps().model.accessPoint).toBeNull());

    (api.getParcelConfig as any).mockResolvedValue({ accessPoint: null, exclusionZones: emptyFc });
    clickGenerate();
    await screen.findByText(/12 pasadas/);
    expect(api.saveParcelConfig).not.toHaveBeenCalled();

    (api.getParcelConfig as any).mockResolvedValue({ accessPoint: point, exclusionZones: emptyFc });
    clickGenerate();
    await waitFor(() => expect(api.saveParcelConfig).toHaveBeenCalled());
    const [id, body] = (api.saveParcelConfig as any).mock.calls[0];
    expect(id).toBe('p1');
    expect(JSON.parse(JSON.stringify(body)).accessPoint).toBeNull();
  });

  it('a MultiPolygon zone loads as editable parts and survives the autosave payload', async () => {
    const part = (o: number) => [[[o, o], [o + 0.001, o], [o + 0.001, o + 0.001], [o, o + 0.001], [o, o]]];
    (api.getParcelConfig as any).mockResolvedValue({
      accessPoint: null,
      exclusionZones: { type: 'FeatureCollection', features: [
        { type: 'Feature', properties: { id: 'm' }, geometry: { type: 'MultiPolygon', coordinates: [part(0.002), part(0.006)] } },
      ] },
    });
    render(<WorkScreen />);
    fireEvent.change(await parcelSelect(), { target: { value: 'p1' } });
    await waitFor(() => expect(mapProps().model.zones.map((z: any) => z.id)).toEqual(['m#0', 'm#1']));
  });

  it('measures the result strip wrapper and refits when the strip appears', async () => {
    const spy = vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(function (this: Element) {
      const h = this.getAttribute('data-testid') === 'result-strip' ? 90 : 0;
      return { height: h, width: 0, top: 0, left: 0, right: 0, bottom: h, x: 0, y: 0, toJSON() {} } as DOMRect;
    });
    try {
      (api.generate as any).mockResolvedValue(okResponse());
      render(<WorkScreen />);
      await waitFor(() => expect(mapProps()).toBeDefined());
      expect(mapProps().bottomInset).toBe(90);
    } finally { spy.mockRestore(); }
  });
});

describe('App', () => {
  it('switching to the transit tab passes the work context to the pathfinding panel', async () => {
    render(<App />);
    expect(screen.queryByTestId('pf')).toBeNull();
    fireEvent.change(await parcelSelect(), { target: { value: 'p1' } });
    await waitFor(() => expect(mapProps().model.parcel).not.toBeNull());
    fireEvent.mouseDown(screen.getByRole('tab', { name: 'Tránsito A-B' }), { button: 0, ctrlKey: false }); // Radix activates on mousedown
    expect((await screen.findByTestId('pf')).textContent).toBe('Rutas A-B|p1|null|null');
  });

  it('the transit screen is mounted on first visit and survives tab switches (hidden, not unmounted)', async () => {
    render(<App />);
    const tab = (name: string) => fireEvent.mouseDown(screen.getByRole('tab', { name }), { button: 0, ctrlKey: false });
    expect(screen.queryByTestId('pf')).toBeNull();
    tab('Tránsito A-B');
    const first = await screen.findByTestId('pf');
    const mount = first.getAttribute('data-mount');
    expect(first.parentElement!.className).not.toContain('hidden');
    tab('Trabajo');
    await waitFor(() => expect(screen.getByTestId('pf').parentElement!.className).toContain('hidden'));
    tab('Tránsito A-B');
    await waitFor(() => expect(screen.getByTestId('pf').parentElement!.className).not.toContain('hidden'));
    expect(screen.getByTestId('pf').getAttribute('data-mount')).toBe(mount);
  });
});
