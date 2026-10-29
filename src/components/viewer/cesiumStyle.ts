/**
 * Single place where the 3D cockpit styles the gate and the NO-GO zones. Every Cesium drawing of
 * either goes through here, so changing the visual language is a change to this file only.
 * Same language as the MapLibre maps: gate icon + label, red diagonal hatch + thick red border.
 */
import type { PolygonPart } from './cockpitPlan';
import { NOGO_COLOR, gateDataUrl } from '../../map/markers';

type CesiumNs = any;

const lonlatFlat = (ring: number[][]) => ring.flatMap(([lon, lat]) => [lon, lat]);
const isClosed = (r: number[][]) => r.length > 1 && r[0][0] === r[r.length - 1][0] && r[0][1] === r[r.length - 1][1];
const open = (r: number[][]) => (isClosed(r) ? r.slice(0, -1) : r);
const closed = (r: number[][]) => (isClosed(r) ? r : [...r, r[0]]);

function textLabel(Cesium: CesiumNs, text: string, fill: string, extra: Record<string, unknown>) {
  return {
    text,
    font: 'bold 13px sans-serif',
    fillColor: Cesium.Color.WHITE,
    showBackground: true,
    backgroundColor: Cesium.Color.fromCssColorString(fill),
    backgroundPadding: new Cesium.Cartesian2(5, 3),
    disableDepthTestDistance: Number.POSITIVE_INFINITY,
    // The position has no height: without clamping it sits on the ellipsoid, under the terrain,
    // and with depth testing off it is drawn far from the real spot once the camera tilts.
    heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
    ...extra,
  };
}

/** Gate: the shared icon as a billboard, with its translated label under it. */
export function gateEntityOptions(Cesium: CesiumNs, id: string, lon: number, lat: number, labelText: string) {
  return {
    id,
    position: Cesium.Cartesian3.fromDegrees(lon, lat),
    billboard: {
      image: gateDataUrl(),
      width: 36,
      height: 36,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      disableDepthTestDistance: Number.POSITIVE_INFINITY,
      heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
    },
    label: textLabel(Cesium, labelText, '#2563EB', {
      verticalOrigin: Cesium.VerticalOrigin.TOP,
      pixelOffset: new Cesium.Cartesian2(0, 4),
    }),
  };
}

/**
 * One entity per polygon part so a MultiPolygon zone is drawn whole. `labelAt` + `labelText` add
 * the "NO-GO" label (give them to one part per zone only). The border is a separate clamped
 * polyline: Cesium has no outline on terrain-clamped polygons.
 */
export function noGoEntityOptions(
  Cesium: CesiumNs, id: string, part: PolygonPart, labelAt?: number[], labelText?: string,
) {
  const hierarchy = new Cesium.PolygonHierarchy(
    Cesium.Cartesian3.fromDegreesArray(lonlatFlat(open(part.outer))),
    part.holes.map((h) => new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(lonlatFlat(open(h))))),
  );
  const red = Cesium.Color.fromCssColorString(NOGO_COLOR);
  const material = Cesium.StripeMaterialProperty
    ? new Cesium.StripeMaterialProperty({
        evenColor: red.withAlpha(0.6),
        oddColor: red.withAlpha(0.12),
        repeat: 14,
        orientation: Cesium.StripeOrientation.HORIZONTAL,
      })
    : red.withAlpha(0.3);
  const entity: Record<string, unknown> = {
    id,
    polygon: {
      hierarchy,
      clampToGround: true,
      material,
      // Texture rotation turns the horizontal stripes into diagonals.
      stRotation: Math.PI / 4,
      outline: false,
    },
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray(lonlatFlat(closed(part.outer))),
      width: 4,
      material: red,
      clampToGround: true,
    },
  };
  if (labelAt && labelText) {
    entity.position = Cesium.Cartesian3.fromDegrees(labelAt[0], labelAt[1]);
    entity.label = textLabel(Cesium, labelText, NOGO_COLOR, { verticalOrigin: Cesium.VerticalOrigin.CENTER });
  }
  return entity;
}

/** Red border of each hole of a NO-GO part: an entity has one polyline, so holes get their own. */
export function noGoHoleEntities(Cesium: CesiumNs, id: string, part: PolygonPart) {
  const red = Cesium.Color.fromCssColorString(NOGO_COLOR);
  return part.holes.map((h, i) => ({
    id: `${id}-hole-${i}`,
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray(lonlatFlat(closed(h))),
      width: 4,
      material: red,
      clampToGround: true,
    },
  }));
}
