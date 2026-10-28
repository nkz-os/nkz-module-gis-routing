import React from 'react';
import { cleanup, render, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const h = vi.hoisted(() => ({ opts: null as any, fitBounds: vi.fn(), handlers: {} as Record<string, () => void> }));

vi.mock('maplibre-gl', () => {
  class Map {
    constructor(o: any) { h.opts = o; }
    addControl() {}
    on(ev: string, cb: () => void) { if (typeof cb === 'function' && ev === 'load') h.handlers.load = cb; }
    addSource() {}
    addLayer() {}
    getSource() { return undefined; }
    getLayer() { return undefined; }
    fitBounds(...a: unknown[]) { h.fitBounds(...a); }
    resize() {}
    remove() {}
    getCanvas() { return { style: {} }; }
  }
  const C = class {};
  return { default: { Map, NavigationControl: C, ScaleControl: C }, Map, NavigationControl: C, ScaleControl: C };
});
vi.mock('terra-draw', () => {
  class M { constructor(public o?: unknown) {} }
  class TerraDraw {
    start() {} stop() {} setMode() {} on() {} clear() {} addFeatures() {} removeFeatures() {} getSnapshotFeature() { return null; }
  }
  return { TerraDraw, TerraDrawPolygonMode: M, TerraDrawPointMode: M, TerraDrawSelectMode: M };
});
vi.mock('terra-draw-maplibre-gl-adapter', () => ({ TerraDrawMapLibreGLAdapter: class {} }));

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

afterEach(() => { cleanup(); h.opts = null; h.fitBounds.mockClear(); });

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
});
