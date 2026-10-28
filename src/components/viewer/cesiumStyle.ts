/**
 * Single place where the 3D cockpit styles the gate and the NO-GO zones. Every Cesium drawing of
 * either goes through here, so changing the visual language is a change to this file only.
 * Same language as the MapLibre maps: gate icon + label, red diagonal hatch + thick red border.
 */
import type { PolygonPart } from './cockpitPlan';
import { NOGO_COLOR, gateDataUrl } from '../../map/markers';

type CesiumNs = any;

const lonlatFlat = (ring: number[][]) => ring.flatMap(([lon, lat]) => [lon, lat]);

function textLabel(Cesium: CesiumNs, text: string, fill: string, extra: Record<string, unknown>) {
  return {
    text,
    font: 'bold 13px sans-serif',
    fillColor: Cesium.Color.WHITE,
    showBackground: true,
    backgroundColor: Cesium.Color.fromCssColorString(fill),
    backgroundPadding: new Cesium.Cartesian2(5, 3),
    disableDepthTestDistance: Number.POSITIVE_INFINITY,
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
  const o = part.outer;
  const closed = o.length > 1 && o[0][0] === o[o.length - 1][0] && o[0][1] === o[o.length - 1][1];
  const hierarchy = new Cesium.PolygonHierarchy(
    Cesium.Cartesian3.fromDegreesArray(lonlatFlat(closed ? o.slice(0, -1) : o)),
    part.holes.map((h) => new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(lonlatFlat(h)))),
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
      positions: Cesium.Cartesian3.fromDegreesArray(lonlatFlat(closed ? o : [...o, o[0]])),
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
