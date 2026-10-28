import type { LayerSpecification } from 'maplibre-gl';
import type { Plan } from '../services/api';
import { bboxOf, type Zone } from '../services/geo';

export interface MapModel {
  parcel: GeoJSON.Polygon | null;
  zones: Zone[];
  /** w/2 when a working width is set; null otherwise. */
  marginM: number | null;
  accessPoint: GeoJSON.Point | null;
  accessIssue: 'outside' | 'in_zone' | null;
  plan: Plan | null;
  stale: boolean;
  hoveredSwath: number | null;
  selectedWarning: number | null;
}

export const SOURCE_IDS = ['parcel', 'parcel-rings', 'zones', 'zones-margin', 'swaths', 'route', 'access', 'markers', 'warnings'] as const;
export type SourceId = (typeof SOURCE_IDS)[number];

// The map is not DOM: design tokens do not apply, so colours are constants.
const C = {
  work: '#F59E0B',
  headland: '#6B7280',
  zone: '#EF4444',
  zoneInvalid: '#FBBF24',
  route: '#111827',
  access: '#2563EB',
  ret: '#7C3AED',
  warning: '#FBBF24',
  parcel: '#10B981',
} as const;

type Feature = GeoJSON.Feature;
const feature = (geometry: GeoJSON.Geometry, properties: GeoJSON.GeoJsonProperties): Feature => ({ type: 'Feature', geometry, properties });
const fc = (features: Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });

export function buildSources(m: MapModel): Record<SourceId, GeoJSON.FeatureCollection> {
  const plan = m.plan;

  const rings = m.parcel
    ? m.parcel.coordinates.slice(1).map((ring) => feature({ type: 'Polygon', coordinates: [ring] }, {}))
    : [];

  const margin = m.marginM === null
    ? []
    : m.zones.filter((z) => z.valid).map((z) => feature(z.polygon, { marginM: m.marginM }));

  const access: Feature[] = [];
  if (plan?.access_path) access.push(feature(plan.access_path, { kind: 'access' }));
  if (plan?.return_path) access.push(feature(plan.return_path, { kind: 'return' }));

  const markers: Feature[] = [];
  const accessPoint = plan?.access_point ?? m.accessPoint;
  if (accessPoint) markers.push(feature(accessPoint, { kind: 'access', issue: m.accessIssue }));
  if (plan) markers.push(feature(plan.exit_point, { kind: 'exit' }));

  // Numbering counts every warning so it matches the list in the result strip.
  const warnings: Feature[] = [];
  (plan?.validation?.warnings ?? []).forEach((w, i) => {
    if (w.geometry) warnings.push(feature(w.geometry, { n: i + 1, code: w.code, selected: m.selectedWarning === i + 1 }));
  });

  return {
    parcel: fc(m.parcel ? [feature(m.parcel, {})] : []),
    'parcel-rings': fc(rings),
    zones: fc(m.zones.map((z) => feature(z.polygon, { id: z.id, valid: z.valid, areaHa: z.areaHa }))),
    'zones-margin': fc(margin),
    swaths: fc((plan?.swaths ?? []).map((s) => feature(s.geometry, { index: s.index, kind: s.kind, hovered: m.hoveredSwath === s.index }))),
    route: fc(plan ? [feature(plan.route, { stale: m.stale })] : []),
    access: fc(access),
    markers: fc(markers),
    warnings: fc(warnings),
  };
}

export function layerSpecs(): LayerSpecification[] {
  return [
    { id: 'parcel-fill', type: 'fill', source: 'parcel', paint: { 'fill-color': C.parcel, 'fill-opacity': 0.08 } },
    { id: 'parcel-line', type: 'line', source: 'parcel', paint: { 'line-color': C.parcel, 'line-width': 2 } },
    { id: 'rings-fill', type: 'fill', source: 'parcel-rings', paint: { 'fill-color': C.headland, 'fill-opacity': 0.25 } },
    { id: 'rings-line', type: 'line', source: 'parcel-rings', paint: { 'line-color': C.headland, 'line-width': 1.5, 'line-dasharray': [3, 2] } },
    { id: 'zones-fill', type: 'fill', source: 'zones', paint: { 'fill-color': C.zone, 'fill-opacity': 0.3 } },
    {
      id: 'zones-line', type: 'line', source: 'zones',
      paint: {
        'line-color': ['case', ['!', ['get', 'valid']], C.zoneInvalid, C.zone],
        'line-width': 2,
        'line-dasharray': [2, 2],
      },
    },
    { id: 'zones-margin-line', type: 'line', source: 'zones-margin', paint: { 'line-color': C.zone, 'line-width': 1.5, 'line-dasharray': [2, 2], 'line-opacity': 0.7 } },
    {
      id: 'swaths-line', type: 'line', source: 'swaths',
      paint: {
        'line-color': ['match', ['get', 'kind'], 'headland', C.headland, C.work],
        'line-width': ['case', ['get', 'hovered'], 5, 3],
      },
    },
    {
      id: 'route-line', type: 'line', source: 'route',
      paint: { 'line-color': C.route, 'line-width': 1.5, 'line-opacity': ['case', ['get', 'stale'], 0.4, 0.9] },
    },
    {
      id: 'access-line', type: 'line', source: 'access',
      paint: {
        'line-color': ['match', ['get', 'kind'], 'return', C.ret, C.access],
        'line-width': 2,
        'line-dasharray': [1, 2],
      },
    },
    {
      id: 'markers-issue', type: 'circle', source: 'markers', filter: ['!=', ['get', 'issue'], null],
      paint: { 'circle-radius': 11, 'circle-color': 'rgba(0,0,0,0)', 'circle-stroke-color': C.zone, 'circle-stroke-width': 3 },
    },
    {
      id: 'markers-circle', type: 'circle', source: 'markers',
      paint: {
        'circle-radius': 7,
        'circle-color': ['match', ['get', 'kind'], 'access', C.access, C.route],
        'circle-stroke-color': '#FFFFFF',
        'circle-stroke-width': 2,
      },
    },
    {
      id: 'warnings-circle', type: 'circle', source: 'warnings',
      paint: {
        'circle-radius': ['case', ['get', 'selected'], 13, 10],
        'circle-color': C.warning,
        'circle-stroke-color': C.route,
        'circle-stroke-width': ['case', ['get', 'selected'], 3, 1],
      },
    },
    {
      id: 'warnings-label', type: 'symbol', source: 'warnings',
      layout: { 'text-field': ['to-string', ['get', 'n']], 'text-size': 12, 'text-allow-overlap': true },
      paint: { 'text-color': C.route },
    },
  ];
}

export function planBounds(m: MapModel): [number, number, number, number] | null {
  if (m.parcel) return bboxOf(m.parcel);
  if (m.plan) return bboxOf(m.plan.route);
  return null;
}
