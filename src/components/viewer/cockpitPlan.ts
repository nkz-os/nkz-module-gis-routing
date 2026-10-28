import type { Geometry } from 'geojson';
import type { OperationPlan } from '../../services/api';
import { vraClassColors } from '../../map/model';

export type PlanElement =
  | 'route' | 'swath' | 'access_path' | 'access_point' | 'exit_point'
  | 'exclusion_zone' | 'prescription_zone' | 'parcel_boundary' | 'working_area' | 'transit';

export interface PolygonPart { outer: number[][]; holes: number[][][] }

/** Cesium-independent description of one entity of the plan. */
export interface PlanSpec {
  id: string;
  element: PlanElement;
  kind: 'line' | 'polygon' | 'point';
  lines?: number[][][];
  polygons?: PolygonPart[];
  point?: number[];
  color?: string;
  width?: number;
  label?: string;
  labelAt?: number[];
}

const ELEMENTS: PlanElement[] = [
  'route', 'swath', 'access_path', 'access_point', 'exit_point', 'exclusion_zone',
  'prescription_zone', 'parcel_boundary', 'working_area', 'transit',
];

const LINE_STYLE: Partial<Record<PlanElement, { color: string; width: number }>> = {
  route: { color: '#ffffff', width: 2 },
  swath: { color: '#F59E0B', width: 3 },
  access_path: { color: '#38bdf8', width: 4 },
  transit: { color: '#3b82f6', width: 4 },
};
const OUTLINE_STYLE: Partial<Record<PlanElement, string>> = {
  parcel_boundary: '#e2e8f0',
  working_area: '#22c55e',
};

const UNIT: Record<string, string> = { kg_ha: 'kg/ha', l_ha: 'L/ha' };

function parts(g: Geometry): PolygonPart[] {
  const polys = g.type === 'Polygon' ? [g.coordinates] : g.type === 'MultiPolygon' ? g.coordinates : [];
  return polys.filter((p) => p.length > 0).map((p) => ({ outer: p[0], holes: p.slice(1) }));
}

function centroid(ring: number[][]): number[] {
  const pts = ring.slice(0, -1).length ? ring.slice(0, -1) : ring;
  return [
    pts.reduce((a, p) => a + p[0], 0) / pts.length,
    pts.reduce((a, p) => a + p[1], 0) / pts.length,
  ];
}

/** Every drawable element of a GET /operations/{id}/plan result; unknown or empty features are skipped. */
export function planEntitySpecs(plan: OperationPlan | null | undefined): PlanSpec[] {
  const features = Array.isArray(plan?.features) ? plan!.features : [];
  const classIndexes = [...new Set(features
    .filter((f) => f?.properties?.element === 'prescription_zone' && typeof f.properties.class_index === 'number')
    .map((f) => f.properties!.class_index as number))].sort((a, b) => a - b);
  const colors = vraClassColors(classIndexes.length || 1);

  const out: PlanSpec[] = [];
  features.forEach((f, i) => {
    const element = f?.properties?.element as PlanElement;
    const g = f?.geometry;
    if (!g || !ELEMENTS.includes(element)) return;
    const id = `gis-plan-${element}-${i}`;
    if (g.type === 'LineString' || g.type === 'MultiLineString') {
      const style = LINE_STYLE[element] ?? { color: '#ffffff', width: 2 };
      out.push({ id, element, kind: 'line', color: style.color, width: style.width,
        lines: g.type === 'LineString' ? [g.coordinates] : g.coordinates });
    } else if (g.type === 'Point') {
      out.push({ id, element, kind: 'point', point: g.coordinates });
    } else if (g.type === 'Polygon' || g.type === 'MultiPolygon') {
      const ps = parts(g);
      if (!ps.length) return;
      if (element === 'prescription_zone') {
        const rank = Math.max(0, classIndexes.indexOf(f.properties!.class_index));
        const rate = f.properties!.rate;
        const unit = UNIT[f.properties!.unit as string] ?? '';
        out.push({ id, element, kind: 'polygon', polygons: ps, color: colors[rank],
          label: typeof rate === 'number' ? `${rate} ${unit}`.trim() : undefined,
          labelAt: centroid(ps[0].outer) });
      } else {
        out.push({ id, element, kind: 'polygon', polygons: ps, color: OUTLINE_STYLE[element] });
      }
    }
  });
  return out;
}
