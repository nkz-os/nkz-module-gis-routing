import React from 'react';
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ opts: null as any, fitBounds: vi.fn(), setMode: vi.fn(), handlers: {} as Record<string, (...a: any[]) => void>, images: [] as string[], markers: [] as any[] }));

// The worker Blob is covered by loadMapLibre.test; here MapLibre is the plain mock.
vi.mock('../loadMapLibre', () => ({ loadMapLibre: () => import('maplibre-gl') }));
vi.mock('maplibre-gl', () => {
  class Map {
    constructor(o: any) { h.opts = o; }
    addControl() {}
    on(ev: string, cb: (...a: any[]) => void) { if (typeof cb === 'function' && (ev === 'load' || ev === 'error')) h.handlers[ev] = cb; }
    addSource() {}
    hasImage(n: string) { return h.images.includes(n); }
    addImage(n: string) { h.images.push(n); }
    addLayer() {}
    getSource() { return undefined; }
    getLayer() { return undefined; }
    fitBounds(...a: unknown[]) { h.fitBounds(...a); }
    resize() {}
    remove() {}
    getCanvas() { return { style: {} }; }
  }
  class Marker {
    constructor(public o: any) { h.markers.push(this); }
    setLngLat() { return this; } addTo() { return this; } remove() {} getElement() { return this.o.element; }
  }
  const C = class {};
  return { default: { Map, Marker, NavigationControl: C, ScaleControl: C }, Map, Marker, NavigationControl: C, ScaleControl: C };
});
vi.mock('terra-draw', () => {
  class M { constructor(public o?: unknown) {} }
  class TerraDraw {
    start() {} stop() {} setMode(m: string) { h.setMode(m); } on() {} clear() {} addFeatures() {} removeFeatures() {} getSnapshotFeature() { return null; }
  }
  // Mirrors terra-draw: the render mode has no default name and throws without one.
  class R { constructor(o?: { modeName?: string }) { if (!o?.modeName) throw new Error('Mode name is required for TerraDrawRenderMode'); } }
  return { TerraDraw, TerraDrawPolygonMode: M, TerraDrawPointMode: M, TerraDrawSelectMode: M, TerraDrawRenderMode: R };
});
vi.mock('terra-draw-maplibre-gl-adapter', () => ({ TerraDrawMapLibreGLAdapter: class {} }));

import '../../i18n';
import { MapCanvas } from '../MapCanvas';
import type { MapModel } from '../model';

const ring = [[0, 0], [0.01, 0], [0.01, 0.01], [0, 0.01], [0, 0]];
const model = {
  parcel: { type: 'Polygon', coordinates: [ring] },
  zones: [], accessPoint: null, result: null, hoveredSwath: null, selectedWarning: null, focus: null,
} as unknown as MapModel;

const props = {
  model, drawMode: 'none' as const, fitKey: null,
  onZoneDrawn: vi.fn(), onZoneEdited: vi.fn(), onAccessPlaced: vi.fn(), onSwathHover: vi.fn(), onWarningClick: vi.fn(),
};

afterEach(() => { cleanup(); h.opts = null; h.fitBounds.mockClear(); h.setMode.mockClear(); h.handlers = {}; h.images = []; h.markers = []; });

describe('MapCanvas', () => {
  it('hands MapLibre an inner box, not the absolutely positioned wrapper', async () => {
    const { getByTestId } = render(<MapCanvas {...props} />);
    await waitFor(() => expect(h.opts).not.toBeNull());
    const outer = getByTestId('map-canvas');
    expect(outer.className).toContain('absolute');
    expect(h.opts.container).toBe(getByTestId('map-container'));
    expect(h.opts.container).not.toBe(outer);
    expect(h.opts.container.className).not.toContain('absolute');
    expect(h.opts.container.className).toContain('h-full');
    expect(outer.contains(h.opts.container)).toBe(true);
  });

  it('adds bottomInset to the fitBounds bottom padding', async () => {
    render(<MapCanvas {...props} bottomInset={120} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    expect(h.fitBounds).toHaveBeenCalled();
    expect(h.fitBounds.mock.calls[0][1].padding).toEqual({ top: 40, left: 40, right: 40, bottom: 160 });
  });

  it('treats tile/source errors as non-fatal and other map errors as fatal', async () => {
    const onError = vi.fn();
    vi.spyOn(console, 'warn').mockImplementation(() => {});
    vi.spyOn(console, 'error').mockImplementation(() => {});
    render(<MapCanvas {...props} onError={onError} />);
    await waitFor(() => expect(h.handlers.error).toBeTypeOf('function'));
    h.handlers.error({ error: new Error('tile 503'), sourceId: 'basemap', tile: {} });
    expect(onError).not.toHaveBeenCalled();
    h.handlers.error({ error: new Error('style failed') });
    expect(onError).toHaveBeenCalledTimes(1);
  });

  it('switches terra-draw to a non-interactive mode while locked', async () => {
    const { rerender } = render(<MapCanvas {...props} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    await waitFor(() => expect(h.setMode).toHaveBeenCalledWith('select'));
    h.setMode.mockClear();
    rerender(<MapCanvas {...props} locked />);
    await waitFor(() => expect(h.setMode).toHaveBeenCalledWith('render'));
    h.setMode.mockClear();
    rerender(<MapCanvas {...props} locked={false} />);
    await waitFor(() => expect(h.setMode).toHaveBeenCalledWith('select'));
  });

  it('registers the hatch before the layers and labels the gate and every NO-GO zone', async () => {
    const zone = (id: string, x: number) => ({ id, polygon: { type: 'Polygon', coordinates: [[[x, 0], [x + 0.001, 0], [x + 0.001, 0.001], [x, 0.001], [x, 0]]] }, areaHa: 1, valid: true });
    const m = { ...model, zones: [zone('a', 0), zone('b', 0.005)], accessPoint: { type: 'Point', coordinates: [0.002, 0.002] }, marginM: null } as unknown as MapModel;
    render(<MapCanvas {...props} model={m} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    expect(h.images).toContain('nkz-nogo-hatch');
    await waitFor(() => expect(h.markers).toHaveLength(3));
    expect(h.markers.map((k) => k.o.element.textContent).sort()).toEqual(['NO-GO', 'NO-GO', 'Portón']);
  });

  it('keeps the gate label when the zones group is hidden; only the zone labels go', async () => {
    const zone = { id: 'a', polygon: { type: 'Polygon', coordinates: [[[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]] }, areaHa: 1, valid: true };
    const m = { ...model, zones: [zone], accessPoint: { type: 'Point', coordinates: [0.002, 0.002] }, marginM: null } as unknown as MapModel;
    render(<MapCanvas {...props} model={m} visibleLayers={{ zones: false }} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    await waitFor(() => expect(h.markers).toHaveLength(1));
    expect(h.markers[0].o.element.textContent).toBe('Portón');
  });

  it('puts the legend in the bottom-left corner above the result strip, away from the layers panel', async () => {
    const { getByTestId } = render(<MapCanvas {...props} bottomInset={120} />);
    const legend = getByTestId('map-legend');
    expect(legend.className).not.toMatch(/\btop-2\b/);
    expect(legend.style.bottom).toBe('128px');
  });

  it('shows a legend', async () => {
    const { getByTestId } = render(<MapCanvas {...props} />);
    expect(getByTestId('map-legend')).toBeInTheDocument();
  });
});
