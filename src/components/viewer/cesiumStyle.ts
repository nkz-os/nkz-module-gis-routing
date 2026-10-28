/**
 * Single place where the 3D cockpit styles the gate and the NO-GO zones. Every Cesium drawing of
 * either goes through here, so changing the visual language is a change to this file only.
 */
import type { PolygonPart } from './cockpitPlan';

type CesiumNs = any;

const lonlatFlat = (ring: number[][]) => ring.flatMap(([lon, lat]) => [lon, lat]);

export function gateEntityOptions(Cesium: CesiumNs, id: string, lon: number, lat: number, color: string) {
  return {
    id,
    position: Cesium.Cartesian3.fromDegrees(lon, lat),
    point: {
      pixelSize: 14,
      color: Cesium.Color.fromCssColorString(color),
      outlineColor: Cesium.Color.WHITE,
      outlineWidth: 2,
    },
    label: {
      text: '⚑',
      font: 'bold 18px sans-serif',
      fillColor: Cesium.Color.WHITE,
      style: Cesium.LabelStyle.FILL_AND_OUTLINE,
      outlineColor: Cesium.Color.fromCssColorString('#1e293b'),
      outlineWidth: 3,
      verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
      pixelOffset: new Cesium.Cartesian2(0, -12),
    },
  };
}

/** One entity per polygon part so a MultiPolygon zone is drawn whole. */
export function noGoEntityOptions(Cesium: CesiumNs, id: string, part: PolygonPart) {
  const o = part.outer;
  const closed = o.length > 1 && o[0][0] === o[o.length - 1][0] && o[0][1] === o[o.length - 1][1];
  const hierarchy = new Cesium.PolygonHierarchy(
    Cesium.Cartesian3.fromDegreesArray(lonlatFlat(closed ? o.slice(0, -1) : o)),
    part.holes.map((h) => new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(lonlatFlat(h)))),
  );
  return {
    id,
    polygon: {
      hierarchy,
      clampToGround: true,
      material: Cesium.Color.RED.withAlpha(0.3),
      outline: false,
    },
    polyline: {
      positions: Cesium.Cartesian3.fromDegreesArray(lonlatFlat(closed ? o : [...o, o[0]])),
      width: 4,
      material: Cesium.Color.RED,
      clampToGround: true,
    },
  };
}
