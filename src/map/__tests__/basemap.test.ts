import { describe, expect, it } from 'vitest';
import { basemapFor, rasterSource } from '../basemap';
describe('basemap', () => {
  it('uses PNOA inside Spain and Esri elsewhere', () => {
    expect(basemapFor(-1.65, 42.8)).toBe('pnoa'); expect(basemapFor(-3.7, 40.4)).toBe('pnoa');
    expect(basemapFor(2.35, 48.85)).toBe('esri'); expect(basemapFor(-74, 40.7)).toBe('esri');
  });
  it('raster sources carry attribution and a {z}/{x}/{y} template', () => {
    for (const id of ['pnoa', 'esri'] as const) {
      const s = rasterSource(id);
      expect(s.tiles[0]).toMatch(/\{z\}/); expect(s.attribution.length).toBeGreaterThan(3); expect(s.maxzoom).toBe(19);
    }
    expect(rasterSource('pnoa').tiles[0]).toContain('TILEMATRIXSET=GoogleMapsCompatible');
  });
});
