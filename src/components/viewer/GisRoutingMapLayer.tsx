/**
 * GisRoutingMapLayer — Map-layer slot widget for the Cesium viewer.
 *
 * 1. Route visualization: listens for `nekazari:gis-routing:routeGenerated`
 *    and renders swath polylines + VRA zone polygons.
 * 2. Pathfinding pick mode: activated via `nekazari:gis-routing:pickPathStart`,
 *    handles click-to-pick A/B points, renders markers + 3 alternatives.
 */
import React, { useEffect, useRef } from 'react';
import { useViewer } from '@nekazari/sdk';
import { api } from '../../services/api';

interface Props {
  viewer?: any;
}

const ALT_COLORS = ['#22c55e', '#F59E0B', '#3b82f6'];

export const GisRoutingMapLayer: React.FC<Props> = ({ viewer: propViewer }) => {
  const { cesiumViewer, selectedEntityId } = useViewer() as any;
  const viewer = propViewer || cesiumViewer;
  const routeEntitiesRef = useRef<string[]>([]);
  const pfRef = useRef<{
    state: 'idle' | 'picking-a' | 'picking-b' | 'calculating' | 'done';
    pointA: [number, number] | null;
    pointB: [number, number] | null;
    entities: string[];
    clickHandler: any;
    pollTimer: any;
    alternatives: any[];
    selectedAlt: any;
  }>({
    state: 'idle', pointA: null, pointB: null, entities: [],
    clickHandler: null, pollTimer: null, alternatives: [], selectedAlt: null,
  });

  // Helper: emit state to context panel
  const emitPfState = (s: string) => {
    window.dispatchEvent(new CustomEvent('nekazari:pf:stateChange', { detail: { state: s } }));
  };

  // Cancel pick mode when entity selection changes
  useEffect(() => {
    if (pfRef.current.state !== 'idle') {
      pfRef.current.entities.forEach(id => {
        if (!viewer?.isDestroyed?.()) viewer?.entities.removeById(id);
      });
      pfRef.current.entities = [];
      if (pfRef.current.clickHandler && !pfRef.current.clickHandler.isDestroyed?.()) {
        pfRef.current.clickHandler.destroy();
      }
      pfRef.current.clickHandler = null;
      if (pfRef.current.pollTimer) { clearInterval(pfRef.current.pollTimer); pfRef.current.pollTimer = null; }
      pfRef.current.state = 'idle';
      pfRef.current.pointA = null;
      pfRef.current.pointB = null;
      pfRef.current.alternatives = [];
      pfRef.current.selectedAlt = null;
      window.dispatchEvent(new CustomEvent('nekazari:pf:stateChange', { detail: { state: 'idle' } }));
    }
  }, [selectedEntityId, viewer]);

  // ---- Route visualization ----
  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    const handler = (e: CustomEvent) => {
      const { geometry, prescriptionMap } = e.detail || {};
      routeEntitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
      routeEntitiesRef.current = [];

      if (geometry?.type === 'MultiLineString' && geometry.coordinates) {
        geometry.coordinates.forEach((coords: number[][], idx: number) => {
          const entityId = `gis-routing-swatch-${idx}`;
          routeEntitiesRef.current.push(entityId);
          try {
            viewer.entities.add({
              id: entityId, polyline: {
                positions: Cesium.Cartesian3.fromDegreesArray(coords.flatMap(([lon, lat]) => [lon, lat])),
                width: 3, material: Cesium.Color.fromCssColorString('#F59E0B'), clampToGround: true,
              },
            });
          } catch { /* skip */ }
        });
      }
      if (prescriptionMap?.features) {
        prescriptionMap.features.forEach((feat: any, idx: number) => {
          if (feat.geometry?.type === 'Polygon') {
            const entityId = `gis-routing-vra-${idx}`;
            routeEntitiesRef.current.push(entityId);
            try {
              const ring = feat.geometry.coordinates[0].map(
                ([lon, lat]: number[]) => Cesium.Cartesian3.fromDegrees(lon, lat),
              );
              const rate = feat.properties?.rate || 0;
              const alpha = Math.min(0.3 + Math.min(rate / 200, 0.5), 0.8);
              viewer.entities.add({
                id: entityId, polygon: {
                  hierarchy: ring, clampToGround: true,
                  material: Cesium.Color.fromCssColorString('#ef4444').withAlpha(alpha),
                },
              });
            } catch { /* skip */ }
          }
        });
      }
    };

    // On mount, check for cross-tab saved route
    try {
      const stored = sessionStorage.getItem('nkz:gis-routing:lastSaved');
      if (stored) {
        const { geometry, prescriptionMap, timestamp } = JSON.parse(stored);
        if (geometry && (Date.now() - timestamp < 60000)) {
          handler(new CustomEvent('nekazari:gis-routing:routeGenerated', { detail: { geometry, prescriptionMap } }));
          sessionStorage.removeItem('nkz:gis-routing:lastSaved');
        }
      }
    } catch { /* ignore */ }

    window.addEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
    return () => {
      window.removeEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
      routeEntitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
    };
  }, [viewer]);

  // ---- Pathfinding pick mode (single consolidated effect) ----
  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    const pf = pfRef.current;

    const clearPfEntities = () => {
      pf.entities.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
      pf.entities = [];
    };

    const clearPolling = () => {
      if (pf.pollTimer) { clearInterval(pf.pollTimer); pf.pollTimer = null; }
    };

    const cleanupClickHandler = () => {
      if (pf.clickHandler && !pf.clickHandler.isDestroyed?.()) pf.clickHandler.destroy();
      pf.clickHandler = null;
    };

    const cancel = () => {
      clearPfEntities();
      clearPolling();
      cleanupClickHandler();
      pf.state = 'idle'; pf.pointA = null; pf.pointB = null;
      pf.alternatives = []; pf.selectedAlt = null;
      emitPfState('idle');
    };

    const addPointMarker = (id: string, lon: number, lat: number, color: string, label: string) => {
      pf.entities.push(id);
      viewer.entities.add({
        id, position: Cesium.Cartesian3.fromDegrees(lon, lat),
        point: { pixelSize: 14, color: Cesium.Color.fromCssColorString(color), outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
        label: { text: label, font: 'bold 16px sans-serif', fillColor: Cesium.Color.WHITE,
          style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineColor: Cesium.Color.fromCssColorString('#1e293b'), outlineWidth: 3,
          verticalOrigin: Cesium.VerticalOrigin.BOTTOM, pixelOffset: new Cesium.Cartesian2(0, -12) },
      });
    };

    const submitPathfinding = async () => {
      if (!pf.pointA || !pf.pointB) return;

      const [lonA, latA] = pf.pointA;
      const [lonB, latB] = pf.pointB;

      let elevationGrid: any = null;

      // Try Cesium terrain sampling first
      try {
        const terrainProvider = viewer.terrainProvider;
        if (terrainProvider && !(terrainProvider instanceof Cesium.EllipsoidTerrainProvider)) {
          const margin = 0.003;
          const minLon = Math.min(lonA, lonB) - margin;
          const maxLon = Math.max(lonA, lonB) + margin;
          const minLat = Math.min(latA, latB) - margin;
          const maxLat = Math.max(latA, latB) + margin;

          const GRID = 40;
          const positions: any[] = [];
          for (let row = 0; row < GRID; row++) {
            for (let col = 0; col < GRID; col++) {
              const lon = minLon + (col / (GRID - 1)) * (maxLon - minLon);
              const lat = minLat + (row / (GRID - 1)) * (maxLat - minLat);
              positions.push(Cesium.Cartographic.fromDegrees(lon, lat));
            }
          }

          const sampled = await Cesium.sampleTerrainMostDetailed(terrainProvider, positions);
          const elevations: number[][] = [];
          for (let row = 0; row < GRID; row++) {
            elevations.push(sampled.slice(row * GRID, (row + 1) * GRID).map((c: any) => c.height));
          }

          elevationGrid = {
            elevations,
            origin_lon: minLon,
            origin_lat: maxLat,
            pixel_size_deg: (maxLon - minLon) / (GRID - 1),
            cols: GRID,
          };
        }
      } catch (e) {
        console.warn('[GisRoutingMapLayer] Terrain sampling failed, falling back to eu-dem:', e);
      }

      api.startPathCalculation({
        point_a: pf.pointA,
        point_b: pf.pointB,
        machine_width_m: 3,
        max_slope_deg: 15,
        min_turn_radius_m: 8,
        elevation_source: elevationGrid ? 'cesium-terrain' : 'eu-dem',
        elevation_grid: elevationGrid,
      }).then((res: any) => {
        const jobId = res?.job_id;
        if (jobId) startPolling(jobId);
        else { pf.state = 'done'; emitPfState('done'); }
      }).catch(() => {
        pf.state = 'done'; emitPfState('done');
      });
    };

    const startPolling = (jobId: string) => {
      let attempts = 0;
      pf.pollTimer = setInterval(async () => {
        attempts++;
        try {
          const result: any = await api.getPathResult(jobId);
          if (result?.status === 'completed') {
            clearPolling();
            pf.alternatives = result.alternatives || [];
            pf.state = 'done';
            emitPfState('done');
            renderAlternatives();
          } else if (result?.status === 'failed') {
            clearPolling();
            pf.state = 'done';
            emitPfState('done');
          } else if (attempts >= 30) {
            clearPolling();
            pf.state = 'done';
            emitPfState('done');
          }
        } catch {
          if (attempts >= 30) { clearPolling(); pf.state = 'done'; emitPfState('done'); }
        }
      }, 2000);
    };

    const renderAlternatives = () => {
      // Remove old path entities
      pf.entities = pf.entities.filter(id => {
        if (id.startsWith('pf-path-')) {
          if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
          return false;
        }
        return true;
      });

      pf.alternatives.forEach((alt: any, idx: number) => {
        if (alt.geometry?.type !== 'LineString' || !alt.geometry.coordinates) return;
        const entityId = `pf-path-${idx}`;
        pf.entities.push(entityId);
        const isSelected = pf.selectedAlt?.id === alt.id;
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
            label: {
              text: `${(alt.distance_m / 1000).toFixed(2)} km · ${alt.cumulative_climb_m?.toFixed(0) || 0} m`,
              font: '11px sans-serif',
              fillColor: Cesium.Color.WHITE,
              showBackground: true,
              backgroundColor: Cesium.Color.fromCssColorString('#1e293b'),
              verticalOrigin: Cesium.VerticalOrigin.TOP,
              pixelOffset: new Cesium.Cartesian2(0, 8),
            },
          });
          (entity as any)._pfAlt = alt;
        } catch { /* skip */ }
      });
    };

    const onPickStart = () => {
      cancel();
      pf.state = 'picking-a';
      emitPfState('picking-a');

      pf.clickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      pf.clickHandler.setInputAction((click: any) => {
        // Ignore clicks on existing path entities (allow selecting alternatives)
        if (pf.state === 'done') return;

        const cartesian = viewer.scene.pickPosition(click.position);
        if (!Cesium.defined(cartesian)) return; // clicked sky

        const carto = Cesium.Cartographic.fromCartesian(cartesian);
        const lon = Cesium.Math.toDegrees(carto.longitude);
        const lat = Cesium.Math.toDegrees(carto.latitude);

        if (pf.state === 'picking-a') {
          // Visual feedback: flash effect via entity add + small delay
          addPointMarker('pf-point-a', lon, lat, '#22c55e', 'A');
          pf.pointA = [lon, lat];
          pf.state = 'picking-b';
          emitPfState('picking-b');
        } else if (pf.state === 'picking-b' && pf.pointA) {
          addPointMarker('pf-point-b', lon, lat, '#ef4444', 'B');
          pf.pointB = [lon, lat];
          pf.state = 'calculating';
          emitPfState('calculating');

          // Sample terrain via Cesium, then call API
          submitPathfinding();
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    };

    const onPickCancel = () => cancel();

    // Click handler for selecting alternatives (only when done)
    const setupAltClick = () => {
      if (pf.state !== 'done' || pf.alternatives.length === 0) return;
      if (pf.clickHandler && !pf.clickHandler.isDestroyed?.()) pf.clickHandler.destroy();

      pf.clickHandler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      pf.clickHandler.setInputAction((click: any) => {
        const picked = viewer.scene.pick(click.position);
        if (picked?.id?._pfAlt) {
          pf.selectedAlt = picked.id._pfAlt;
          window.dispatchEvent(new CustomEvent('nekazari:gis-routing:pathAlternativeSelected', {
            detail: pf.selectedAlt,
          }));
          renderAlternatives(); // re-render with highlight
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    };

    // Re-render alternatives when selection changes (called externally)
    const onAltSelected = (e: Event) => {
      pf.selectedAlt = (e as CustomEvent).detail;
      renderAlternatives();
    };

    window.addEventListener('nekazari:gis-routing:pickPathStart', onPickStart);
    window.addEventListener('nekazari:gis-routing:pickPathCancel', onPickCancel);
    window.addEventListener('nekazari:gis-routing:pathAlternativeSelected', onAltSelected);

    // Watch for state changes to switch click handler mode
    const stateInterval = setInterval(() => {
      if (pf.state === 'done' && pf.alternatives.length > 0) {
        setupAltClick();
      }
    }, 500);

    return () => {
      window.removeEventListener('nekazari:gis-routing:pickPathStart', onPickStart);
      window.removeEventListener('nekazari:gis-routing:pickPathCancel', onPickCancel);
      window.removeEventListener('nekazari:gis-routing:pathAlternativeSelected', onAltSelected);
      clearInterval(stateInterval);
      cancel();
    };
  }, [viewer]);

  return null;
};
