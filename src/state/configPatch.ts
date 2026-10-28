import type { FeatureCollection, Geometry, Point } from 'geojson';
import type { ParcelConfigPatch } from '../services/api';

export interface CfgZone { id: string; ring: number[][]; geometry?: Geometry }
export interface CfgSnapshot { gate: [number, number] | null; zones: CfgZone[] }

const sameGate = (a: [number, number] | null, b: [number, number] | null) =>
  a === b || (!!a && !!b && a[0] === b[0] && a[1] === b[1]);

const sameZones = (a: CfgZone[], b: CfgZone[]) =>
  a.length === b.length && a.every((z, i) => z.id === b[i].id && JSON.stringify(z.ring) === JSON.stringify(b[i].ring));

export function zonesToCollection(zones: CfgZone[]): FeatureCollection {
  return {
    type: 'FeatureCollection',
    features: zones.map((z) => ({
      type: 'Feature' as const, properties: { id: z.id },
      geometry: z.geometry ?? { type: 'Polygon' as const, coordinates: [z.ring] },
    })),
  };
}

/**
 * The body of PUT /parcels/{id}/config with ONLY what the user changed since the configuration was
 * loaded: an absent field is unchanged on the backend, so saving the gate never rewrites the zones.
 * An empty zone collection is sent only when zones existed and the user deleted them all.
 */
export function buildConfigPatch(loaded: CfgSnapshot, current: CfgSnapshot): ParcelConfigPatch {
  const patch: ParcelConfigPatch = {};
  if (!sameGate(loaded.gate, current.gate)) {
    patch.accessPoint = current.gate
      ? ({ type: 'Point', coordinates: current.gate } as Point)
      : null;
  }
  if (!sameZones(loaded.zones, current.zones)) patch.exclusionZones = zonesToCollection(current.zones);
  return patch;
}
