import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { initialWorkState, type WorkState } from '../../../state/workMachine';
import type { Plan } from '../../../services/api';
import { ResultStrip } from '../ResultStrip';
import { ActionsBar } from '../ActionsBar';
import { PatternSaveLoad } from '../../patterns/PatternSaveLoad';

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

vi.mock('../../../services/api', () => ({
  api: { savePattern: vi.fn().mockResolvedValue({}) },
}));
import { api } from '../../../services/api';

const poly = (s = 0.01): GeoJSON.Polygon => ({
  type: 'Polygon',
  coordinates: [[[0, 0], [s, 0], [s, s], [0, s], [0, 0]]],
});
const route: GeoJSON.LineString = { type: 'LineString', coordinates: [[0, 0], [1, 1]] };
const point: GeoJSON.Point = { type: 'Point', coordinates: [0.5, 0.5] };

const plan = (): Plan => ({
  pattern: 'boustrophedon', curve_type: 'dubins', swath_count: 12, headland_passes: 1,
  route, swaths: [], access_path: null, return_path: null, access_point: null,
  exit_point: point, working_area: poly(), unreached_parts: [],
  metrics: {
    worked_distance_m: 15676.2, non_working_distance_m: 0, access_distance_m: 0,
    access_leg_distance_m: 0, return_distance_m: 0, field_efficiency: 0.9274,
    covered_area_ha: 37.582, parcel_area_ha: 37.582, working_area_ha: 37.582,
  },
  validation: {
    ok: true, checks: [],
    fallbacks_applied: ['headland_passes:1->2'],
    warnings: [
      { code: 'MANUAL_TURN', geometry: point, params: { from_swath: 3, to_swath: 4 } },
      { code: 'HEADLAND_WIDENED', geometry: null, params: { requested: 1, applied: 2 } },
    ],
  },
  exclusion_zones: { type: 'FeatureCollection', features: [] },
  prescription: null,
});

const withResult = (over: Partial<WorkState> = {}, operationId: string | null = null): WorkState => ({
  ...initialWorkState,
  phase: 'generated',
  parcel: { id: 'p1', name: 'Alpha', geometry: poly() },
  machine: { ...initialWorkState.machine, widthM: 6, turningRadiusM: 5 },
  result: { plan: plan(), kind: 'with_warnings', operationId, planId: null, vraKey: null },
  ...over,
});

beforeAll(async () => {
  await i18n.changeLanguage('es');
});
beforeEach(() => vi.clearAllMocks());
afterEach(cleanup);

const bar = (state: WorkState, over: Record<string, unknown> = {}) => {
  const props = {
    state, dispatch: vi.fn(), onGenerate: vi.fn(), onSave: vi.fn(), onExport: vi.fn(),
    onShowError: vi.fn(), plan: state.result?.plan ?? null, ...over,
  };
  render(<ActionsBar {...(props as any)} />);
  return props;
};

