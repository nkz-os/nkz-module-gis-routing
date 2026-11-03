import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import { ManualZoningScreen } from '../ManualZoningScreen';

vi.mock('../../../map/MapCanvas', () => ({
  MapCanvas: (props: any) => {
    (window as any).__zoningMap = props;
    return <div data-testid="map" />;
  },
}));

vi.mock('../../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api')>();
  return {
    ...actual,
    api: {
      listZonings: vi.fn(), previewManualZoning: vi.fn(), saveManualZoning: vi.fn(),
      deleteZoning: vi.fn(), getParcelGeometry: vi.fn(),
    },
  };
});
import { api, ApiError } from '../../../services/api';

const poly = (x = 0, s = 0.001): GeoJSON.Polygon => ({
  type: 'Polygon', coordinates: [[[x, 0], [x + s, 0], [x + s, s], [x, s], [x, 0]]],
});
const PARCEL = poly(0, 0.01);
const MANUAL = 'manual-1a2b3c4d';
const map = () => (window as any).__zoningMap;

beforeAll(async () => { await i18n.changeLanguage('es'); });
beforeEach(() => {
  vi.clearAllMocks();
  (api.listZonings as any).mockResolvedValue({ zonings: [] });
  (api.previewManualZoning as any).mockResolvedValue({
    zones: [
      { rank: 1, label: 'T1', geometry: poly(0), area_m2: 10000 },
      { rank: 2, label: 'Z2', geometry: poly(1), area_m2: 25000 },
    ],
    rejected: [{ index: 0, reason: 'not_polygon' }],
    warnings: [],
  });
  (api.saveManualZoning as any).mockResolvedValue({ run_id: MANUAL, zone_count: 2 });
  (api.deleteZoning as any).mockResolvedValue({ run_id: MANUAL, deleted: 2 });
  (api.getParcelGeometry as any).mockResolvedValue({ id: 'p1', name: 'Alpha', geometry: PARCEL });
});
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

const upload = (name: string, text: string) => {
  const file = new File([text], name);
  fireEvent.change(screen.getByLabelText('Subir fichero'), { target: { files: [file] } });
};

