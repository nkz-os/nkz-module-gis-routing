/**
 * GisRoutingMapLayer — Map-layer slot widget for the Cesium viewer.
 *
 * Listens for `nekazari:gis-routing:routeGenerated` custom events dispatched
 * by RoutePreviewMap (or the full app wizard) and renders swath polylines and
 * VRA zone polygons on the Cesium globe.
 */
import React, { useEffect, useRef } from 'react';
import { useViewer, useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';

interface Props {
  viewer?: any;
}

export const GisRoutingMapLayer: React.FC<Props> = ({ viewer }) => {
  const { t } = useTranslation(NS);
  useViewer(); // re-render on entity selection changes
  const entitiesRef = useRef<string[]>([]);

  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    const handler = (e: CustomEvent) => {
      const { geometry, prescriptionMap } = e.detail || {};
      // Clear previous entities
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
          } catch {
            // Skip malformed coordinate sequences
          }
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
            } catch {
              // Skip malformed feature geometries
            }
          }
        });
      }
    };

    window.addEventListener(
      'nekazari:gis-routing:routeGenerated',
      handler as EventListener,
    );
    return () => {
      window.removeEventListener(
        'nekazari:gis-routing:routeGenerated',
        handler as EventListener,
      );
      entitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
    };
  }, [viewer, t]);

  return null;
};
