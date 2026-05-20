/**
 * GisRoutingMapLayer — Map-layer slot widget for the Cesium viewer.
 *
 * Two modes:
 * 1. Route visualization: listens for `nekazari:gis-routing:routeGenerated`
 *    events and renders swath polylines + VRA zone polygons.
 * 2. Pathfinding pick mode: activated by `nekazari:gis-routing:pickPathStart`,
 *    lets user click two points on the map, calculates A-B paths, renders
 *    3 alternatives with distinct colors.
 */
import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useViewer } from '@nekazari/sdk';
import { usePathfinding, PathAlternative } from '../../hooks/usePathfinding';

interface Props {
  viewer?: any;
}

const ALT_COLORS = ['#22c55e', '#F59E0B', '#3b82f6']; // green, amber, blue
const ALT_LABELS = ['Min elevation', 'Balanced', 'Shortest'];

export const GisRoutingMapLayer: React.FC<Props> = ({ viewer: propViewer }) => {
  const { cesiumViewer } = useViewer();
  const viewer = propViewer || cesiumViewer;
  const {
    state: pickState,
    pointA, pointB,
    alternatives,
    selectedAlternative,
    startPicking, cancelPicking,
    selectPoint, selectAlternative,
  } = usePathfinding();
  const entitiesRef = useRef<string[]>([]);
  const [pathEntities, setPathEntities] = useState<string[]>([]);

  // ---- Route visualization mode ----
  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    const handler = (e: CustomEvent) => {
      const { geometry, prescriptionMap } = e.detail || {};
      entitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
      entitiesRef.current = [];

      if (geometry?.type === 'MultiLineString' && geometry.coordinates) {
        geometry.coordinates.forEach((coords: number[][], idx: number) => {
          const entityId = `gis-routing-swatch-${idx}`;
          entitiesRef.current.push(entityId);
          try {
            viewer.entities.add({
              id: entityId,
              polyline: {
                positions: Cesium.Cartesian3.fromDegreesArray(
                  coords.flatMap(([lon, lat]) => [lon, lat]),
                ),
                width: 3,
                material: Cesium.Color.fromCssColorString('#F59E0B'),
                clampToGround: true,
              },
            });
          } catch { /* skip */ }
        });
      }

      if (prescriptionMap?.features) {
        prescriptionMap.features.forEach((feat: any, idx: number) => {
          if (feat.geometry?.type === 'Polygon') {
            const entityId = `gis-routing-vra-${idx}`;
            entitiesRef.current.push(entityId);
            try {
              const ring = feat.geometry.coordinates[0].map(
                ([lon, lat]: number[]) => Cesium.Cartesian3.fromDegrees(lon, lat),
              );
              const rate = feat.properties?.rate || 0;
              const alpha = Math.min(0.3 + Math.min(rate / 200, 0.5), 0.8);
              viewer.entities.add({
                id: entityId,
                polygon: {
                  hierarchy: ring,
                  material: Cesium.Color.fromCssColorString('#ef4444').withAlpha(alpha),
                  clampToGround: true,
                },
              });
            } catch { /* skip */ }
          }
        });
      }
    };

    window.addEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
    return () => {
      window.removeEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
      entitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
    };
  }, [viewer]);

  // ---- Pathfinding pick mode ----
  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    let handler: any = null;

    const onStart = () => startPicking();
    const onCancel = () => {
      // clean up pick-mode entities
      ['pf-point-a', 'pf-point-b', ...pathEntities].forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
      setPathEntities([]);
      if (handler && !handler.isDestroyed?.()) handler.destroy();
    };

    window.addEventListener('nekazari:gis-routing:pickPathStart', onStart);
    window.addEventListener('nekazari:gis-routing:pickPathCancel', onCancel);

    return () => {
      window.removeEventListener('nekazari:gis-routing:pickPathStart', onStart);
      window.removeEventListener('nekazari:gis-routing:pickPathCancel', onCancel);
      onCancel();
    };
  }, [viewer, startPicking, pathEntities]);

  // ScreenSpaceEventHandler for pick mode
  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    if (pickState !== 'picking-a' && pickState !== 'picking-b') return;

    const h = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
    h.setInputAction((click: any) => {
      const cartesian = viewer.scene.pickPosition(click.position);
      if (!cartesian) return;
      const carto = Cesium.Cartographic.fromCartesian(cartesian);
      const lon = Cesium.Math.toDegrees(carto.longitude);
      const lat = Cesium.Math.toDegrees(carto.latitude);
      selectPoint(lon, lat);
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => { if (!h.isDestroyed?.()) h.destroy(); };
  }, [viewer, pickState, selectPoint]);

  // Render point markers
  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    // Remove old point entities
    ['pf-point-a', 'pf-point-b'].forEach(id => {
      if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
    });

    if (pointA) {
      viewer.entities.add({
        id: 'pf-point-a',
        position: Cesium.Cartesian3.fromDegrees(pointA[0], pointA[1]),
        point: { pixelSize: 12, color: Cesium.Color.fromCssColorString('#22c55e'), outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
        label: { text: 'A', font: 'bold 14px sans-serif', fillColor: Cesium.Color.WHITE, verticalOrigin: Cesium.VerticalOrigin.BOTTOM, pixelOffset: new Cesium.Cartesian2(0, -10) },
      });
    }
    if (pointB) {
      viewer.entities.add({
        id: 'pf-point-b',
        position: Cesium.Cartesian3.fromDegrees(pointB[0], pointB[1]),
        point: { pixelSize: 12, color: Cesium.Color.fromCssColorString('#ef4444'), outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
        label: { text: 'B', font: 'bold 14px sans-serif', fillColor: Cesium.Color.WHITE, verticalOrigin: Cesium.VerticalOrigin.BOTTOM, pixelOffset: new Cesium.Cartesian2(0, -10) },
      });
    }
  }, [viewer, pointA, pointB]);

  // Render alternatives
  const selectPathOnMap = useCallback((alt: PathAlternative) => {
    selectAlternative(alt);
    window.dispatchEvent(new CustomEvent('nekazari:gis-routing:pathAlternativeSelected', { detail: alt }));
  }, [selectAlternative]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    pathEntities.forEach(id => {
      if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
    });
    const newIds: string[] = [];

    if (alternatives.length > 0 && (pickState === 'done' || pickState === 'calculating')) {
      alternatives.forEach((alt, idx) => {
        if (alt.geometry?.type === 'LineString' && alt.geometry.coordinates) {
          const entityId = `pf-path-${idx}`;
          newIds.push(entityId);
          const isSelected = selectedAlternative?.id === alt.id;
          try {
            const entity = viewer.entities.add({
              id: entityId,
              polyline: {
                positions: Cesium.Cartesian3.fromDegreesArray(
                  alt.geometry.coordinates.flatMap(([lon, lat]: number[]) => [lon, lat]),
                ),
                width: isSelected ? 6 : 4,
                material: Cesium.Color.fromCssColorString(ALT_COLORS[idx] || '#F59E0B'),
                clampToGround: true,
              },
              label: isSelected ? {
                text: `${ALT_LABELS[idx]}: ${(alt.distance_m / 1000).toFixed(2)}km`,
                font: '12px sans-serif',
                fillColor: Cesium.Color.WHITE,
                showBackground: true,
                backgroundColor: Cesium.Color.fromCssColorString('#1e293b'),
                verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                pixelOffset: new Cesium.Cartesian2(0, -8),
              } : undefined,
            });
            // Store alt data on entity for click handler
            (entity as any)._pfAlt = alt;
            (entity as any)._pfIdx = idx;
          } catch { /* skip */ }
        }
      });
    }
    setPathEntities(newIds);

    // Click handler for selecting alternatives on map
    let clickHandler: any = null;
    if (newIds.length > 0) {
      clickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      clickHandler.setInputAction((click: any) => {
        const picked = viewer.scene.pick(click.position);
        if (picked?.id?._pfAlt) {
          selectPathOnMap(picked.id._pfAlt);
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    }

    return () => {
      if (clickHandler && !clickHandler.isDestroyed?.()) clickHandler.destroy();
    };
  }, [viewer, alternatives, pickState, selectedAlternative, selectPathOnMap, pathEntities]);

  return null;
};
