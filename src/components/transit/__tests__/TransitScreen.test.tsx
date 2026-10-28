import React from 'react';
import { act, cleanup, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../../../i18n';

vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select aria-label={p.options[0]?.label} value={p.value} onChange={(e) => p.onValueChange(e.target.value)} disabled={p.disabled}>
      {p.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  return { ...actual, Select };
});

vi.mock('../../../map/TransitMapCanvas', () => ({
  TransitMapCanvas: (props: any) => {
    (window as any).__tm = props;
    return <div data-testid="tmap" />;
  },
}));

vi.mock('../../../services/exportTransit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/exportTransit')>();
  return { ...actual, downloadText: vi.fn() };
});

vi.mock('../../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api')>();
  return {
    ...actual,
    api: {
      listParcels: vi.fn(), listEquipment: vi.fn(), getParcelConfig: vi.fn(), getParcelsContext: vi.fn(),
      startPathCalculation: vi.fn(), getPathResult: vi.fn(), saveOperation: vi.fn(),
    },
  };
});
import { api, ApiError, type PathAlternative } from '../../../services/api';
import { downloadText } from '../../../services/exportTransit';
import { TransitScreen, parcelAtGate, parseLatLon } from '../TransitScreen';
import type { WorkContext } from '../../work/WorkScreen';

const alt = (id: PathAlternative['id'], dist: number): PathAlternative => ({
  id, label: id, distance_m: dist, cumulative_climb_m: 12.34, max_slope_deg_found: 8.5,
  geometry: { type: 'LineString', coordinates: [[0, 0], [0.001, 0.001]] },
  elevation_profile: [[0, 0, 100], [0.001, 0.001, 110]],
});
const completed = { status: 'completed', alternatives: [alt('least_slope', 321), alt('fastest', 210)], report: {} };
const ctx: WorkContext = { parcelId: null, parcelGeometry: null, machineWidthM: null, turningRadiusM: null };
const tm = () => (window as any).__tm;

const gatedParcel = { id: 'p1', name: 'North', geometry: { type: 'Polygon', coordinates: [] }, access_point: { type: 'Point', coordinates: [0.001, 0.001] }, zones: [] };

beforeEach(() => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  (api.listParcels as any).mockResolvedValue([{ id: 'p1', name: 'North' }, { id: 'p2', name: 'South' }]);
  (api.listEquipment as any).mockResolvedValue([{ id: 'm1', name: 'Sprayer', implementWidth: 4 }]);
  (api.getParcelConfig as any).mockResolvedValue({ accessPoint: null, exclusionZones: null });
  (api.getParcelsContext as any).mockResolvedValue({ parcels: [] });
  (api.startPathCalculation as any).mockResolvedValue({ job_id: 'j1' });
  (api.getPathResult as any).mockResolvedValue(completed);
  (api.saveOperation as any).mockResolvedValue({ success: true, operation_id: 'op-abcdefgh12345678', persisted: true });
});
afterEach(() => { cleanup(); vi.useRealTimers(); vi.clearAllMocks(); });

const advance = (ms: number) => act(async () => { await vi.advanceTimersByTimeAsync(ms); });

async function setup(workContext = ctx) {
  render(<TransitScreen workContext={workContext} />);
  await advance(0);
  await act(async () => { tm().onViewChange({ bbox: [0, 0, 0.05, 0.05], zoom: 14 }); });
  await advance(500);
}
async function place(a = [0, 0], b = [0.001, 0.001]) {
  await act(async () => { tm().onPick('a', a); tm().onPick('b', b); });
  fireEvent.change(screen.getByLabelText('Ancho de trabajo (m)'), { target: { value: '3' } });
}
async function calculate() {
  fireEvent.click(screen.getByRole('button', { name: 'Calcular ruta' }));
  await advance(1100);
}

describe('helpers', () => {
  it('parses lat, lon and rejects junk', () => {
    expect(parseLatLon('42.5, -1.25')).toEqual([-1.25, 42.5]);
    expect(parseLatLon('91, 0')).toBeNull();
    expect(parseLatLon('abc')).toBeNull();
  });
  it('matches the parcel whose gate is within 5 m', () => {
    expect(parcelAtGate([0.001, 0.001 + 0.00002], [gatedParcel as any])).toBe('p1');
    expect(parcelAtGate([0.001, 0.0011], [gatedParcel as any])).toBeNull();
  });
});

