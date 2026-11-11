import React, { useReducer } from 'react';
import { act, cleanup, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { initialWorkState, toVraRequest, workReducer, type WorkEvent, type WorkState } from '../../../state/workMachine';
import { useVraSync } from '../../../state/useVraSync';
import { useFastPrefill } from '../../../state/useFastPrefill';
import { fastPrefillFromSearch, type FastPrefillRequest } from '../../../state/fastLink';
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
      getParcelGeometry: vi.fn(), getParcelConfig: vi.fn(), getDistribution: vi.fn(), requestZones: vi.fn(),
      prescription: vi.fn(), listZonings: vi.fn(), getZoningZones: vi.fn(),
    },
  };
});
import { api, ApiError } from '../../../services/api';

const poly = (x = 0, s = 0.001): GeoJSON.Polygon => ({
  type: 'Polygon', coordinates: [[[x, 0], [x + s, 0], [x + s, s], [x, s], [x, 0]]],
});
const Z1 = 'urn:ngsi-ld:AgriManagementZone:tenant-a:parcel-1:run-1-1';
const Z2 = 'urn:ngsi-ld:AgriManagementZone:tenant-a:parcel-1:run-1-2';
const RUN = 'run-1';

const b64url = (o: unknown) =>
  btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const link = (over: Record<string, unknown> = {}) => ({
  v: 1, source: 'fast', zoning_run_id: RUN, unit: 'kg_ha', product: 'NAC 27',
  zone_rates: { [Z1]: 240, [Z2]: 180.5 }, rest_rate: 222.2,
  origin: { plan: 'plan-1', sheet: 'sheet-1', strategy: 'potential', n_kg_ha: 60 }, ...over,
});
const request = (over?: Record<string, unknown>) =>
  fastPrefillFromSearch(`?view=work&parcel=parcel-1&vra=${b64url(link(over))}`);

let latest: WorkState;
let send: React.Dispatch<WorkEvent>;
let settled = 0;
const Harness: React.FC<{ req: FastPrefillRequest | null; initial?: WorkState }> = ({ req, initial = initialWorkState }) => {
  const [state, dispatch] = useReducer(workReducer, initial);
  latest = state; send = dispatch;
  const sync = useVraSync(state, dispatch);
  const fast = useFastPrefill(req, state, dispatch, sync.setRateZones, () => { settled += 1; });
  return (
    <>
      {fast.notice && <p data-testid="notice">{JSON.stringify(fast.notice)}</p>}
      <StepVra state={state} dispatch={dispatch} sync={sync} />
    </>
  );
};

async function flush(ms = 0) {
  await act(async () => { await vi.advanceTimersByTimeAsync(ms); });
}
const notice = () => JSON.parse(screen.getByTestId('notice').textContent ?? 'null');

beforeAll(async () => { await i18n.changeLanguage('es'); });
beforeEach(() => {
  vi.useFakeTimers();
  vi.clearAllMocks();
  settled = 0;
  (api.getParcelGeometry as any).mockResolvedValue({ name: 'Alpha', geometry: poly(0, 0.01) });
  (api.getParcelConfig as any).mockResolvedValue({ exclusionZones: { type: 'FeatureCollection', features: [] }, accessPoint: null });
  (api.getZoningZones as any).mockResolvedValue({ data: { zones: [
    { id: Z1, label: 'Zona A', rank: 1, area_ha: 1.5, geometry: poly(0) },
    { id: Z2, label: 'Zona B', rank: 2, area_ha: 2, geometry: poly(1) },
  ] } });
  (api.listZonings as any).mockResolvedValue({ zonings: [
    { run_id: RUN, method: 'vegetationIndex', date: '2026-05-01T00:00:00Z', zone_count: 2, labels: [], is_default: true },
  ] });
  (api.getDistribution as any).mockResolvedValue({ source: 'orion', variable: 'NDVI', zones: [], missing: [], percentiles: [] });
});
afterEach(() => { cleanup(); vi.useRealTimers(); });

