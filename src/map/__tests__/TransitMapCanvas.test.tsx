import React from 'react';
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ fit: vi.fn(), handlers: {} as Record<string, (...a: any[]) => void>, markers: [] as any[], images: [] as string[], sources: {} as Record<string, any> }));

vi.mock('maplibre-gl', () => {
  class Map {
    constructor(public o: any) {}
    addControl() {}
    on(ev: string, cb: (...a: any[]) => void) { h.handlers[ev] = cb; }
    addSource(id: string) { h.sources[id] = { setData: vi.fn() }; }
    addLayer() {}
    hasImage(n: string) { return h.images.includes(n); }
    addImage(n: string) { h.images.push(n); }
    getSource(id: string) { return h.sources[id]; }
    fitBounds(...a: unknown[]) {
      // Like MapLibre: padding larger than the canvas throws.
      const el = this.o.container as HTMLElement;
      if (el.clientWidth < 121 || el.clientHeight < 121) throw new Error('Map cannot fit within canvas with the given bounds, padding, and/or offset.');
      h.fit(...a);
    }
    getBounds() { return { getWest: () => 0, getSouth: () => 0, getEast: () => 0.05, getNorth: () => 0.05 }; }
    getZoom() { return 14; }
    getCanvas() { return { style: {} }; }
    resize() {}
    remove() {}
  }
  class Marker {
    el: HTMLElement; ll: [number, number] = [0, 0]; handlers: Record<string, () => void> = {};
    constructor(o: any) { this.el = o.element; h.markers.push(this); }
    setLngLat(ll: [number, number]) { this.ll = ll; return this; }
    addTo() { return this; }
    on(ev: string, cb: () => void) { this.handlers[ev] = cb; return this; }
    getLngLat() { return { lng: this.ll[0], lat: this.ll[1] }; }
    getElement() { return this.el; }
    setDraggable() {}
    remove() {}
  }
  const C = class {};
  return { default: { Map, Marker, NavigationControl: C, ScaleControl: C }, Map, Marker, NavigationControl: C, ScaleControl: C };
});

import '../../i18n';
import { TransitMapCanvas } from '../TransitMapCanvas';
import type { TransitMapModel } from '../transitModel';

const model: TransitMapModel = { a: [0, 0], b: [0.01, 0.01], badPoint: null, focus: null, alternatives: [], selected: null, stale: false, hover: null, context: [] };
const base = { model, pick: null, fitKey: null, onPick: vi.fn(), onMarkerMoved: vi.fn(), onViewChange: vi.fn() };

afterEach(() => { vi.unstubAllGlobals(); cleanup(); h.fit.mockClear(); h.handlers = {}; h.markers = []; h.images = []; h.sources = {}; vi.clearAllMocks(); });

describe('TransitMapCanvas', () => {
  it('places the picked point on click only while picking', async () => {
    const onPick = vi.fn();
    const { rerender } = render(<TransitMapCanvas {...base} onPick={onPick} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    h.handlers.click({ lngLat: { lng: 1, lat: 2 } });
    expect(onPick).not.toHaveBeenCalled();
    rerender(<TransitMapCanvas {...base} onPick={onPick} pick="b" />);
    h.handlers.click({ lngLat: { lng: 1, lat: 2 } });
    expect(onPick).toHaveBeenCalledWith('b', [1, 2]);
  });

  it('reports the view on load and draws draggable A/B markers', async () => {
    const onMarkerMoved = vi.fn();
    render(<TransitMapCanvas {...base} onMarkerMoved={onMarkerMoved} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    expect(base.onViewChange).toHaveBeenCalledWith({ bbox: [0, 0, 0.05, 0.05], zoom: 14 });
    await waitFor(() => expect(h.markers).toHaveLength(2));
    h.markers[0].ll = [3, 4];
    h.markers[0].handlers.dragend();
    expect(onMarkerMoved).toHaveBeenCalledWith('a', [3, 4]);
  });
});

describe('TransitMapCanvas in a hidden container', () => {
  const size = (el: HTMLElement, w: number, h2: number) => {
    Object.defineProperty(el, 'clientWidth', { configurable: true, value: w });
    Object.defineProperty(el, 'clientHeight', { configurable: true, value: h2 });
  };

  it('does not throw on load or fitKey change while 0x0, and fits once it gets a size', async () => {
    let roCallback: () => void = () => {};
    vi.stubGlobal('ResizeObserver', class { constructor(cb: () => void) { roCallback = cb; } observe() {} disconnect() {} });
    const onError = vi.fn();
    const { getByTestId, rerender } = render(<TransitMapCanvas {...base} onError={onError} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    rerender(<TransitMapCanvas {...base} onError={onError} fitKey="1" />);
    expect(onError).not.toHaveBeenCalled();
    expect(h.fit).not.toHaveBeenCalled();
    size(getByTestId('transit-map-container'), 800, 600);
    roCallback();
    expect(h.fit).toHaveBeenCalledTimes(1);
    roCallback();
    expect(h.fit).toHaveBeenCalledTimes(1);
  });

  it('ignores a map click that lands on a marker', async () => {
    const onPick = vi.fn();
    render(<TransitMapCanvas {...base} onPick={onPick} pick="a" />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    await waitFor(() => expect(h.markers).toHaveLength(2));
    h.handlers.click({ lngLat: { lng: 1, lat: 2 }, originalEvent: { target: h.markers[0].el } });
    expect(onPick).not.toHaveBeenCalled();
    expect(h.markers[0].el.getAttribute('aria-label')).toBe('A');
  });
});

describe('TransitMapCanvas gates and zones', () => {
  it('registers the hatch and labels each gate and NO-GO zone, with a legend', async () => {
    const poly = { type: 'Polygon', coordinates: [[[0, 0], [0.001, 0], [0.001, 0.001], [0, 0.001], [0, 0]]] } as GeoJSON.Polygon;
    const context = [{ id: 'p1', name: 'P', geometry: poly, access_point: { type: 'Point', coordinates: [0.0005, 0] }, zones: [poly] }] as any;
    const { getByTestId } = render(<TransitMapCanvas {...base} model={{ ...model, a: null, b: null, context }} />);
    await waitFor(() => expect(h.handlers.load).toBeTypeOf('function'));
    h.handlers.load();
    expect(h.images).toContain('nkz-nogo-hatch');
    await waitFor(() => expect(h.markers).toHaveLength(2));
    expect(h.markers.map((k) => k.el.textContent).sort()).toEqual(['NO-GO', 'Portón']);
    expect(getByTestId('map-legend')).toBeInTheDocument();
  });
});
