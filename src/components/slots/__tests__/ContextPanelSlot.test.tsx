import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../../../i18n';

vi.mock('@nekazari/viewer-kit', () => ({ SlotShell: (p: any) => <div>{p.children}</div> }));
vi.mock('@nekazari/sdk', async (importOriginal) => {
  const { createInstance } = await import('i18next');
  const i18n = createInstance();
  i18n.init({ lng: 'es', fallbackLng: 'en', defaultNS: 'gis-routing', resources: {}, interpolation: { escapeValue: false } });
  return {
    ...(await importOriginal<Record<string, unknown>>()),
    i18n,
    useTranslation: (ns?: string) => ({ t: i18n.getFixedT(null, ns ?? 'gis-routing'), i18n }),
    useViewer: () => ({ selectedEntityId: 'p1', selectedEntityType: 'AgriParcel' }),
  };
});
vi.mock('../../../services/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  api: {
    listPatterns: vi.fn(), getParcelConfig: vi.fn(), saveParcelConfig: vi.fn(),
    listEquipment: vi.fn(), saveOperation: vi.fn(), startOperation: vi.fn(), closeOperation: vi.fn(),
  },
}));
import { api } from '../../../services/api';
import { ContextPanelSlot } from '../ContextPanelSlot';
import { EV } from '../../viewer/routingMode';

const ring = [[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]];
const zone = (id: string) => ({ type: 'Feature', properties: { id }, geometry: { type: 'Polygon', coordinates: [ring] } });

beforeEach(() => {
  vi.mocked(api.listPatterns).mockResolvedValue({ data: [] });
  vi.mocked(api.saveParcelConfig).mockResolvedValue({ success: true, updated: [] });
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

async function openDraw(cfg: any) {
  vi.mocked(api.getParcelConfig).mockResolvedValue(cfg);
  render(<ContextPanelSlot />);
  await waitFor(() => expect(api.getParcelConfig).toHaveBeenCalled());
  await act(async () => {});
  fireEvent.click(screen.getByRole('button', { name: /Portón|Gate/i }));
}
const save = () => fireEvent.click(screen.getByRole('button', { name: /Guardar configuración|Save configuration/i }));

describe('cockpit config save', () => {
  it('saving a new gate does not touch the stored no-go zones', async () => {
    await openDraw({ accessPoint: null, exclusionZones: { type: 'FeatureCollection', features: [zone('a'), zone('b')] } });
    act(() => { window.dispatchEvent(new CustomEvent(EV.gatePicked, { detail: { lonlat: [3, 4] } })); });
    save();
    await waitFor(() => expect(api.saveParcelConfig).toHaveBeenCalled());
    const [id, body] = vi.mocked(api.saveParcelConfig).mock.calls[0];
    expect(id).toBe('p1');
    expect(body).toEqual({ accessPoint: { type: 'Point', coordinates: [3, 4] } });
    expect(api.saveOperation).not.toHaveBeenCalled();
  });

  it('saving a new zone leaves the gate alone', async () => {
    await openDraw({ accessPoint: { type: 'Point', coordinates: [1, 1] }, exclusionZones: null });
    act(() => { window.dispatchEvent(new CustomEvent(EV.zoneDrawn, { detail: { ring } })); });
    save();
    await waitFor(() => expect(api.saveParcelConfig).toHaveBeenCalled());
    const body: any = vi.mocked(api.saveParcelConfig).mock.calls[0][1];
    expect('accessPoint' in body).toBe(false);
    expect(body.exclusionZones.features).toHaveLength(1);
  });

  it('an empty collection goes out only when the user deleted the last zone', async () => {
    await openDraw({ accessPoint: null, exclusionZones: { type: 'FeatureCollection', features: [zone('a')] } });
    fireEvent.click(screen.getByTitle(/Eliminar|Delete/i));
    save();
    await waitFor(() => expect(api.saveParcelConfig).toHaveBeenCalled());
    expect(vi.mocked(api.saveParcelConfig).mock.calls[0][1]).toEqual({ exclusionZones: { type: 'FeatureCollection', features: [] } });
  });

  it('sends nothing when nothing changed', async () => {
    await openDraw({ accessPoint: null, exclusionZones: { type: 'FeatureCollection', features: [zone('a')] } });
    save();
    await act(async () => {});
    expect(api.saveParcelConfig).not.toHaveBeenCalled();
  });
});

describe('cockpit config load', () => {
  it('a config that failed to load blocks the save and says so', async () => {
    vi.mocked(api.getParcelConfig).mockRejectedValue(new Error('502'));
    render(<ContextPanelSlot />);
    await waitFor(() => expect(api.getParcelConfig).toHaveBeenCalled());
    await act(async () => {});
    fireEvent.click(screen.getByRole('button', { name: /Portón|Gate/i }));
    expect(screen.getByRole('alert').textContent).toMatch(/No se pudo cargar la configuración|Could not load/i);
    act(() => { window.dispatchEvent(new CustomEvent(EV.zoneDrawn, { detail: { ring } })); });
    save();
    await act(async () => {});
    expect(api.saveParcelConfig).not.toHaveBeenCalled();
  });

  it.each(['nkz:', 'https://nkz-os.org/ns/'])('reads zones and gate stored as %s names, so a new zone keeps them', async (prefix) => {
    await openDraw({
      [`${prefix}accessPoint`]: { type: 'Point', coordinates: [1, 1] },
      [`${prefix}exclusionZones`]: { type: 'FeatureCollection', features: [zone('a')] },
    });
    act(() => { window.dispatchEvent(new CustomEvent(EV.zoneDrawn, { detail: { ring } })); });
    save();
    await waitFor(() => expect(api.saveParcelConfig).toHaveBeenCalled());
    const body: any = vi.mocked(api.saveParcelConfig).mock.calls[0][1];
    expect('accessPoint' in body).toBe(false);
    expect(body.exclusionZones.features).toHaveLength(2);
  });
});

