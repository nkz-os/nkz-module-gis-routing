import type { LayerSpecification } from 'maplibre-gl';
import type { Plan, Prescription } from '../services/api';
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
  /** Geometry of a failed request (no plan): drawn as a synthetic warning and used for fitting. */
  focus?: GeoJSON.Geometry | null;
  /** Active VRA prescription; classes are drawn and swath segments recoloured. */
  vra?: Prescription | null;
  /** Pre-formatted dose label per rate (unit text comes from i18n in the UI). */
  vraRateLabel?: (rate: number) => string;
}

export const SOURCE_IDS = ['parcel', 'parcel-rings', 'zones', 'zones-margin', 'vra-classes', 'swaths', 'route', 'access', 'markers', 'warnings'] as const;
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

/** Sequential 5-step ramp (low to high dose), legible over aerial imagery. */
export const VRA_PALETTE = ['#FDE725', '#7AD151', '#22A884', '#2A788E', '#414487'] as const;
export const VRA_UNCOVERED_COLOR = '#9CA3AF';

/** The n first steps of the ramp, spread evenly (2 to 5 classes). */
export function vraClassColors(n: number): string[] {
  const k = Math.max(1, Math.min(VRA_PALETTE.length, Math.floor(n)));
  if (k === 1) return [VRA_PALETTE[0]];
  return Array.from({ length: k }, (_, i) => VRA_PALETTE[Math.round((i * (VRA_PALETTE.length - 1)) / (k - 1))]);
}

type Feature = GeoJSON.Feature;
const feature = (geometry: GeoJSON.Geometry, properties: GeoJSON.GeoJsonProperties): Feature => ({ type: 'Feature', geometry, properties });
const fc = (features: Feature[]): GeoJSON.FeatureCollection => ({ type: 'FeatureCollection', features });

function anchorOf(g: GeoJSON.Geometry): GeoJSON.Point {
  switch (g.type) {
    case 'Point':
      return g;
    case 'LineString':
    case 'MultiLineString': {
      const line = g.type === 'LineString' ? g.coordinates : g.coordinates[0];
      return { type: 'Point', coordinates: line[Math.floor(line.length / 2)] };
    }
    default:
      break;
  }
  // Polygons (first part) and anything else: centre of the bounding box.
  const target = g.type === 'MultiPolygon' ? ({ type: 'Polygon', coordinates: g.coordinates[0] } as GeoJSON.Polygon) : g;
  const [x0, y0, x1, y1] = bboxOf(target.type === 'Polygon' ? { type: 'Polygon', coordinates: [target.coordinates[0]] } : target);
  return { type: 'Point', coordinates: [(x0 + x1) / 2, (y0 + y1) / 2] };
}

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
  // Each warning yields its shape (lines/polygons) plus one anchor point that carries the number.
  const warnings: Feature[] = [];
  (plan?.validation?.warnings ?? []).forEach((w, i) => {
    if (!w.geometry) return;
    const props = { n: i + 1, code: w.code, selected: m.selectedWarning === i + 1 };
    if (w.geometry.type !== 'Point') warnings.push(feature(w.geometry, { ...props, part: 'shape' }));
    warnings.push(feature(anchorOf(w.geometry), { ...props, part: 'anchor' }));
  });

  if (m.focus && !plan) {
    const props = { n: 0, code: 'ERROR', selected: true };
    if (m.focus.type !== 'Point') warnings.push(feature(m.focus, { ...props, part: 'shape' }));
    warnings.push(feature(anchorOf(m.focus), { ...props, part: 'anchor' }));
  }

  const presc = m.vra ?? null;
  const classColors = presc ? vraClassColors(presc.classes.length) : [];
  const colorOf = (ci: unknown): string =>
    typeof ci === 'number' && classColors[ci] ? classColors[ci] : VRA_UNCOVERED_COLOR;
  const labelOf = m.vraRateLabel ?? ((r: number) => String(r));

  const vraClasses: Feature[] = [];
  for (const z of presc?.zones.features ?? []) {
    const ci = z.properties?.class_index;
    const rate = z.properties?.rate;
    const color = colorOf(ci);
    vraClasses.push(feature(z.geometry, { part: 'fill', class_index: ci, rate, color }));
    vraClasses.push(feature(anchorOf(z.geometry), { part: 'label', class_index: ci, rate, color, label: typeof rate === 'number' ? labelOf(rate) : '' }));
  }

  const swaths: Feature[] = presc
    ? presc.swath_segments.features.map((s) => feature(s.geometry, {
        index: s.properties?.swath_index, kind: 'work', hovered: m.hoveredSwath === s.properties?.swath_index,
        class_index: s.properties?.class_index ?? null, color: colorOf(s.properties?.class_index),
      }))
    : (plan?.swaths ?? []).map((s) => feature(s.geometry, { index: s.index, kind: s.kind, hovered: m.hoveredSwath === s.index }));

  return {
    parcel: fc(m.parcel ? [feature(m.parcel, {})] : []),
    'parcel-rings': fc(rings),
    zones: fc(m.zones.map((z) => feature(z.polygon, { id: z.id, valid: z.valid, areaHa: z.areaHa }))),
    'zones-margin': fc(margin),
    'vra-classes': fc(vraClasses),
    swaths: fc(swaths),
    route: fc(plan ? [feature(plan.route, { stale: m.stale })] : []),
    access: fc(access),
    markers: fc(markers),
    warnings: fc(warnings),
  };
}

