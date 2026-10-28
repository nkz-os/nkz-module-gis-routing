import React from 'react';
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ handlers: {} as Record<string, (...a: any[]) => void>, markers: [] as any[], sources: {} as Record<string, any> }));

vi.mock('maplibre-gl', () => {
  class Map {
    constructor(public o: any) {}
    addControl() {}
    on(ev: string, cb: (...a: any[]) => void) { h.handlers[ev] = cb; }
    addSource(id: string) { h.sources[id] = { setData: vi.fn() }; }
    addLayer() {}
    getSource(id: string) { return h.sources[id]; }
    fitBounds() {}
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

import { TransitMapCanvas } from '../TransitMapCanvas';
import type { TransitMapModel } from '../transitModel';

const model: TransitMapModel = { a: [0, 0], b: [0.01, 0.01], badPoint: null, focus: null, alternatives: [], selected: null, stale: false, hover: null, context: [] };
const base = { model, pick: null, fitKey: null, onPick: vi.fn(), onMarkerMoved: vi.fn(), onViewChange: vi.fn() };

afterEach(() => { cleanup(); h.handlers = {}; h.markers = []; h.sources = {}; vi.clearAllMocks(); });

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