describe('ManualZoningScreen', () => {
  it('asks for a parcel when none is chosen', () => {
    render(<ManualZoningScreen parcelId={null} parcelGeometry={null} />);
    expect(screen.getByText('Elige una parcela en la pestaña Trabajo.')).toBeTruthy();
    expect(api.listZonings).not.toHaveBeenCalled();
  });

  it('loads the parcel geometry for the map when only the id is known (deep link)', async () => {
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={null} />);
    await waitFor(() => expect(api.getParcelGeometry).toHaveBeenCalledWith('p1'));
    await waitFor(() => expect(map().model.parcel).toEqual(PARCEL));
  });

  it('uploads a file, previews accepted and rejected items, saves with edited labels', async () => {
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    upload('zonas.kml', '<kml/>');
    await waitFor(() => expect(api.previewManualZoning).toHaveBeenCalledWith('p1', 'kml', btoa('<kml/>')));
    expect(await screen.findAllByTestId('zoning-preview-row')).toHaveLength(2);
    expect(screen.getByTestId('zoning-rejected').textContent).toContain('Elemento 1: no es un polígono');
    expect(api.saveManualZoning).not.toHaveBeenCalled();
    fireEvent.change(screen.getByLabelText('Nombre de la zona 2'), { target: { value: 'Control' } });
    fireEvent.click(screen.getByRole('button', { name: 'Guardar zonificación' }));
    await waitFor(() => expect(api.saveManualZoning).toHaveBeenCalledWith(
      'p1', 'kml', btoa('<kml/>'), { 1: 'T1', 2: 'Control' }));
    expect(await screen.findByText('Zonificación guardada (2 zonas).')).toBeTruthy();
    expect(api.listZonings).toHaveBeenCalledTimes(2);
    expect(screen.queryAllByTestId('zoning-preview-row')).toHaveLength(0);
  });

  it('maps file extensions to formats', async () => {
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    for (const [name, fmt] of [['a.kmz', 'kmz'], ['a.zip', 'shapefile'], ['a.xml', 'isoxml'], ['a.geojson', 'geojson'], ['a.json', 'geojson']]) {
      upload(name, 'x');
      await waitFor(() => expect((api.previewManualZoning as any).mock.calls.at(-1)[1]).toBe(fmt));
    }
  });

  it('draws polygons on the map and previews them as a FeatureCollection', async () => {
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    expect(map().drawMode).toBe('none');
    fireEvent.click(screen.getByRole('button', { name: 'Dibujar zonas' }));
    expect(map().drawMode).toBe('zone');
    act(() => { map().onZoneDrawn(poly(0)); map().onZoneDrawn(poly(2)); });
    expect(screen.getByText('2 zonas dibujadas')).toBeTruthy();
    expect(map().model.zones).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Revisar zonas dibujadas' }));
    await waitFor(() => expect(api.previewManualZoning).toHaveBeenCalled());
    const [pid, fmt, content] = (api.previewManualZoning as any).mock.calls[0];
    expect([pid, fmt]).toEqual(['p1', 'drawn']);
    const fc = JSON.parse(content);
    expect(fc.type).toBe('FeatureCollection');
    expect(fc.features.map((f: any) => f.geometry)).toEqual([poly(0), poly(2)]);
  });

  it('shows a coded error translated', async () => {
    (api.previewManualZoning as any).mockRejectedValue(
      new ApiError(400, { code: 'ZONES_FILE_INVALID', detail: 'bad', params: {} }));
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    upload('zonas.kml', '<kml/>');
    expect((await screen.findByRole('alert')).textContent).toBeTruthy();
    expect(screen.getByRole('alert').textContent).not.toContain('ZONES_FILE_INVALID');
  });

  it('lists only manual zonings and deletes one after confirmation', async () => {
    (api.listZonings as any).mockResolvedValue({ zonings: [
      { run_id: MANUAL, method: 'manual', date: '2026-06-01T10:00:00+00:00', zone_count: 2, labels: ['T1', 'T2'], is_default: false },
      { run_id: 'veg-1', method: 'vegetationIndex', date: '2026-05-01T00:00:00Z', zone_count: 4, labels: [], is_default: true },
    ] });
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    expect(await screen.findAllByTestId('zoning-saved-row')).toHaveLength(1);
    fireEvent.click(screen.getByRole('button', { name: 'Borrar la zonificación T1, T2' }));
    await waitFor(() => expect(api.deleteZoning).toHaveBeenCalledWith('p1', MANUAL));
    await waitFor(() => expect(api.listZonings).toHaveBeenCalledTimes(2));
  });

  it('does not delete when the confirmation is cancelled', async () => {
    (api.listZonings as any).mockResolvedValue({ zonings: [
      { run_id: MANUAL, method: 'manual', date: null, zone_count: 1, labels: [null], is_default: false },
    ] });
    vi.spyOn(window, 'confirm').mockReturnValue(false);
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    fireEvent.click(await screen.findByRole('button', { name: `Borrar la zonificación ${MANUAL}` }));
    expect(api.deleteZoning).not.toHaveBeenCalled();
  });
});

describe('ManualZoningScreen drawing after a review', () => {
  it('a new drawing discards the review, so nothing drawn is lost on save', async () => {
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    fireEvent.click(screen.getByRole('button', { name: 'Dibujar zonas' }));
    act(() => { map().onZoneDrawn(poly(0)); });
    fireEvent.click(screen.getByRole('button', { name: 'Revisar zonas dibujadas' }));
    expect(await screen.findAllByTestId('zoning-preview-row')).toHaveLength(2);
    fireEvent.click(screen.getByRole('button', { name: 'Dibujar zonas' }));
    act(() => { map().onZoneDrawn(poly(2)); });
    expect(screen.queryAllByTestId('zoning-preview-row')).toHaveLength(0);
    expect(screen.queryByRole('button', { name: 'Guardar zonificación' })).toBeNull();
    expect(screen.getByText('2 zonas dibujadas')).toBeTruthy();
  });

  it('rejected items left out by the reader are shown by name', async () => {
    (api.previewManualZoning as any).mockResolvedValue({
      zones: [], rejected: [{ index: null, name: 'fence', reason: 'not_polygon' }], warnings: [],
    });
    render(<ManualZoningScreen parcelId="p1" parcelGeometry={PARCEL} />);
    upload('zonas.kml', '<kml/>');
    expect((await screen.findByTestId('zoning-rejected')).textContent).toContain('fence: no es un polígono');
  });
});
