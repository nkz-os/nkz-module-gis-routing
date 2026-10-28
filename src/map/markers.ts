/**
 * Shared visual language for the gate and the NO-GO zones on every map (MapLibre and Cesium):
 * the gate icon (own SVG), the red diagonal hatch and the legend swatches.
 */

import pointOnFeature from '@turf/point-on-feature';

export const GATE_IMAGE = 'nkz-gate';
export const HATCH_IMAGE = 'nkz-nogo-hatch';
export const NOGO_COLOR = '#DC2626';
export const GATE_COLOR = '#2563EB';

const SVG_NS = 'http://www.w3.org/2000/svg'; // hygiene:allow XML namespace, not a network call

/** Gate: round blue badge, two posts, two rails and a brace. */
export function gateSvg(): string {
  return `<svg xmlns="${SVG_NS}" width="64" height="64" viewBox="0 0 64 64">`
    + `<circle cx="32" cy="32" r="29" fill="${GATE_COLOR}" stroke="#FFFFFF" stroke-width="4"/>`
    + '<g stroke="#FFFFFF" stroke-linecap="round" fill="none">'
    + '<path d="M17 47V19M47 47V19" stroke-width="5"/>'
    + '<path d="M17 26H47M17 40H47M17 26L47 40" stroke-width="3.5"/>'
    + '</g></svg>';
}

const toDataUrl = (svg: string) => `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
export const gateDataUrl = (): string => toDataUrl(gateSvg());

/** Legend swatch of the hatched NO-GO fill with its thick red border. */
export function nogoSwatchDataUrl(): string {
  return toDataUrl(
    `<svg xmlns="${SVG_NS}" width="24" height="16" viewBox="0 0 24 16">`
    + `<rect x="1.5" y="1.5" width="21" height="13" fill="${NOGO_COLOR}" fill-opacity="0.2"/>`
    + `<g stroke="${NOGO_COLOR}" stroke-width="2"><path d="M-2 18L18 -2M4 18L24 -2M10 18L30 -2"/></g>`
    + `<rect x="1.5" y="1.5" width="21" height="13" fill="none" stroke="${NOGO_COLOR}" stroke-width="3"/></svg>`,
  );
}

/** Legend swatch of the dashed safety margin. */
export function marginSwatchDataUrl(): string {
  return toDataUrl(
    `<svg xmlns="${SVG_NS}" width="24" height="16" viewBox="0 0 24 16">`
    + `<rect x="1.5" y="1.5" width="21" height="13" fill="none" stroke="${NOGO_COLOR}" stroke-width="2" stroke-dasharray="4 3"/></svg>`,
  );
}

export interface PixelImage { width: number; height: number; data: Uint8Array }

/**
 * Diagonal red stripes on transparent, built without a canvas (jsdom has none).
 * The period divides the size, so the tile repeats seamlessly.
 */
export function hatchPixels(size = 16): PixelImage {
  const period = 8;
  const stripe = 3;
  const data = new Uint8Array(size * size * 4);
  for (let y = 0; y < size; y++) {
    for (let x = 0; x < size; x++) {
      if ((x + y) % period < stripe) {
        const i = (y * size + x) * 4;
        data[i] = 220; data[i + 1] = 38; data[i + 2] = 38; data[i + 3] = 235;
      }
    }
  }
  return { width: size, height: size, data };
}

interface ImageMap {
  hasImage(id: string): boolean;
  addImage(id: string, image: unknown, options?: { pixelRatio?: number }): void;
}

export function loadGateImage(): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image(64, 64);
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error('gate icon failed to load'));
    img.src = gateDataUrl();
  });
}

const gateLoading = new WeakSet<object>();

/**
 * Registers the hatch and the gate icon on a map. Idempotent: safe to call at load, on
 * `styledata` and on `styleimagemissing` (a style reload drops images).
 */
export async function ensureMapImages(map: ImageMap, loadGate: () => Promise<unknown> = loadGateImage): Promise<void> {
  if (!map.hasImage(HATCH_IMAGE)) map.addImage(HATCH_IMAGE, hatchPixels(16), { pixelRatio: 2 });
  if (map.hasImage(GATE_IMAGE) || gateLoading.has(map)) return;
  gateLoading.add(map);
  try {
    const img = await loadGate();
    if (!map.hasImage(GATE_IMAGE)) map.addImage(GATE_IMAGE, img, { pixelRatio: 2 });
  } catch (e) {
    console.warn('[gis-routing] gate icon not available', e);
  } finally {
    gateLoading.delete(map);
  }
}

/**
 * Where a label sits: the point itself, a line's middle, or a point guaranteed to lie on the
 * first polygon part (a concave zone's bounding-box centre can fall outside it).
 */
export function labelAnchor(g: GeoJSON.Geometry): [number, number] {
  if (g.type === 'Point') return [g.coordinates[0], g.coordinates[1]];
  if (g.type === 'LineString' || g.type === 'MultiLineString') {
    const line = g.type === 'LineString' ? g.coordinates : g.coordinates[0];
    const p = line[Math.floor(line.length / 2)];
    return [p[0], p[1]];
  }
  if (g.type === 'GeometryCollection') {
    const first = g.geometries.find((x) => x.type === 'Polygon' || x.type === 'MultiPolygon');
    return first ? labelAnchor(first) : [0, 0];
  }
  const rings = g.type === 'MultiPolygon' ? g.coordinates[0] : g.type === 'Polygon' ? g.coordinates : undefined;
  if (!rings || !rings[0] || rings[0].length === 0) return [0, 0];
  try {
    const p = pointOnFeature({ type: 'Polygon', coordinates: rings }).geometry.coordinates;
    return [p[0], p[1]];
  } catch {
    return [rings[0][0][0], rings[0][0][1]];
  }
}
