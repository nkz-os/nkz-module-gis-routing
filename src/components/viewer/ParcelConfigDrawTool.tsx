/**
 * ParcelConfigDrawTool — Map-layer slot widget for the Cesium viewer.
 *
 * Lets the user configure a parcel's routing constraints directly on the 3D map:
 *   1. Drop a single access-point marker (mode `access`).
 *   2. Draw no-go polygons (mode `zone`): left-click to add vertices,
 *      double-click to close the ring.
 *
 * Activation/clear is driven by window CustomEvents; results are emitted back
 * the same way. Renders nothing in React (Cesium scene only).
 *
 * Events consumed:
 *   nekazari:gis-routing:parcelConfig:activate  { mode: 'access'|'zone'|'off' }
 *   nekazari:gis-routing:parcelConfig:clear     (no detail)
 *
 * Events emitted:
 *   nekazari:gis-routing:parcelConfig:accessPicked { lonlat: [lon, lat] }
 *   nekazari:gis-routing:parcelConfig:zoneDrawn    { ring: [[lon,lat], ...] }
 */
import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import { accent } from '../../config/accent';

interface Props {
  viewer?: any;
}

const ACCESS_POINT_ID = 'gis-routing-parcel-config-access';
const ZONE_TEMP_LINE_ID = 'gis-routing-parcel-config-zone-temp';

