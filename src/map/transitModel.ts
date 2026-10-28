import type { LayerSpecification } from 'maplibre-gl';
import type { ContextParcel, PathAlternative, PathAlternativeId } from '../services/api';
import type { LonLat } from '../state/transitMachine';
import { GATE_IMAGE, HATCH_IMAGE, NOGO_COLOR } from './markers';

export interface TransitMapModel {
  a: LonLat | null;
  b: LonLat | null;
  /** Point the last job rejected (in a no-go zone or on a fence): drawn red. */
  badPoint: 'A' | 'B' | null;
  /** Geometry the backend reported with the error. */
  focus: GeoJSON.Geometry | null;
  alternatives: PathAlternative[];
  selected: PathAlternativeId | null;
  stale: boolean;
  /** Profile hover position. */
  hover: LonLat | null;
  context: ContextParcel[];
}

export const TRANSIT_SOURCE_IDS = ['tr-parcels', 'tr-gates', 'tr-zones', 'tr-alts', 'tr-focus', 'tr-hover'] as const;
export type TransitSourceId = (typeof TRANSIT_SOURCE_IDS)[number];

// The map is not DOM: design tokens do not apply, so colours are constants.
export const TRANSIT_COLORS = {
  parcel: '#10B981',
  gate: '#2563EB',
  zone: NOGO_COLOR,
  selected: '#2563EB',
  other: '#9CA3AF',
  hover: '#F59E0B',
  a: '#16A34A',
  b: '#7C3AED',
  bad: '#DC2626',
} as const;

const feature = (geometry: GeoJSON.Geometry, properties: GeoJSON.GeoJsonProperties = {}): GeoJSON.Feature => ({ type: 'Feature', geometry, properties });
const fc = (features: GeoJSON.Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });

export function buildTransitSources(m: TransitMapModel): Record<TransitSourceId, GeoJSON.FeatureCollection> {
  return {
    'tr-parcels': fc(m.context.map((p) => feature(p.geometry, { id: p.id, name: p.name, gated: p.access_point !== null }))),
    'tr-gates': fc(m.context.filter((p) => p.access_point).map((p) => feature(p.access_point as GeoJSON.Point, { id: p.id }))),
    'tr-zones': fc(m.context.flatMap((p) => p.zones.map((z) => feature(z, { parcel: p.id })))),
    // Unselected first so the chosen alternative is drawn on top.
    'tr-alts': fc([...m.alternatives]
      .sort((x, y) => Number(x.id === m.selected) - Number(y.id === m.selected))
      .map((a) => feature(a.geometry, { id: a.id, selected: a.id === m.selected, stale: m.stale }))),
    'tr-focus': fc(m.focus ? [feature(m.focus)] : []),
    'tr-hover': fc(m.hover ? [feature({ type: 'Point', coordinates: m.hover })] : []),
  };
}

export function changedTransitSources(prev: TransitMapModel | null, next: TransitMapModel): TransitSourceId[] {
  if (prev === null) return [...TRANSIT_SOURCE_IDS];
  const out: TransitSourceId[] = [];
  if (prev.context !== next.context) out.push('tr-parcels', 'tr-gates', 'tr-zones');
  if (prev.alternatives !== next.alternatives || prev.selected !== next.selected || prev.stale !== next.stale) out.push('tr-alts');
  if (prev.focus !== next.focus) out.push('tr-focus');
  if (prev.hover !== next.hover) out.push('tr-hover');
  return out;
}

export function transitLayerSpecs(): LayerSpecification[] {
  const C = TRANSIT_COLORS;
  return [
    { id: 'tr-parcels-fill', type: 'fill', source: 'tr-parcels', paint: { 'fill-color': C.parcel, 'fill-opacity': 0.06 } },
    {
      id: 'tr-parcels-line', type: 'line', source: 'tr-parcels',
      paint: { 'line-color': C.parcel, 'line-width': 1.5, 'line-dasharray': [3, 2] },
    },
    { id: 'tr-zones-fill', type: 'fill', source: 'tr-zones', paint: { 'fill-color': C.zone, 'fill-opacity': 0.18 } },
    { id: 'tr-zones-hatch', type: 'fill', source: 'tr-zones', paint: { 'fill-pattern': HATCH_IMAGE } },
    { id: 'tr-zones-line', type: 'line', source: 'tr-zones', paint: { 'line-color': C.zone, 'line-width': 3 } },
    {
      id: 'tr-gates-icon', type: 'symbol', source: 'tr-gates',
      layout: { 'icon-image': GATE_IMAGE, 'icon-anchor': 'bottom', 'icon-allow-overlap': true, 'icon-ignore-placement': true },
    },
    {
      id: 'tr-alts-casing', type: 'line', source: 'tr-alts', filter: ['==', ['get', 'selected'], true],
      paint: { 'line-color': '#FFFFFF', 'line-width': 8, 'line-opacity': ['case', ['get', 'stale'], 0.4, 0.9] },
    },
    {
      id: 'tr-alts-line', type: 'line', source: 'tr-alts',
      layout: { 'line-cap': 'round', 'line-join': 'round' },
      paint: {
        'line-color': ['case', ['get', 'selected'], C.selected, C.other],
        'line-width': ['case', ['get', 'selected'], 5, 3],
        'line-opacity': ['case', ['get', 'stale'], 0.4, ['get', 'selected'], 1, 0.7],
      },
    },
    { id: 'tr-focus-fill', type: 'fill', source: 'tr-focus', filter: ['==', ['geometry-type'], 'Polygon'], paint: { 'fill-color': C.bad, 'fill-opacity': 0.3 } },
    { id: 'tr-focus-line', type: 'line', source: 'tr-focus', filter: ['!=', ['geometry-type'], 'Point'], paint: { 'line-color': C.bad, 'line-width': 3 } },
    {
      id: 'tr-focus-point', type: 'circle', source: 'tr-focus', filter: ['==', ['geometry-type'], 'Point'],
      paint: { 'circle-radius': 14, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': C.bad, 'circle-stroke-width': 3 },
    },
    {
      id: 'tr-hover-circle', type: 'circle', source: 'tr-hover',
      paint: { 'circle-radius': 6, 'circle-color': C.hover, 'circle-stroke-color': '#111827', 'circle-stroke-width': 2 },
    },
  ];
}

/** [minLon, minLat, maxLon, maxLat] enclosing A, B and every alternative. */
export function transitBounds(m: TransitMapModel): [number, number, number, number] | null {
  const pts: number[][] = [];
  if (m.a) pts.push(m.a);
  if (m.b) pts.push(m.b);
  for (const alt of m.alternatives) pts.push(...alt.geometry.coordinates);
  if (pts.length === 0) return null;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of pts) {
    x0 = Math.min(x0, x); x1 = Math.max(x1, x);
    y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  return [x0, y0, x1, y1];
}

/** Context is only fetched when both sides of the view are at most this many degrees (backend cap). */
export const CONTEXT_MAX_SIDE_DEG = 0.2;

export function contextBboxOk(b: [number, number, number, number]): boolean {
  return b[2] - b[0] <= CONTEXT_MAX_SIDE_DEG && b[3] - b[1] <= CONTEXT_MAX_SIDE_DEG && b[2] > b[0] && b[3] > b[1];
}
