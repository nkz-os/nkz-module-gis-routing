import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { initialWorkState, type WorkState } from '../../../state/workMachine';
import { StepList } from '../StepList';
import { StepParcel } from '../StepParcel';
import { StepZones } from '../StepZones';
import { StepAccess } from '../StepAccess';
import { StepMachine } from '../StepMachine';
import { StepPattern } from '../StepPattern';

// Radix Select needs pointer APIs jsdom lacks: swap it for a native <select>
// (same props contract) so tests can drive onValueChange. Everything else is real.
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

vi.mock('../../../services/api', () => ({
  api: {
    listParcels: vi.fn(),
    getParcelGeometry: vi.fn(),
    getParcelConfig: vi.fn(),
    listEquipment: vi.fn(),
  },
}));
import { api } from '../../../services/api';

const poly = (x: number, s = 0.001): GeoJSON.Polygon => ({
  type: 'Polygon',
  coordinates: [[[x, 0], [x + s, 0], [x + s, s], [x, s], [x, 0]]],
});
const zone = (id: string, valid = true, x = 0) => ({ id, polygon: poly(x), areaHa: 1, valid });
const parcelState = (over: Partial<WorkState> = {}): WorkState => ({
  ...initialWorkState,
  phase: 'configuring',
  parcel: { id: 'p1', name: 'Alpha', geometry: poly(0, 0.01) },
  ...over,
});
const autosave = (status: any = { state: 'clean', savedAt: null }) => ({
  status, retry: vi.fn(), verifyBeforeGenerate: vi.fn(),
});

beforeAll(async () => {
  await i18n.changeLanguage('es');
});
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup); // vitest globals are off, so RTL does not auto-clean