export const ParcelConfigDrawTool: React.FC<Props> = ({ viewer: propViewer }) => {
  const { cesiumViewer } = useViewer();
  const viewer = propViewer || cesiumViewer;

  const stateRef = useRef<{
    mode: 'off' | 'access' | 'zone';
    handler: any;
    entityIds: string[];
    zoneVerts: number[][];
    zoneIndex: number;
    currentMousePos: [number, number] | null;
  }>({
    mode: 'off',
    handler: null,
    entityIds: [],
    zoneVerts: [],
    zoneIndex: 0,
    currentMousePos: null,
  });

  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    const st = stateRef.current;

    // --- entity helpers ---
    const removeEntity = (id: string) => {
      if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      st.entityIds = st.entityIds.filter((e) => e !== id);
    };

    const removeAllEntities = () => {
      st.entityIds.forEach((id) => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
      st.entityIds = [];
    };

    const destroyHandler = () => {
      if (st.handler && !st.handler.isDestroyed?.()) st.handler.destroy();
      st.handler = null;
    };

    // Screen click -> [lon, lat] using the same pick technique as GisRoutingMapLayer.
    const pickLonLat = (screenPos: any): [number, number] | null => {
      let cartesian;
      if (viewer.scene.pickPositionSupported) {
        cartesian = viewer.scene.pickPosition(screenPos);
      }
      if (!Cesium.defined(cartesian)) {
        const ray = viewer.camera.getPickRay(screenPos);
        cartesian = viewer.scene.globe.pick(ray, viewer.scene);
      }
      if (!Cesium.defined(cartesian)) {
        cartesian = viewer.camera.pickEllipsoid(screenPos, viewer.scene.globe.ellipsoid);
      }
      if (!Cesium.defined(cartesian)) return null;
      const carto = Cesium.Cartographic.fromCartesian(cartesian);
      const lon = Cesium.Math.toDegrees(carto.longitude);
      const lat = Cesium.Math.toDegrees(carto.latitude);
      return [lon, lat];
    };

    // --- temporary in-progress polyline for zone drawing ---
    const clearTempLine = () => {
      removeEntity(ZONE_TEMP_LINE_ID);
    };

    const renderTempLine = () => {
      clearTempLine();
      if (st.zoneVerts.length < 1) return;
      try {
        st.entityIds.push(ZONE_TEMP_LINE_ID);
        viewer.entities.add({
          id: ZONE_TEMP_LINE_ID,
          polyline: {
            positions: new Cesium.CallbackProperty(() => {
              const pts = [...st.zoneVerts];
              if (st.currentMousePos) pts.push(st.currentMousePos);
              if (pts.length < 2) return [];
              return Cesium.Cartesian3.fromDegreesArray(
                pts.flatMap(([lon, lat]) => [lon, lat])
              );
            }, false),
            width: 4,
            material: Cesium.Color.fromCssColorString(accent.base),
            clampToGround: true,
          },
        });
      } catch {
        /* skip */
      }
    };

    const addAccessPoint = (lon: number, lat: number) => {
      removeEntity(ACCESS_POINT_ID);
      try {
        st.entityIds.push(ACCESS_POINT_ID);
        viewer.entities.add({
          id: ACCESS_POINT_ID,
          position: Cesium.Cartesian3.fromDegrees(lon, lat),
          point: {
            pixelSize: 14,
            color: Cesium.Color.fromCssColorString(accent.base),
            outlineColor: Cesium.Color.WHITE,
            outlineWidth: 2,
          },
          label: {
            text: '⚑', // flag glyph
            font: 'bold 18px sans-serif',
            fillColor: Cesium.Color.WHITE,
            style: Cesium.LabelStyle.FILL_AND_OUTLINE,
            outlineColor: Cesium.Color.fromCssColorString('#1e293b'),
            outlineWidth: 3,
            verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
            pixelOffset: new Cesium.Cartesian2(0, -12),
          },
        });
      } catch {
        /* skip */
      }
    };

    const closeZone = () => {
      if (st.zoneVerts.length < 3) return;
      const ring = [...st.zoneVerts.map((v) => [v[0], v[1]]), [st.zoneVerts[0][0], st.zoneVerts[0][1]]];
      const entityId = `gis-routing-parcel-config-zone-${st.zoneIndex++}`;
      try {
        st.entityIds.push(entityId);
        const hierarchy = st.zoneVerts.map(([lon, lat]) =>
          Cesium.Cartesian3.fromDegrees(lon, lat),
        );
        viewer.entities.add({
          id: entityId,
          polygon: {
            hierarchy,
            clampToGround: true,
            material: Cesium.Color.RED.withAlpha(0.3),
            outline: false,
          },
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(
              ring.flatMap(([lon, lat]) => [lon, lat])
            ),
            width: 4,
            material: Cesium.Color.RED,
            clampToGround: true,
          }
        });
      } catch {
        /* skip */
      }
      window.dispatchEvent(
        new CustomEvent('nekazari:gis-routing:parcelConfig:zoneDrawn', {
          detail: { ring },
        }),
      );
      st.zoneVerts = [];
      st.currentMousePos = null;
      clearTempLine();
    };

    // --- (re)install the screen-space click handler for the active mode ---
    const installHandler = () => {
      destroyHandler();
      if (st.mode === 'off') return;

      st.handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

      st.handler.setInputAction((click: any) => {
        const lonlat = pickLonLat(click.position);
        if (!lonlat) return;
        const [lon, lat] = lonlat;

        if (st.mode === 'access') {
          addAccessPoint(lon, lat);
          window.dispatchEvent(
            new CustomEvent('nekazari:gis-routing:parcelConfig:accessPicked', {
              detail: { lonlat: [lon, lat] },
            }),
          );
        } else if (st.mode === 'zone') {
          st.zoneVerts.push([lon, lat]);
          if (st.zoneVerts.length === 1) renderTempLine();
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      st.handler.setInputAction((move: any) => {
        if (st.mode !== 'zone' || st.zoneVerts.length === 0) return;
        st.currentMousePos = pickLonLat(move.endPosition);
      }, Cesium.ScreenSpaceEventType.MOUSE_MOVE);

      st.handler.setInputAction(() => {
        if (st.mode === 'zone') closeZone();
      }, Cesium.ScreenSpaceEventType.LEFT_DOUBLE_CLICK);
    };

    // --- event handlers ---
    const onActivate = (e: Event) => {
      const detail = (e as CustomEvent).detail || {};
      const mode: 'off' | 'access' | 'zone' =
        detail.mode === 'access' || detail.mode === 'zone' ? detail.mode : 'off';
      st.mode = mode;
      // Switching modes abandons any in-progress zone vertices.
      st.zoneVerts = [];
      st.currentMousePos = null;
      clearTempLine();
      if (mode === 'off') {
        destroyHandler();
      } else {
        installHandler();
      }
    };

    const onClear = () => {
      st.mode = 'off';
      st.zoneVerts = [];
      st.zoneIndex = 0;
      st.currentMousePos = null;
      destroyHandler();
      removeAllEntities();
    };

    window.addEventListener('nekazari:gis-routing:parcelConfig:activate', onActivate as EventListener);
    window.addEventListener('nekazari:gis-routing:parcelConfig:clear', onClear as EventListener);

    return () => {
      window.removeEventListener('nekazari:gis-routing:parcelConfig:activate', onActivate as EventListener);
      window.removeEventListener('nekazari:gis-routing:parcelConfig:clear', onClear as EventListener);
      destroyHandler();
      removeAllEntities();
      st.mode = 'off';
      st.zoneVerts = [];
      st.currentMousePos = null;
    };
  }, [viewer]);

  return null;
};
