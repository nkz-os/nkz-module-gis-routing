import React from 'react';
import { cleanup, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { WorkScreen } from '../WorkScreen';
import { fastPrefillFromSearch } from '../../../state/fastLink';

vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select value={p.value} onChange={(e) => p.onValueChange(e.target.value)}>
      {p.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  return { ...actual, Select };
});
vi.mock('../../../map/MapCanvas', () => ({ MapCanvas: () => <div data-testid="map" /> }));
vi.mock('../../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api')>();
  return {
    ...actual,
    api: {
      listParcels: vi.fn(), getParcelGeometry: vi.fn(), getParcelConfig: vi.fn(), getZoningZones: vi.fn(),
      listZonings: vi.fn(), getDistribution: vi.fn(), listEquipment: vi.fn(), saveParcelConfig: vi.fn(),
    },
  };
});
import { api } from '../../../services/api';

const poly = (): GeoJSON.Polygon => ({ type: 'Polygon', coordinates: [[[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]]] });
const Z1 = 'urn:ngsi-ld:AgriManagementZone:tenant-a:parcel-1:run-1-1';
const b64url = (o: unknown) =>
  btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
const req = (strategy: string, n = 60.04) => fastPrefillFromSearch(`?view=work&parcel=parcel-1&vra=${b64url({
  v: 1, source: 'fast', zoning_run_id: 'run-1', unit: 'kg_ha', product: 'NAC 27', zone_rates: { [Z1]: 240 }, rest_rate: 1,
  origin: { strategy, n_kg_ha: n },
})}`);

beforeAll(async () => { await i18n.changeLanguage('es'); });
beforeEach(() => {
  vi.clearAllMocks();
  (api.listParcels as any).mockResolvedValue([]);
  (api.getParcelGeometry as any).mockResolvedValue({ name: 'Alpha', geometry: poly() });
  (api.getParcelConfig as any).mockResolvedValue({ accessPoint: null, exclusionZones: { type: 'FeatureCollection', features: [] } });
  (api.getZoningZones as any).mockResolvedValue({ data: { zones: [{ id: Z1, label: 'A', rank: 1, area_ha: 1, geometry: poly() }] } });
  (api.listZonings as any).mockResolvedValue({ zonings: [] });
  (api.getDistribution as any).mockResolvedValue({ source: 'orion', variable: 'NDVI', zones: [], missing: [], percentiles: [] });
});
afterEach(cleanup);

const text = async () => (await screen.findByTestId('fast-notice')).textContent ?? '';

describe('FaST notice text', () => {
  it.each([['potential', 'potencial'], ['uniform', 'uniforme'], ['compensate', 'compensar']])(
    'names the known strategy %s', async (s, label) => {
      render(<WorkScreen prefill={req(s)} />);
      const t = await text();
      expect(t).toContain(`(${label}, 60 kg N/ha`);
    });

  it('formats n_kg_ha as a number', async () => {
    render(<WorkScreen prefill={req('potential', 1234.56)} />);
    expect(await text()).toContain('1234,6 kg N/ha');
  });

  it.each(['a.b', 'work.fast.failed.linkContent', 'x:y', '{{x}}', '__proto__', 'constructor', 'toString'])(
    'never shows or uses the raw strategy %s', async (s) => {
      render(<WorkScreen prefill={req(s)} />);
      const t = await text();
      expect(t).toContain('(otra, 60 kg N/ha');
      expect(t).not.toContain(s);
      expect(t).not.toContain('key');
    });

  it('shows the transient and work-started messages', async () => {
    (api.getZoningZones as any).mockRejectedValue(new TypeError('Failed to fetch'));
    render(<WorkScreen prefill={req('potential')} />);
    await waitFor(async () => expect(await text()).toContain('Recarga la página'));
  });
});