describe('work steps', () => {
  it('StepList shows six steps, VRA disabled, and dispatches STEP_ACTIVATED', () => {
    const dispatch = vi.fn();
    render(<StepList state={parcelState()} dispatch={dispatch}>{(s) => <div>body-{s}</div>}</StepList>);
    expect(screen.getAllByRole('button').length).toBeGreaterThanOrEqual(6);
    expect(screen.getByText('body-parcel')).toBeTruthy();
    // parcel row is active (glyph-only badge needs an accessible name)
    expect(screen.getByRole('button', { name: /Parcela.*Paso activo/ })).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: /Zonas/ }));
    expect(dispatch).toHaveBeenCalledWith({ type: 'STEP_ACTIVATED', step: 'zones' });
    dispatch.mockClear();
    const vra = screen.getByRole('button', { name: /VRA/ });
    fireEvent.click(vra);
    expect(dispatch).not.toHaveBeenCalled();
  });

  it('StepParcel loads geometry+config and dispatches PARCEL_LOADED with zones from the FeatureCollection', async () => {
    const dispatch = vi.fn();
    const fc = { type: 'FeatureCollection', features: [{ type: 'Feature', properties: { id: 'z1' }, geometry: poly(0) }] };
    (api.listParcels as any).mockResolvedValue([{ id: 'p1', name: 'Alpha', area: 3.2 }]);
    (api.getParcelGeometry as any).mockResolvedValue({ id: 'p1', name: 'Alpha', geometry: poly(0, 0.01) });
    (api.getParcelConfig as any).mockResolvedValue({ accessPoint: null, exclusionZones: fc });
    render(<StepParcel state={initialWorkState} dispatch={dispatch} />);
    const select = await screen.findByRole('combobox');
    await screen.findByText('Alpha (3.2 ha)');
    fireEvent.change(select, { target: { value: 'p1' } });
    expect(dispatch.mock.calls[0][0]).toMatchObject({ type: 'PARCEL_SELECTED', id: 'p1' });
    await waitFor(() => expect(dispatch).toHaveBeenCalledTimes(2));
    const ev = dispatch.mock.calls[1][0];
    expect(ev.type).toBe('PARCEL_LOADED');
    expect(ev.requestId).toBe(dispatch.mock.calls[0][0].requestId);
    expect(ev.name).toBe('Alpha');
    expect(ev.config.exclusionZones.features).toHaveLength(1);
  });

  it('StepParcel reports a load error and offers retry', async () => {
    const dispatch = vi.fn();
    const onLoadError = vi.fn();
    (api.listParcels as any).mockResolvedValue([{ id: 'p1', name: 'Alpha' }]);
    (api.getParcelGeometry as any).mockRejectedValue(Object.assign(new Error('Parcel not found'), { status: 404 }));
    (api.getParcelConfig as any).mockResolvedValue({ accessPoint: null, exclusionZones: null });
    render(<StepParcel state={initialWorkState} dispatch={dispatch} onLoadError={onLoadError} />);
    const select = await screen.findByRole('combobox');
    await screen.findByText('Alpha');
    fireEvent.change(select, { target: { value: 'p1' } });
    // Translated prefix + status; the raw backend message is not shown.
    await screen.findByText('Error al cargar la geometría (HTTP 404)');
    expect(screen.queryByText(/Parcel not found/)).toBeNull();
    expect(onLoadError).toHaveBeenCalledWith('Error al cargar la geometría (HTTP 404)');
    expect(screen.getByRole('button', { name: 'Reintentar' })).toBeTruthy();
  });

  it('StepParcel ignores a stale failed selection while a newer one loads', async () => {
    const dispatch = vi.fn();
    let rejectFirst!: (e: Error) => void;
    (api.listParcels as any).mockResolvedValue([{ id: 'p1', name: 'Alpha' }, { id: 'p2', name: 'Beta' }]);
    (api.getParcelGeometry as any).mockImplementation((id: string) =>
      id === 'p1'
        ? new Promise((_, rej) => { rejectFirst = rej; })
        : Promise.resolve({ id: 'p2', name: 'Beta', geometry: poly(0, 0.01) }));
    (api.getParcelConfig as any).mockResolvedValue({ accessPoint: null, exclusionZones: null });
    const onLoadError = vi.fn();
    render(<StepParcel state={initialWorkState} dispatch={dispatch} onLoadError={onLoadError} />);
    const select = await screen.findByRole('combobox');
    await screen.findByText('Beta');
    fireEvent.change(select, { target: { value: 'p1' } });
    fireEvent.change(select, { target: { value: 'p2' } });
    await waitFor(() => expect(dispatch.mock.calls.filter((c) => c[0].type === 'PARCEL_LOADED')).toHaveLength(1));
    rejectFirst(new Error('late boom'));
    await new Promise((r) => setTimeout(r, 20));
    expect(screen.queryByText('late boom')).toBeNull();
    expect(onLoadError).not.toHaveBeenCalled();
    const loaded = dispatch.mock.calls.map((c) => c[0]).filter((e) => e.type === 'PARCEL_LOADED');
    expect(loaded[0].id).toBe('p2');
  });

  it('StepMachine lets the user type 0.5 without rewriting the input', async () => {
    const dispatch = vi.fn();
    (api.listEquipment as any).mockResolvedValue([]);
    render(<StepMachine state={parcelState()} dispatch={dispatch} />);
    await waitFor(() => expect(screen.getAllByRole('spinbutton')).toHaveLength(2));
    const [width] = screen.getAllByRole('spinbutton') as HTMLInputElement[];
    fireEvent.change(width, { target: { value: '0' } });
    expect(dispatch).toHaveBeenLastCalledWith({ type: 'MACHINE_CHANGED', machine: { widthM: null, widthSource: 'manual' } });
    fireEvent.change(width, { target: { value: '0.5' } });
    expect(dispatch).toHaveBeenLastCalledWith({ type: 'MACHINE_CHANGED', machine: { widthM: 0.5, widthSource: 'manual' } });
    expect(width.value).toBe('0.5');
  });

  it('StepMachine ties the width and radius labels to their inputs', async () => {
    (api.listEquipment as any).mockResolvedValue([]);
    render(<StepMachine state={parcelState()} dispatch={vi.fn()} />);
    await waitFor(() => expect(screen.getAllByRole('spinbutton')).toHaveLength(2));
    expect(screen.getByLabelText(i18n.t('work.machine.width', { ns: 'gis-routing' })).tagName).toBe('INPUT');
    expect(screen.getByLabelText(i18n.t('work.machine.radius', { ns: 'gis-routing' })).tagName).toBe('INPUT');
  });

  it('StepZones lists zones with area and invalid badge; delete dispatches ZONES_CHANGED without it', () => {
    const dispatch = vi.fn();
    const state = parcelState({ zones: [zone('a'), zone('b', false, 0.002)] });
    render(
      <StepZones state={state} dispatch={dispatch} drawMode="none" setDrawMode={vi.fn()} autosave={autosave()} />,
    );
    expect(screen.getByText('Inválida')).toBeTruthy();
    expect(screen.getAllByText(/ha$/).length).toBeGreaterThanOrEqual(2);
    const del = screen.getAllByRole('button', { name: 'Eliminar zona' });
    expect(del).toHaveLength(2);
    fireEvent.click(del[1]);
    expect(dispatch).toHaveBeenCalledWith({ type: 'ZONES_CHANGED', zones: [state.zones[0]] });
  });

  it('StepZones toggles draw mode and shows autosave status and retry', () => {
    const setDrawMode = vi.fn();
    const a = autosave({ state: 'error', message: 'x' });
    render(
      <StepZones state={parcelState()} dispatch={vi.fn()} drawMode="none" setDrawMode={setDrawMode} autosave={a} />,
    );
    fireEvent.click(screen.getByRole('button', { name: /Dibujar zona/ }));
    expect(setDrawMode).toHaveBeenCalledWith('zone');
    expect(screen.getByText('Error al guardar')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(a.retry).toHaveBeenCalled();
  });

  it('StepAccess shows the issue text when accessIssue is set and toggles return-to-access', () => {
    const dispatch = vi.fn();
    const state = parcelState({
      accessPoint: { type: 'Point', coordinates: [0, 0] },
      accessIssue: 'outside',
    });
    render(
      <StepAccess state={state} dispatch={dispatch} drawMode="none" setDrawMode={vi.fn()} autosave={autosave()} />,
    );
    expect(screen.getByText('Entrada fuera de la parcela')).toBeTruthy();
    fireEvent.click(screen.getByLabelText('Volver a la entrada al terminar'));
    expect(dispatch).toHaveBeenCalledWith({ type: 'PATTERN_CHANGED', pattern: { returnToAccess: true } });
    dispatch.mockClear();
    fireEvent.click(screen.getByRole('button', { name: 'Quitar entrada' }));
    expect(dispatch).toHaveBeenCalledWith({ type: 'ACCESS_CHANGED', point: null, issue: null });
  });

  it('StepZones and StepAccess block drawing and removing while a request runs', () => {
    const busy = parcelState({ zones: [zone('a')], accessPoint: { type: 'Point', coordinates: [0, 0] }, phase: 'generating' });
    render(
      <>
        <StepZones state={busy} dispatch={vi.fn()} drawMode="none" setDrawMode={vi.fn()} autosave={autosave()} />
        <StepAccess state={busy} dispatch={vi.fn()} drawMode="none" setDrawMode={vi.fn()} autosave={autosave()} />
      </>,
    );
    expect(screen.getByRole('button', { name: /Dibujar zona/ })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Eliminar zona' })).toBeDisabled();
    expect(screen.getByRole('button', { name: 'Quitar entrada' })).toBeDisabled();
  });

  it('StepParcel links back to the entities view with the parcel query', async () => {
    (api.listParcels as any).mockResolvedValue([{ id: 'urn:p 1', name: 'Alpha' }]);
    render(<StepParcel state={parcelState({ parcel: { id: 'urn:p 1', name: 'Alpha', geometry: poly(0, 0.01) } })} dispatch={vi.fn()} />);
    const a = await screen.findByRole('link');
    expect(a.getAttribute('href')).toBe('/entities?parcel=urn%3Ap%201');
  });

  it('StepMachine prefills width and radius from the implement and marks them "from machine"; typing marks manual', async () => {
    const dispatch = vi.fn();
    (api.listEquipment as any).mockResolvedValue([
      { id: 't1', name: 'Tractor', category: 'tractor' },
      { id: 'i1', name: 'Sprayer', category: 'implement', implementWidth: 24, minTurningRadius: 6 },
    ]);
    render(<StepMachine state={parcelState()} dispatch={dispatch} />);
    await screen.findByText('Sprayer');
    // order: operation, tractor, implement
    fireEvent.change(screen.getAllByRole('combobox')[2], { target: { value: 'i1' } });
    expect(dispatch).toHaveBeenCalledWith({
      type: 'MACHINE_CHANGED',
      machine: { implementId: 'i1', widthM: 24, widthSource: 'machine', turningRadiusM: 6, radiusSource: 'machine' },
    });
  });

  it('StepMachine shows "from machine" badges and typing dispatches manual', async () => {
    const dispatch = vi.fn();
    (api.listEquipment as any).mockResolvedValue([]);
    const state = parcelState({
      machine: { ...initialWorkState.machine, widthM: 24, widthSource: 'machine', turningRadiusM: 6, radiusSource: 'machine' },
    });
    render(<StepMachine state={state} dispatch={dispatch} />);
    await waitFor(() => expect(api.listEquipment).toHaveBeenCalled());
    expect(screen.getAllByText('De la máquina')).toHaveLength(2);
    expect(screen.getByText('Ancho efectivo: 24 m')).toBeTruthy();
    const [width] = screen.getAllByRole('spinbutton');
    fireEvent.change(width, { target: { value: '30' } });
    expect(dispatch).toHaveBeenCalledWith({
      type: 'MACHINE_CHANGED', machine: { widthM: 30, widthSource: 'manual' },
    });
  });

  it('StepPattern defaults to auto and dispatches headlandPasses as number', () => {
    const dispatch = vi.fn();
    render(<StepPattern state={parcelState()} dispatch={dispatch} />);
    const [pattern, , headland] = screen.getAllByRole('combobox') as HTMLSelectElement[];
    expect(pattern.value).toBe('auto');
    expect(screen.getByRole('option', { name: 'Automático' })).toBeTruthy();
    fireEvent.change(headland, { target: { value: '2' } });
    expect(dispatch).toHaveBeenCalledWith({ type: 'PATTERN_CHANGED', pattern: { headlandPasses: 2 } });
    expect(screen.queryByRole('spinbutton')).toBeNull();
  });
});