describe('save confirmation and alert status', () => {
  it.each([
    ['sent', /Aviso registrado/], ['skipped', /Sin aviso: desactivado en ajustes/], ['failed', /No se pudo registrar el aviso/],
  ])('ActionsBar shows availability and alert %s after saving', (alert, text) => {
    const base = withResult({ phase: 'saved' }, 'urn:ngsi-ld:Op:abcdefgh12345678');
    bar({ ...base, result: { ...base.result!, alert } as any });
    expect(screen.getByText('Disponible en la app · operación #12345678')).toBeInTheDocument();
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});

describe('export errors', () => {
  it('shows a refused export translated by its code', () => {
    const base = withResult({ phase: 'saved' }, 'urn:ngsi-ld:Op:abcdefgh12345678');
    bar(base, { exportError: { code: 'IMPLEMENT_WIDTH_MISSING', detail: '', params: {} } });
    expect(screen.getByRole('alert').textContent).toMatch(/ancho/i);
  });
});

describe('result strip and actions bar', () => {
  it('ResultStrip renders metrics, warnings with show-on-map, stale badge and translated fallbacks', () => {
    const onWarningSelect = vi.fn();
    render(
      <ResultStrip state={withResult({ stale: true })} onWarningSelect={onWarningSelect} collapsed={false} onToggle={vi.fn()} />,
    );
    expect(screen.getByText(/15,7 km/)).toBeInTheDocument();
    expect(screen.getByText(/93 %/)).toBeInTheDocument();
    expect(screen.getByText(/37,6 \/ 37,6 ha/)).toBeInTheDocument();
    expect(screen.getByText(/2 avisos/)).toBeInTheDocument();
    expect(screen.getByText(/Giro manual entre las pasadas 3 y 4/)).toBeInTheDocument();
    expect(screen.getByText('Obsoleto')).toBeInTheDocument();
    expect(screen.getByText(/asadas de cabecera ajustadas de 1 a 2/)).toBeInTheDocument();
    const btns = screen.getAllByRole('button', { name: 'Ver en el mapa' });
    expect(btns).toHaveLength(1);
    fireEvent.click(btns[0]);
    expect(onWarningSelect).toHaveBeenCalledWith(1);
  });

  it('ResultStrip renders nothing without a result and hides the body when collapsed', () => {
    const { container, rerender } = render(
      <ResultStrip state={initialWorkState} onWarningSelect={vi.fn()} collapsed={false} onToggle={vi.fn()} />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(<ResultStrip state={withResult()} onWarningSelect={vi.fn()} collapsed onToggle={vi.fn()} />);
    expect(screen.getByRole('button', { name: /Expandir/ })).toHaveAttribute('aria-expanded', 'false');
    expect(screen.queryByText(/Giro manual/)).toBeNull();
  });

  it('ActionsBar: generate disabled until ready, send enabled after generated, saved shows the operation id', () => {
    const ready = bar({ ...initialWorkState, phase: 'configuring' });
    expect(screen.getByRole('button', { name: 'Generar Ruta' })).toBeDisabled();
    cleanup();
    const p2 = bar(withResult({ phase: 'generated' }, 'op-abcdef1234567890'));
    expect(screen.getByRole('button', { name: 'Generar Ruta' })).toBeEnabled();
    const send = screen.getByRole('button', { name: 'Enviar al tractor' });
    expect(send).toBeEnabled();
    fireEvent.click(send);
    expect(p2.onSave).toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Exportar' }));
    expect(p2.onExport).toHaveBeenCalledWith('isoxml');
    expect(ready.onGenerate).not.toHaveBeenCalled();
    cleanup();
    bar(withResult({ phase: 'saved', stale: true }, 'op-abcdef1234567890'));
    expect(screen.getByText(/Guardada.*34567890/)).toBeInTheDocument();
    expect(screen.getByText('op-abcdef1234567890')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Regenerar' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Enviar al tractor' })).toBeDisabled();
  });

  it('ActionsBar: failed state shows the coded message and show-on-map for geometric codes', () => {
    const state = withResult({
      phase: 'failed',
      error: { code: 'ACCESS_IN_ZONE', detail: 'x', params: { point } },
    });
    const p = bar(state);
    expect(screen.getByRole('alert')).toHaveTextContent('zona excluida');
    fireEvent.click(screen.getByRole('button', { name: 'Ver en el mapa' }));
    expect(p.onShowError).toHaveBeenCalledWith(point);
    fireEvent.click(screen.getByRole('button', { name: 'Reintentar' }));
    expect(p.dispatch).toHaveBeenCalledWith({ type: 'DISMISS_ERROR' });
  });

  it('ActionsBar: unknown error code falls back to the generic message without show-on-map', () => {
    bar(withResult({ phase: 'failed', error: { code: 'WAT', detail: 'boom', params: {} } }));
    expect(screen.getByRole('alert')).toHaveTextContent('boom');
    expect(screen.queryByRole('button', { name: 'Ver en el mapa' })).toBeNull();
  });

  it('PatternSaveLoad saves the route from plan', async () => {
    render(
      <PatternSaveLoad plan={plan()} parcelId="p1" tractorId={null} implementId={null}
        pattern="boustrophedon" patternConfig={{}} operationId="op-1" />,
    );
    fireEvent.change(screen.getByPlaceholderText('Nombre del patrón...'), { target: { value: 'mine' } });
    fireEvent.click(screen.getByRole('button', { name: 'Guardar' }));
    await waitFor(() => expect(api.savePattern).toHaveBeenCalled());
    const body = (api.savePattern as any).mock.calls[0][0];
    expect(JSON.parse(body.route_geojson)).toEqual(route);
    expect(body.vra_prescription_map).toBeNull();
    expect(body.source_operation_id).toBe('op-1');
  });
  it('ResultStrip formats the backend UNREACHED_AREA area_ha param and has no own positioning', () => {
    const p = plan();
    p.validation!.warnings = [{ code: 'UNREACHED_AREA', geometry: point, params: { area_ha: 2.54 } }];
    const state = withResult(); state.result!.plan = p;
    const { container } = render(<ResultStrip state={state} onWarningSelect={vi.fn()} collapsed={false} onToggle={vi.fn()} />);
    expect(screen.getByText('Zona sin cubrir de 2,5 ha')).toBeInTheDocument();
    expect(container.textContent).not.toContain('{{');
    // The wrapper positions the strip: an absolute root would measure as height 0.
    expect((container.firstElementChild as HTMLElement).className).not.toMatch(/\babsolute\b/);
  });

  it('PatternSaveLoad tells the user when saving the template fails', async () => {
    (api.savePattern as any).mockRejectedValueOnce(new Error('x'));
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(
      <PatternSaveLoad plan={plan()} parcelId="p1" tractorId={null} implementId={null}
        pattern="boustrophedon" patternConfig={{}} operationId="op-1" />,
    );
    fireEvent.change(screen.getByPlaceholderText(/./), { target: { value: 'T' } });
    fireEvent.click(screen.getByRole('button', { name: /Guardar/ }));
    expect(await screen.findByRole('alert')).toHaveTextContent('No se pudo guardar la plantilla');
  });
});
