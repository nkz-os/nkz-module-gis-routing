import { describe, expect, it, vi } from 'vitest';
vi.mock('maplibre-gl/dist/maplibre-gl.css?inline', () => ({ default: '.maplibregl-map{position:relative}' }));
import { injectMapCss } from '../injectMapCss';

describe('injectMapCss', () => {
  it('adds the stylesheet once with the module marker', () => {
    injectMapCss(document);
    injectMapCss(document);
    const styles = document.querySelectorAll('style[data-nkz-gis-routing="maplibre"]');
    expect(styles).toHaveLength(1);
    expect(styles[0].textContent).toContain('.maplibregl-map');
  });
});