describe('FaST link prefill', () => {
  it('selects the parcel and sets the per-zone doses in one go', async () => {
    render(<Harness req={request()} />);
    await flush(0);
    expect(api.getZoningZones).toHaveBeenCalledWith('parcel-1', RUN);
    expect(latest.parcel?.id).toBe('parcel-1');
    expect(latest.vra.config).toMatchObject({
      enabled: true, source: 'orion', zoningRunId: RUN, unit: 'kg_ha', product: 'NAC 27', restRate: 222.2,
      zoneRates: { [Z1]: 240, [Z2]: 180.5 },
    });
    expect(toVraRequest(latest.vra.config)).toMatchObject({
      zoning_run_id: RUN, zone_rates: { [Z1]: 240, [Z2]: 180.5 }, rest_rate: 222.2, unit: 'kg_ha', product: 'NAC 27',
    });
    expect(notice()).toMatchObject({ kind: 'applied', strategy: 'potential', nKgHa: 60 });
    expect(settled).toBe(1);
    // nothing is generated or requested on its own
    expect(latest.phase).toBe('configuring');
    expect(latest.result).toBeNull();
    expect(api.prescription).not.toHaveBeenCalled();
  });

  it('shows zone labels and doses in the step, and the technician can edit them', async () => {
    render(<Harness req={request()} />);
    await flush(0);
    act(() => send({ type: 'STEP_ACTIVATED', step: 'vra' }));
    await flush(0);
    expect(screen.getAllByTestId('vra-zone-row')).toHaveLength(2);
    expect(screen.getByLabelText('Dosis de la zona Zona A')).toHaveValue(240);
    expect(screen.getByLabelText('Dosis del resto de la parcela')).toHaveValue(222.2);
    act(() => send({ type: 'VRA_CONFIG_CHANGED', config: { restRate: 100 } }));
    expect(latest.vra.config.restRate).toBe(100);
    expect(latest.vra.config.zoneRates).toEqual({ [Z1]: 240, [Z2]: 180.5 });
  });

  it('drops the notice when the technician changes zoning or parcel', async () => {
    render(<Harness req={request()} />);
    await flush(0);
    expect(screen.queryByTestId('notice')).not.toBeNull();
    act(() => send({ type: 'VRA_CONFIG_CHANGED', config: { zoningRunId: 'other-run', zoneRates: undefined } }));
    await flush(0);
    expect(screen.queryByTestId('notice')).toBeNull();
  });

  it('applies nothing and says so when the link is invalid', async () => {
    render(<Harness req={fastPrefillFromSearch('?view=work&parcel=parcel-1&vra=%21')} />);
    await flush(0);
    expect(notice()).toEqual({ kind: 'failed', reason: 'not_base64' });
    expect(api.getParcelGeometry).not.toHaveBeenCalled();
    expect(latest).toEqual(initialWorkState);
    expect(settled).toBe(1);
  });

  it('applies nothing when the link has no parcel', async () => {
    render(<Harness req={fastPrefillFromSearch(`?view=work&vra=${b64url(link())}`)} />);
    await flush(0);
    expect(notice()).toEqual({ kind: 'failed', reason: 'parcel' });
    expect(latest).toEqual(initialWorkState);
  });

  it('applies nothing when the zoning no longer exists', async () => {
    (api.getZoningZones as any).mockRejectedValue(new ApiError(422, { code: 'ZONING_NOT_FOUND', detail: 'x', params: {} }));
    render(<Harness req={request()} />);
    await flush(0);
    expect(notice()).toEqual({ kind: 'failed', reason: 'zoning_missing' });
    expect(latest).toEqual(initialWorkState);
    expect(latest.parcel).toBeNull();
    expect(settled).toBe(1);
  });

  it('applies nothing when the zoning has no zones', async () => {
    (api.getZoningZones as any).mockResolvedValue({ data: { zones: [] } });
    render(<Harness req={request()} />);
    await flush(0);
    expect(notice()).toEqual({ kind: 'failed', reason: 'zoning_missing' });
    expect(latest).toEqual(initialWorkState);
  });

  it.each([
    ['a zone is missing from the link', { zone_rates: { [Z1]: 240 } }],
    ['the link has an extra zone', { zone_rates: { [Z1]: 240, [Z2]: 1, 'urn:extra': 3 } }],
    ['a zone id differs', { zone_rates: { [Z1]: 240, 'urn:other': 3 } }],
  ])('applies nothing when %s', async (_name, over) => {
    render(<Harness req={request(over)} />);
    await flush(0);
    expect(notice()).toEqual({ kind: 'failed', reason: 'zones_mismatch' });
    expect(latest).toEqual(initialWorkState);
    expect(latest.vra.config.zoneRates).toBeUndefined();
  });

  it('applies nothing when the zoning cannot be loaded', async () => {
    (api.getZoningZones as any).mockRejectedValue(new ApiError(502, { detail: 'down' }));
    render(<Harness req={request()} />);
    await flush(0);
    expect(notice()).toEqual({ kind: 'failed', reason: 'zoning_load' });
    expect(latest).toEqual(initialWorkState);
  });

  it('applies nothing when the parcel cannot be loaded', async () => {
    (api.getParcelGeometry as any).mockRejectedValue(new ApiError(404, { detail: 'nope' }));
    render(<Harness req={request()} />);
    await flush(0);
    expect(notice()).toEqual({ kind: 'failed', reason: 'parcel_load' });
    expect(latest).toEqual(initialWorkState);
  });

  it('does nothing without a link', async () => {
    render(<Harness req={null} />);
    await flush(0);
    expect(api.getParcelGeometry).not.toHaveBeenCalled();
    expect(screen.queryByTestId('notice')).toBeNull();
    expect(settled).toBe(0);
  });
});