describe('TransitScreen', () => {
  it('shows the two alternative cards and highlights the chosen one on the map', async () => {
    await setup();
    await place();
    await calculate();
    const slope = await screen.findByTestId('alt-least_slope');
    expect(within(slope).getByText('Menos pendiente')).toBeTruthy();
    expect(slope.textContent).toContain('321 m');
    expect(slope.textContent).toContain('12.3 m');
    expect(screen.getByTestId('alt-fastest').textContent).toContain('210 m');
    expect(tm().model.selected).toBe('least_slope');
    fireEvent.click(screen.getByTestId('alt-fastest'));
    expect(tm().model.selected).toBe('fastest');
    expect(screen.getByTestId('elevation-profile')).toBeTruthy();
  });

  it('marks the point on the map when hovering the profile', async () => {
    await setup();
    await place();
    await calculate();
    const svg = (await screen.findByTestId('elevation-profile')).querySelector('svg')!;
    svg.getBoundingClientRect = () => ({ left: 0, width: 100, top: 0, height: 10, right: 100, bottom: 10, x: 0, y: 0, toJSON() {} }) as DOMRect;
    fireEvent.mouseMove(svg, { clientX: 100 });
    expect(tm().model.hover).toEqual([0.001, 0.001]);
    fireEvent.mouseLeave(svg);
    expect(tm().model.hover).toBeNull();
  });

  it('polls once per second and shows queued/running', async () => {
    (api.getPathResult as any).mockResolvedValueOnce({ status: 'queued' }).mockResolvedValueOnce({ status: 'running' });
    await setup();
    await place();
    fireEvent.click(screen.getByRole('button', { name: 'Calcular ruta' }));
    await advance(1100);
    expect(screen.getByRole('status').textContent).toBe('Esperando en la cola...');
    await advance(1000);
    expect(screen.getByRole('status').textContent).toBe('Calculando las rutas...');
    await advance(1000);
    expect(api.getPathResult).toHaveBeenCalledTimes(3);
    expect(await screen.findByTestId('alt-fastest')).toBeTruthy();
  });

  it('a double click on Calculate starts one job', async () => {
    await setup();
    await place();
    const btn = screen.getByRole('button', { name: 'Calcular ruta' });
    fireEvent.click(btn);
    fireEvent.click(btn);
    await advance(1100);
    expect(api.startPathCalculation).toHaveBeenCalledTimes(1);
    expect((api.startPathCalculation as any).mock.calls[0][0]).toEqual({
      point_a: [0, 0], point_b: [0.001, 0.001], machine_width_m: 3, max_slope_deg: 15,
    });
  });

  it('sends machine_id when a machine is picked', async () => {
    await setup();
    await act(async () => { tm().onPick('a', [0, 0]); tm().onPick('b', [0.001, 0.001]); });
    fireEvent.change(screen.getByLabelText('Ancho manual'), { target: { value: 'm1' } });
    await calculate();
    expect((api.startPathCalculation as any).mock.calls[0][0]).toMatchObject({ machine_id: 'm1', machine_width_m: 4 });
  });

  it.each([
    ['DEM_UNAVAILABLE', {}, 'No hay datos de elevación para esta zona.'],
    ['NO_PATH', {}, 'Ninguna ruta evita las zonas NO-GO y las parcelas con portón.'],
    ['NO_PATH', { search_margin_m: 500 }, 'Ninguna ruta evita las zonas NO-GO y las parcelas con portón (se buscó en 500 m alrededor de A-B).'],
    ['MACHINE_WIDTH_MISSING', {}, 'La máquina no tiene ancho de trabajo. Escríbelo.'],
    ['AREA_TOO_LARGE', {}, 'A y B están demasiado lejos para calcular la ruta.'],
    ['ENGINE_FAILURE', {}, 'Error interno del motor de rutas.'],
  ])('translates the failed-job code %s', async (code, params, text) => {
    (api.getPathResult as any).mockResolvedValue({ status: 'failed', error: 'x', error_code: code, error_params: params });
    await setup();
    await place();
    await calculate();
    expect((await screen.findByRole('alert')).textContent).toContain(text);
  });

  it('POINT_IN_ZONE paints B red and sends the geometry to the map', async () => {
    const geometry = { type: 'Point', coordinates: [0.001, 0.001] };
    (api.getPathResult as any).mockResolvedValue({ status: 'failed', error: 'x', error_code: 'POINT_IN_ZONE', error_params: { point: 'B', geometry } });
    await setup();
    await place();
    await calculate();
    expect((await screen.findByRole('alert')).textContent).toContain('El punto B está dentro de una zona NO-GO');
    expect(tm().model.badPoint).toBe('B');
    expect(tm().model.focus).toEqual(geometry);
  });

  it('times out after 5 minutes of polling', async () => {
    (api.getPathResult as any).mockResolvedValue({ status: 'running' });
    await setup();
    await place();
    fireEvent.click(screen.getByRole('button', { name: 'Calcular ruta' }));
    await advance(301_000);
    expect((await screen.findByRole('alert')).textContent).toContain('ha tardado demasiado');
  });

  it('marks the result stale after an edit and blocks saving until recalculated', async () => {
    await setup();
    await place();
    await calculate();
    await screen.findByTestId('alt-fastest');
    fireEvent.change(screen.getByLabelText('Sin parcela'), { target: { value: 'p2' } });
    const save = screen.getByRole('button', { name: 'Guardar como operación' }) as HTMLButtonElement;
    expect(save.disabled).toBe(false);
    await act(async () => { tm().onMarkerMoved('a', [0.0005, 0.0005]); });
    expect(screen.getByText(/Desactualizado/)).toBeTruthy();
    expect(save.disabled).toBe(true);
    expect(tm().model.stale).toBe(true);
    await calculate();
    expect(screen.queryByText(/Desactualizado/)).toBeNull();
    expect((screen.getByRole('button', { name: 'Guardar como operación' }) as HTMLButtonElement).disabled).toBe(false);
  });

  it('without a destination parcel Save is disabled with help text', async () => {
    await setup();
    await place();
    await calculate();
    await screen.findByTestId('alt-fastest');
    expect((screen.getByRole('button', { name: 'Guardar como operación' }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText(/Elige una parcela de destino/)).toBeTruthy();
  });

  it('defaults the destination to the parcel whose gate is at B and saves once', async () => {
    (api.getParcelsContext as any).mockResolvedValue({ parcels: [gatedParcel] });
    await setup();
    await place([0, 0], [0.001, 0.001]);
    await advance(0);
    await calculate();
    await screen.findByTestId('alt-fastest');
    expect((screen.getByLabelText('Sin parcela') as HTMLSelectElement).value).toBe('p1');
    let resolve!: (v: unknown) => void;
    (api.saveOperation as any).mockReturnValue(new Promise((r) => { resolve = r; }));
    const save = screen.getByRole('button', { name: 'Guardar como operación' });
    fireEvent.click(save);
    fireEvent.click(save);
    expect(api.saveOperation).toHaveBeenCalledTimes(1);
    expect(api.saveOperation).toHaveBeenCalledWith({ kind: 'transit', job_id: 'j1', alternative_id: 'least_slope', parcel_id: 'p1' });
    await act(async () => { resolve({ success: true, operation_id: 'op-abcdefgh12345678', persisted: true }); });
    expect((await screen.findByText('Disponible en la app · operación #12345678'))).toBeTruthy();
    expect((screen.getByRole('button', { name: 'Guardar como operación' }) as HTMLButtonElement).disabled).toBe(true);
  });

  it('shows a coded save error', async () => {
    await setup();
    await place();
    await calculate();
    await screen.findByTestId('alt-fastest');
    fireEvent.change(screen.getByLabelText('Sin parcela'), { target: { value: 'p2' } });
    (api.saveOperation as any).mockRejectedValue(new ApiError(404, { code: 'JOB_NOT_FOUND', detail: 'gone', params: {} }));
    fireEvent.click(screen.getByRole('button', { name: 'Guardar como operación' }));
    expect((await screen.findByRole('alert')).textContent).toContain('El cálculo ya no está disponible');
  });

  it('exports the chosen alternative on the client, without saving', async () => {
    await setup();
    await place();
    await calculate();
    await screen.findByTestId('alt-fastest');
    fireEvent.click(screen.getByTestId('alt-fastest'));
    fireEvent.click(screen.getByRole('button', { name: 'GPX' }));
    const [file, mime, content] = (downloadText as any).mock.calls[0];
    expect(file).toBe('transit-fastest.gpx');
    expect(mime).toContain('gpx');
    expect(content).toContain('<trkpt');
    fireEvent.click(screen.getByRole('button', { name: 'GeoJSON' }));
    const [file2, , json] = (downloadText as any).mock.calls[1];
    expect(file2).toBe('transit-fastest.geojson');
    expect(JSON.parse(json).properties.id).toBe('fastest');
    expect(api.saveOperation).not.toHaveBeenCalled();
  });

  it('uses the Work tab entrance as B', async () => {
    (api.getParcelConfig as any).mockResolvedValue({ accessPoint: { type: 'Point', coordinates: [0.002, 0.003] }, exclusionZones: null });
    await setup({ ...ctx, parcelId: 'p1' });
    fireEvent.click(await screen.findByRole('button', { name: 'Usar la entrada de North como B' }));
    expect(tm().model.b).toEqual([0.002, 0.003]);
  });

  it('fetches the parcel context only when zoomed in enough', async () => {
    await setup();
    expect(api.getParcelsContext).toHaveBeenCalledTimes(1);
    await act(async () => { tm().onViewChange({ bbox: [0, 0, 0.5, 0.5], zoom: 9 }); });
    await advance(500);
    expect(api.getParcelsContext).toHaveBeenCalledTimes(1);
    expect(screen.getByText('Acércate para ver parcelas, portones y zonas NO-GO')).toBeTruthy();
  });
});
