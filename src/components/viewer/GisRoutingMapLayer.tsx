import React, { useEffect, useRef, useCallback } from 'react';
import { useViewer, useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';
const ROUTE_STORAGE_KEY = 'nkz-gis-routing-last';

interface Props {
  viewer?: any;
}

export const GisRoutingMapLayer: React.FC<Props> = ({ viewer }) => {
  useTranslation(NS); // register namespace
  useViewer();
  const entitiesRef = useRef<string[]>([]);

  const renderRoute = useCallback((geometry: any, prescriptionMap?: any) => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    // Clear previous
    entitiesRef.current.forEach(id => {
      try { viewer.entities.removeById(id); } catch {}
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
        } catch {}
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
          } catch {}
        }
      });
    }
  }, [viewer]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    // 1. Same-tab: listen for custom event from RoutePreviewMap
    const onCustomEvent = (e: CustomEvent) => {
      renderRoute(e.detail?.geometry, e.detail?.prescriptionMap);
    };
    window.addEventListener('nekazari:gis-routing:routeGenerated', onCustomEvent as EventListener);

    // 2. Cross-tab: listen for localStorage changes
    const onStorage = (e: StorageEvent) => {
      if (e.key === ROUTE_STORAGE_KEY && e.newValue) {
        try {
          const data = JSON.parse(e.newValue);
          renderRoute(data.geometry, data.prescriptionMap);
        } catch {}
      }
    };
    window.addEventListener('storage', onStorage);

    // 3. On mount: check if a route was already saved
    try {
      const stored = localStorage.getItem(ROUTE_STORAGE_KEY);
      if (stored) {
        const data = JSON.parse(stored);
        renderRoute(data.geometry, data.prescriptionMap);
      }
    } catch {}

    return () => {
      window.removeEventListener('nekazari:gis-routing:routeGenerated', onCustomEvent as EventListener);
      window.removeEventListener('storage', onStorage);
      entitiesRef.current.forEach(id => {
        try { viewer.entities.removeById(id); } catch {}
      });
    };
  }, [viewer, renderRoute]);

  return null;
};
