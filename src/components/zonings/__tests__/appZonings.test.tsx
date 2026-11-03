import React, { useEffect } from 'react';
import { cleanup, fireEvent, render, screen } from '@testing-library/react';
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';
import App from '../../../App';

const GEOM: GeoJSON.Polygon = { type: 'Polygon', coordinates: [[[0, 0], [1, 0], [1, 1], [0, 0]]] };

vi.mock('../../work/WorkScreen', () => ({
  WorkScreen: (props: any) => {
    useEffect(() => {
      props.onContextChange?.({ parcelId: 'p-work', parcelGeometry: GEOM, machineWidthM: null, turningRadiusM: null });
    }, []); // eslint-disable-line react-hooks/exhaustive-deps
    return <div data-testid="work" />;
  },
}));
vi.mock('../../transit/TransitScreen', () => ({ TransitScreen: () => <div data-testid="transit" /> }));
vi.mock('../ManualZoningScreen', () => ({
  ManualZoningScreen: (props: any) => (
    <div data-testid="zonings">{String(props.parcelId)}|{props.parcelGeometry ? 'geom' : 'nogeom'}</div>
  ),
}));

beforeAll(async () => { await i18n.changeLanguage('es'); });
afterEach(() => { cleanup(); window.history.replaceState({}, '', '/'); });

const tab = (name: string) => fireEvent.mouseDown(screen.getByRole('tab', { name }), { button: 0, ctrlKey: false });

describe('App manual zonings tab', () => {
  it('opens on the work parcel when the tab is chosen', () => {
    render(<App />);
    expect(screen.queryByTestId('zonings')).toBeNull();
    tab('Zonas manuales');
    expect(screen.getByTestId('zonings').textContent).toBe('p-work|geom');
  });

  it('a deep link opens the tab for the given parcel', () => {
    window.history.replaceState({}, '', '/?view=zonings&parcel=urn%3Angsi-ld%3AAgriParcel%3Ademo-parcel-001');
    render(<App />);
    const el = screen.getByTestId('zonings');
    expect(el.textContent).toBe('urn:ngsi-ld:AgriParcel:demo-parcel-001|nogeom');
    expect(el.closest('.hidden')).toBeNull();
  });
});