/**
 * Sources whose content depends on something that differs between two models.
 * `prev === null` means everything. Mirrors the inputs read in buildSources.
 */
export function changedSources(prev: MapModel | null, next: MapModel): SourceId[] {
  if (prev === null) return [...SOURCE_IDS];
  const ch = (...keys: (keyof MapModel)[]) => keys.some((k) => prev[k] !== next[k]);
  const out: SourceId[] = [];
  if (ch('parcel')) out.push('parcel', 'parcel-rings');
  if (ch('zones')) out.push('zones');
  if (ch('zones', 'marginM')) out.push('zones-margin');
  if (ch('vra', 'vraRateLabel')) out.push('vra-classes');
  if (ch('plan', 'hoveredSwath', 'vra')) out.push('swaths');
  if (ch('plan', 'stale')) out.push('route');
  if (ch('plan')) out.push('access');
  if (ch('plan', 'accessPoint', 'accessIssue')) out.push('markers');
  if (ch('plan', 'selectedWarning', 'focus')) out.push('warnings');
  return out;
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
      id: 'vra-classes-fill', type: 'fill', source: 'vra-classes', filter: ['==', ['get', 'part'], 'fill'],
      paint: { 'fill-color': ['get', 'color'], 'fill-opacity': 0.45 },
    },
    {
      id: 'vra-classes-line', type: 'line', source: 'vra-classes', filter: ['==', ['get', 'part'], 'fill'],
      paint: { 'line-color': ['get', 'color'], 'line-width': 1.5 },
    },
    {
      id: 'vra-classes-label', type: 'symbol', source: 'vra-classes', filter: ['==', ['get', 'part'], 'label'],
      layout: { 'text-field': ['get', 'label'], 'text-size': 12, 'text-allow-overlap': false },
      paint: { 'text-color': '#FFFFFF', 'text-halo-color': C.route, 'text-halo-width': 1.5 },
    },
    {
      id: 'swaths-line', type: 'line', source: 'swaths',
      paint: {
        'line-color': ['case', ['has', 'color'], ['get', 'color'], ['match', ['get', 'kind'], 'headland', C.headland, C.work]],
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
      id: 'warnings-shape', type: 'line', source: 'warnings', filter: ['==', ['get', 'part'], 'shape'],
      paint: { 'line-color': C.warning, 'line-width': 3, 'line-dasharray': [2, 1] },
    },
    {
      id: 'warnings-circle', type: 'circle', source: 'warnings', filter: ['==', ['get', 'part'], 'anchor'],
      paint: {
        'circle-radius': ['case', ['get', 'selected'], 13, 10],
        'circle-color': C.warning,
        'circle-stroke-color': C.route,
        'circle-stroke-width': ['case', ['get', 'selected'], 3, 1],
      },
    },
    {
      id: 'warnings-label', type: 'symbol', source: 'warnings', filter: ['==', ['get', 'part'], 'anchor'],
      layout: { 'text-field': ['to-string', ['get', 'n']], 'text-size': 12, 'text-allow-overlap': true },
      paint: { 'text-color': C.route },
    },
  ];
}

export function planBounds(m: MapModel): [number, number, number, number] | null {
  if (m.focus) return bboxOf(m.focus);
  if (m.parcel) return bboxOf(m.parcel);
  if (m.plan) return bboxOf(m.plan.route);
  return null;
}
