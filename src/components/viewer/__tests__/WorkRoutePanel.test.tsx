import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../../../i18n';

vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select aria-label="equipment" value={p.value} onChange={(e) => p.onValueChange(e.target.value)}>
      {p.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  return { ...actual, Select };
});
vi.mock('../../../services/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  api: { listEquipment: vi.fn(), getParcelGeometry: vi.fn(), generate: vi.fn(), saveOperation: vi.fn() },
}));
import { api, ApiError } from '../../../services/api';
import { WorkRoutePanel } from '../WorkRoutePanel';
import { EV } from '../routingMode';

const plan = {
  route: { type: 'LineString', coordinates: [[0, 0], [1, 1]] },
  metrics: { field_efficiency: 0.8, covered_area_ha: 1.5 },
};
const machine = (over: any = {}) => ({ id: 'm1', name: 'Sprayer', machine_role: 'implement', implementWidth: 18, minTurningRadius: 6, ...over });

beforeEach(() => {
  vi.mocked(api.getParcelGeometry).mockResolvedValue({ id: 'p', name: 'P', geometry: { type: 'Polygon', coordinates: [] } });
  vi.mocked(api.listEquipment).mockResolvedValue([machine()]);
  vi.mocked(api.generate).mockResolvedValue({ success: true, operation_id: null, persisted: false, plan: plan as any, plan_id: 'plan-1' });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const clickByText = (re: RegExp) => fireEvent.click(screen.getByRole('button', { name: re }));

describe('WorkRoutePanel', () => {
  it('takes width and turning radius from the machine and generates without persisting', async () => {
    render(<WorkRoutePanel parcelId="p" />);
    await waitFor(() => expect((screen.getByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement).value).toBe('18'));
    expect((screen.getByLabelText(/Radio de giro|Turning radius/i) as HTMLInputElement).value).toBe('6');
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(api.generate).toHaveBeenCalled());
    const body = vi.mocked(api.generate).mock.calls[0][0];
    expect(body.persist).toBe(false);
    expect(body.pattern_config.width_m).toBe(18);
    expect(body.pattern_config.turning_radius_m).toBe(6);
  });

  it('asks for manual values when the machine lacks them and sends what was typed', async () => {
    vi.mocked(api.listEquipment).mockResolvedValue([machine({ implementWidth: null, minTurningRadius: null })]);
    render(<WorkRoutePanel parcelId="p" />);
    const width = await screen.findByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement;
    await waitFor(() => expect(width.value).toBe(''));
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(screen.getByText(/ancho de trabajo|working width/i, { selector: 'p' })).toBeTruthy());
    expect(api.generate).not.toHaveBeenCalled();
    fireEvent.change(width, { target: { value: '12' } });
    fireEvent.change(screen.getByLabelText(/Radio de giro|Turning radius/i), { target: { value: '5.5' } });
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(api.generate).toHaveBeenCalled());
    const body = vi.mocked(api.generate).mock.calls[0][0];
    expect(body.pattern_config.width_m).toBe(12);
    expect(body.pattern_config.turning_radius_m).toBe(5.5);
  });

  it('translates a backend code, never shows it raw', async () => {
    vi.mocked(api.generate).mockRejectedValue(new ApiError(422, { code: 'TURNING_RADIUS_MISSING', detail: 'x' }));
    render(<WorkRoutePanel parcelId="p" />);
    await waitFor(() => expect((screen.getByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement).value).toBe('18'));
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(screen.getByText(/radio de giro|turning radius/i, { selector: 'p' })).toBeTruthy());
    expect(screen.queryByText(/TURNING_RADIUS_MISSING/)).toBeNull();
  });

  it('saves by plan_id and the routeGenerated event carries the operation_id', async () => {
    vi.mocked(api.saveOperation).mockResolvedValue({ success: true, operation_id: 'op-9', persisted: true, alert: 'sent' });
    const seen: any[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(EV.routeGenerated, on);
    render(<WorkRoutePanel parcelId="p" />);
    await waitFor(() => expect((screen.getByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement).value).toBe('18'));
    clickByText(/Generar|Generate/i);
    const save = await screen.findByRole('button', { name: /Guardar|Save/i });
    expect(seen.every((d) => !d.operation_id)).toBe(true); // the preview is not an operation yet
    fireEvent.click(save);
    await waitFor(() => expect(api.saveOperation).toHaveBeenCalledWith({ kind: 'plan', plan_id: 'plan-1' }));
    await waitFor(() => expect(seen.some((d) => d.operation_id === 'op-9')).toBe(true));
    window.removeEventListener(EV.routeGenerated, on);
  });

  it('does not offer to save a plan without plan_id', async () => {
    vi.mocked(api.generate).mockResolvedValue({ success: true, operation_id: null, persisted: false, plan: plan as any, plan_id: null });
    render(<WorkRoutePanel parcelId="p" />);
    await waitFor(() => expect((screen.getByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement).value).toBe('18'));
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(screen.getByText(/demasiado grande|too large/i, { selector: 'p' })).toBeTruthy());
    expect(screen.queryByRole('button', { name: /Guardar|Save/i })).toBeNull();
  });

  it('shows a progress line while the job runs and a translated timeout error with retry', async () => {
    let reject!: (e: unknown) => void;
    vi.mocked(api.generate).mockReturnValue(new Promise((_, rej) => { reject = rej; }) as any);
    render(<WorkRoutePanel parcelId="p" />);
    await waitFor(() => expect((screen.getByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement).value).toBe('18'));
    clickByText(/Generar|Generate/i);
    const notice = await screen.findByRole('status');
    expect(notice.textContent).toMatch(/Calculando la ruta\. En parcelas grandes.*hasta un minuto; no cierres la página\. \(0:00\)/);
    expect(notice.getAttribute('aria-live')).toBe('polite');
    reject(new ApiError(504, { code: 'GENERATE_TIMEOUT', detail: 'x' }));
    await waitFor(() => expect(screen.queryByRole('status')).toBeNull());
    expect(screen.getByText(/tard|too long/i, { selector: 'p' })).toBeTruthy();
    expect(screen.queryByText(/GENERATE_TIMEOUT/)).toBeNull();
    vi.mocked(api.generate).mockResolvedValue({ success: true, operation_id: null, persisted: false, plan: plan as any, plan_id: 'plan-1' });
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(api.generate).toHaveBeenCalledTimes(2));
  });

  it('aborts the request on unmount and ignores its late result', async () => {
    let resolve!: (v: any) => void;
    let signal: AbortSignal | undefined;
    vi.mocked(api.generate).mockImplementation(((_b: any, o: any) => {
      signal = o?.signal;
      return new Promise((r) => { resolve = r; });
    }) as any);
    const seen: any[] = [];
    const on = (e: Event) => seen.push((e as CustomEvent).detail);
    window.addEventListener(EV.routeGenerated, on);
    const view = render(<WorkRoutePanel parcelId="p" />);
    await waitFor(() => expect((screen.getByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement).value).toBe('18'));
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(signal).toBeDefined());
    view.unmount();
    expect(signal!.aborted).toBe(true);
    resolve({ success: true, operation_id: null, persisted: false, plan: plan as any, plan_id: 'plan-1' });
    await Promise.resolve(); await Promise.resolve();
    expect(seen).toEqual([]);
    window.removeEventListener(EV.routeGenerated, on);
  });

  it('passes a live AbortSignal while the request runs', async () => {
    const signals: AbortSignal[] = [];
    vi.mocked(api.generate).mockImplementation(((_b: any, o: any) => {
      signals.push(o.signal);
      return new Promise(() => {});
    }) as any);
    render(<WorkRoutePanel parcelId="p" />);
    await waitFor(() => expect((screen.getByLabelText(/Ancho de trabajo|Working width/i) as HTMLInputElement).value).toBe('18'));
    clickByText(/Generar|Generate/i);
    await waitFor(() => expect(signals.length).toBe(1));
    // the button is disabled while busy; a parcel switch is the other supersede path
    expect(signals[0].aborted).toBe(false);
  });
});
