import area from '@turf/area';
import booleanValid from '@turf/boolean-valid';
import { polygon as turfPolygon } from '@turf/helpers';

export interface Zone {
  id: string;
  polygon: GeoJSON.Polygon;
  areaHa: number;
  valid: boolean;
}

export function areaHa(polygon: GeoJSON.Polygon): number {
  return Math.round((area({ type: 'Feature', properties: {}, geometry: polygon }) / 10000) * 1000) / 1000;
}

type Pt = number[];

function orient(a: Pt, b: Pt, c: Pt): number {
  const v = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]);
  return v > 0 ? 1 : v < 0 ? -1 : 0;
}

function onSegment(a: Pt, b: Pt, c: Pt): boolean {
  return Math.min(a[0], b[0]) <= c[0] && c[0] <= Math.max(a[0], b[0]) && Math.min(a[1], b[1]) <= c[1] && c[1] <= Math.max(a[1], b[1]);
}

function segmentsIntersect(a: Pt, b: Pt, c: Pt, d: Pt): boolean {
  const o1 = orient(a, b, c);
  const o2 = orient(a, b, d);
  const o3 = orient(c, d, a);
  const o4 = orient(c, d, b);
  if (o1 !== o2 && o3 !== o4) return true;
  return (o1 === 0 && onSegment(a, b, c)) || (o2 === 0 && onSegment(a, b, d)) || (o3 === 0 && onSegment(c, d, a)) || (o4 === 0 && onSegment(c, d, b));
}

// @turf/boolean-valid does not detect a self-crossing outer ring (bow-tie), so check it here.
function ringSelfIntersects(ring: Pt[]): boolean {
  const n = ring.length - 1; // number of segments
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const adjacent = j === i + 1 || (i === 0 && j === n - 1);
      if (adjacent) continue;
      if (segmentsIntersect(ring[i], ring[i + 1], ring[j], ring[j + 1])) return true;
    }
  }
  return false;
}

export function isValidPolygon(polygon: GeoJSON.Polygon): boolean {
  const ring = polygon.coordinates[0];
  if (!ring || ring.length < 4) return false;
  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first[0] !== last[0] || first[1] !== last[1]) return false;
  try {
    if (polygon.coordinates.some((r) => ringSelfIntersects(r))) return false;
    return booleanValid(turfPolygon(polygon.coordinates));
  } catch {
    return false;
  }
}

function walk(coords: unknown, visit: (p: number[]) => void): void {
  if (!Array.isArray(coords)) return;
  if (typeof coords[0] === 'number') {
    visit(coords as number[]);
    return;
  }
  for (const c of coords) walk(c, visit);
}

export function bboxOf(geometry: GeoJSON.Geometry): [number, number, number, number] {
  let minX = Infinity;
  let minY = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  const coords = geometry.type === 'GeometryCollection' ? geometry.geometries.map((g) => (g as { coordinates?: unknown }).coordinates) : (geometry as { coordinates: unknown }).coordinates;
  walk(coords, (p) => {
    if (p[0] < minX) minX = p[0];
    if (p[1] < minY) minY = p[1];
    if (p[0] > maxX) maxX = p[0];
    if (p[1] > maxY) maxY = p[1];
  });
  return [minX, minY, maxX, maxY];
}

export function ringToPolygon(ring: number[][]): GeoJSON.Polygon {
  const copy = ring.map((p) => [...p]);
  if (copy.length > 0) {
    const first = copy[0];
    const last = copy[copy.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) copy.push([...first]);
  }
  return { type: 'Polygon', coordinates: [copy] };
}

export function zonesToFeatureCollection(zones: Zone[]): GeoJSON.FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: zones.map((z) => ({ type: 'Feature', properties: { id: z.id }, geometry: z.polygon })),
  };
}

/**
 * Zones from the stored FeatureCollection. A MultiPolygon (the backend accepts and enforces
 * them) is split into one editable zone per part, ids `<id>#<k>`; saving writes them back as
 * Polygons, which the backend treats as the same union.
 */
export function featureCollectionToZones(fc: GeoJSON.FeatureCollection | null): Zone[] {
  if (!fc) return [];
  const zones: Zone[] = [];
  const push = (id: string, polygon: GeoJSON.Polygon) =>
    zones.push({ id, polygon, areaHa: areaHa(polygon), valid: isValidPolygon(polygon) });
  fc.features.forEach((f, i) => {
    const g = f.geometry;
    if (!g) return;
    const raw = f.properties?.id;
    const id = raw !== undefined && raw !== null ? String(raw) : `z${i}`;
    if (g.type === 'Polygon') push(id, g);
    else if (g.type === 'MultiPolygon') {
      g.coordinates.forEach((rings, k) => push(`${id}#${k}`, { type: 'Polygon', coordinates: rings }));
    }
  });
  return zones;
}

/** Great-circle distance in metres between two [lon, lat] points. */
export function distanceM(a: number[], b: number[]): number {
  const R = 6371008.8;
  const rad = Math.PI / 180;
  const dLat = (b[1] - a[1]) * rad;
  const dLon = (b[0] - a[0]) * rad;
  const h = Math.sin(dLat / 2) ** 2 + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(h)));
}
