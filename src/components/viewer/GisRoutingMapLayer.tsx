/**
 * GisRoutingMapLayer — Map-layer slot widget for the Cesium viewer.
 *
 * 1. Route visualization: listens for `nekazari:gis-routing:routeGenerated`
 *    and renders swath polylines + VRA zone polygons.
 * 2. Pathfinding pick mode: activated via `nekazari:gis-routing:pickPathStart`,
 *    handles click-to-pick A/B points, renders markers + 3 alternatives.
 */
import React, { useEffect, useRef, useState } from 'react';
import { useViewer, useTranslation } from '@nekazari/sdk';
import { api, ApiError } from '../../services/api';
import { parts, planEntitySpecs, type PlanSpec } from './cockpitPlan';
import { MapLegend } from '../../map/MapLegend';
import { labelAnchor } from '../../map/markers';
import { gateEntityOptions, noGoEntityOptions, noGoHoleEntities } from './cesiumStyle';

interface Props {
  viewer?: any;
}

const ALT_COLORS = ['#22c55e', '#F59E0B', '#3b82f6'];

/** A-B jobs are polled once a second for up to five minutes. */
const POLL_INTERVAL_MS = 1000;
const POLL_MAX_MS = 5 * 60 * 1000;

interface PfError { code: string; params?: Record<string, unknown>; detail?: string }

export const GisRoutingMapLayer: React.FC<Props> = ({ viewer: propViewer }) => {
  const { cesiumViewer, selectedEntityId } = useViewer();
  const { t } = useTranslation('gis-routing');
  // Read when something is drawn: a language change must not clear what is already on the globe.
  const textsRef = useRef({ gate: '', nogo: '' });
  textsRef.current = { gate: t('map.legend.gate'), nogo: t('map.legend.nogo') };
  // The parcel's current gate and NO-GO zones are always shown. The plan carries its own snapshot of
  // them (what the route was computed with): it is drawn only while the current ones are not.
  const planConstraintIdsRef = useRef<string[]>([]);
  const cfgDrawnRef = useRef(false);
  const applyPlanSnapshotVisibilityRef = useRef<() => void>(() => {});
  const redrawCfgRef = useRef<() => void>(() => {});
  const selectedRef = useRef<string | null>(null);
  selectedRef.current = selectedEntityId || null;
  const [cfgDrawn, setCfgDrawn] = useState(false);
  const [planDrawn, setPlanDrawn] = useState(false);
  const viewer = propViewer || cesiumViewer;
  const routeEntitiesRef = useRef<string[]>([]);
  const parcelCfgEntitiesRef = useRef<string[]>([]);
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
  const emitPfState = (s: string, error?: PfError) => {
    window.dispatchEvent(new CustomEvent('nekazari:pf:stateChange', { detail: error ? { state: s, error } : { state: s } }));
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

    let drawToken = 0;

    const clearRoute = () => {
      routeEntitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
      routeEntitiesRef.current = [];
      planConstraintIdsRef.current = [];
      setPlanDrawn(false);
    };

    applyPlanSnapshotVisibilityRef.current = () => {
      if (viewer.isDestroyed?.()) return;
      for (const id of planConstraintIdsRef.current) {
        const e = viewer.entities.getById?.(id);
        if (e) e.show = !cfgDrawnRef.current;
      }
    };

    const addEntity = (opts: any) => {
      routeEntitiesRef.current.push(opts.id);
      try { viewer.entities.add(opts); } catch { /* skip */ }
    };
    const addSnapshotEntity = (opts: any) => {
      planConstraintIdsRef.current.push(opts.id);
      addEntity(opts);
    };

    const drawSpec = (spec: PlanSpec) => {
      const flat = (c: number[][]) => c.flatMap(([lon, lat]) => [lon, lat]);
      const css = (c: string) => Cesium.Color.fromCssColorString(c);
      if (spec.kind === 'line') {
        (spec.lines ?? []).forEach((coords, n) => addEntity({
          id: `${spec.id}-${n}`,
          polyline: {
            positions: Cesium.Cartesian3.fromDegreesArray(flat(coords)),
            width: spec.width ?? 3, material: css(spec.color ?? '#F59E0B'), clampToGround: true,
          },
        }));
      } else if (spec.kind === 'point' && spec.point) {
        const [lon, lat] = spec.point;
        if (spec.element === 'access_point') addSnapshotEntity(gateEntityOptions(Cesium, spec.id, lon, lat, textsRef.current.gate));
        else addEntity({
          id: spec.id, position: Cesium.Cartesian3.fromDegrees(lon, lat),
          point: { pixelSize: 12, color: css('#ef4444'), outlineColor: Cesium.Color.WHITE, outlineWidth: 2 },
        });
      } else if (spec.kind === 'polygon') {
        (spec.polygons ?? []).forEach((part, n) => {
          const id = `${spec.id}-${n}`;
          if (spec.element === 'exclusion_zone') {
            addSnapshotEntity(noGoEntityOptions(Cesium, id, part, n === 0 ? labelAnchor({ type: 'Polygon', coordinates: [part.outer] }) : undefined, textsRef.current.nogo));
            noGoHoleEntities(Cesium, id, part).forEach(addSnapshotEntity);
            return;
          }
          const hierarchy = new Cesium.PolygonHierarchy(
            Cesium.Cartesian3.fromDegreesArray(flat(part.outer)),
            part.holes.map((h) => new Cesium.PolygonHierarchy(Cesium.Cartesian3.fromDegreesArray(flat(h)))),
          );
          const color = css(spec.color ?? '#ffffff');
          const prescription = spec.element === 'prescription_zone';
          const entity: any = {
            id,
            polygon: { hierarchy, clampToGround: true, material: color.withAlpha(prescription ? 0.6 : 0.08) },
            polyline: {
              positions: Cesium.Cartesian3.fromDegreesArray(flat(part.outer)),
              width: prescription ? 1 : 2, material: color, clampToGround: true,
            },
          };
          if (prescription && spec.label && n === 0 && spec.labelAt) {
            entity.position = Cesium.Cartesian3.fromDegrees(spec.labelAt[0], spec.labelAt[1]);
            entity.label = {
              text: spec.label, font: 'bold 14px sans-serif', fillColor: Cesium.Color.WHITE,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE, outlineColor: css('#1e293b'), outlineWidth: 3,
              verticalOrigin: Cesium.VerticalOrigin.CENTER,
            };
          }
          addEntity(entity);
        });
      }
    };

    const drawLegacy = (geometry: any, prescriptionMap: any) => {
      const lines: number[][][] =
        geometry?.type === 'MultiLineString' ? geometry.coordinates
        : geometry?.type === 'LineString' ? [geometry.coordinates]
        : [];
      lines.forEach((coords: number[][], idx: number) => {
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

    const handler = (e: CustomEvent) => {
      const { geometry, prescriptionMap, operation_id: operationId } = e.detail || {};
      const token = ++drawToken;
      clearRoute();
      if (!operationId) { drawLegacy(geometry, prescriptionMap); return; }
      // The stored operation is the source of truth; a failed read falls back to the route we were given.
      api.getOperationPlan(operationId).then((plan) => {
        if (token !== drawToken || viewer.isDestroyed?.()) return;
        const specs = planEntitySpecs(plan);
        if (specs.length === 0) { drawLegacy(geometry, prescriptionMap); return; }
        specs.forEach(drawSpec);
        if (specs.some((sp) => sp.element === 'access_point' || sp.element === 'exclusion_zone')) {
          setPlanDrawn(true);
          applyPlanSnapshotVisibilityRef.current();
        }
      }).catch(() => {
        if (token !== drawToken || viewer.isDestroyed?.()) return;
        drawLegacy(geometry, prescriptionMap);
      });
    };

    // On mount, check for cross-tab saved route
    try {
      const stored = sessionStorage.getItem('nkz:gis-routing:lastSaved');
      if (stored) {
        const { geometry, prescriptionMap, operation_id: operationId, timestamp } = JSON.parse(stored);
        if ((geometry || operationId) && (Date.now() - timestamp < 60000)) {
          handler(new CustomEvent('nekazari:gis-routing:routeGenerated',
            { detail: { geometry, prescriptionMap, operation_id: operationId } }));
          sessionStorage.removeItem('nkz:gis-routing:lastSaved');
        }
      }
    } catch { /* ignore */ }

    window.addEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
    return () => {
      window.removeEventListener('nekazari:gis-routing:routeGenerated', handler as EventListener);
      drawToken++;
      clearRoute();
    };
  }, [viewer]);

  // ---- Parcel config overlay (access point + no-go zones) ----
  useEffect(() => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    let drawToken = 0;

    const clearCfgEntities = () => {
      parcelCfgEntitiesRef.current.forEach(id => {
        if (!viewer.isDestroyed?.()) viewer.entities.removeById(id);
      });
      parcelCfgEntitiesRef.current = [];
      cfgDrawnRef.current = false;
      setCfgDrawn(false);
      applyPlanSnapshotVisibilityRef.current();
    };

    const addCfg = (opts: any) => {
      try {
        viewer.entities.add(opts);
        parcelCfgEntitiesRef.current.push(opts.id);
      } catch { /* skip */ }
    };

    const drawParcel = (parcelId: string) => {
      const token = ++drawToken;
      clearCfgEntities();
      api.getParcelConfig(parcelId).then((d: any) => {
        if (token !== drawToken || viewer.isDestroyed?.()) return;
        const coords = d?.accessPoint?.coordinates;
        if (Array.isArray(coords) && coords.length >= 2) {
          addCfg(gateEntityOptions(Cesium, `gis-cfg-access-${parcelId}`, coords[0], coords[1], textsRef.current.gate));
        }
        ((d?.exclusionZones?.features ?? []) as any[]).forEach((feat: any, idx: number) => {
          if (!feat?.geometry) return;
          parts(feat.geometry).forEach((part, n) => {
            addCfg(noGoEntityOptions(
              Cesium, `gis-cfg-zone-${parcelId}-${idx}-${n}`, part,
              n === 0 ? labelAnchor({ type: 'Polygon', coordinates: [part.outer] }) : undefined, textsRef.current.nogo,
            ));
            noGoHoleEntities(Cesium, `gis-cfg-zone-${parcelId}-${idx}-${n}`, part).forEach(addCfg);
          });
        });
        cfgDrawnRef.current = parcelCfgEntitiesRef.current.length > 0;
        setCfgDrawn(cfgDrawnRef.current);
        applyPlanSnapshotVisibilityRef.current();
      }).catch(() => { /* ignore fetch errors */ });
    };
    redrawCfgRef.current = () => { if (selectedRef.current) drawParcel(selectedRef.current); else clearCfgEntities(); };

    const onShow = (e: Event) => {
      const { parcelId } = (e as CustomEvent).detail || {};
      if (parcelId) drawParcel(parcelId);
    };
    // Hiding the editor must not hide the constraints of the parcel that is still selected.
    const onHide = () => redrawCfgRef.current();

    redrawCfgRef.current();
    window.addEventListener('nekazari:gis-routing:parcelConfig:show', onShow);
    window.addEventListener('nekazari:gis-routing:parcelConfig:hide', onHide);
    return () => {
      drawToken++;
      window.removeEventListener('nekazari:gis-routing:parcelConfig:show', onShow);
      window.removeEventListener('nekazari:gis-routing:parcelConfig:hide', onHide);
      clearCfgEntities();
    };
  }, [viewer, selectedEntityId]);

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

      // Try Cesium terrain sampling as primary elevation source.
      // Falls back to eu-elevation backend raster (backend builds its own grid).
      let elevationGrid: any = null;
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
          // Cesium terrain samples north-to-south; build grid with SW origin (row 0 = south).
          for (let row = 0; row < GRID; row++) {
            for (let col = 0; col < GRID; col++) {
              const lon = minLon + (col / (GRID - 1)) * (maxLon - minLon);
              const lat = minLat + (row / (GRID - 1)) * (maxLat - minLat);  // south-to-north
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
            origin_lat: minLat,
            pixel_size_deg: (maxLon - minLon) / (GRID - 1),
            cols: GRID,
            rows: GRID,
          };
        }
      } catch (e) {
        console.warn('[GisRoutingMapLayer] Terrain sampling failed, falling back to backend DEM:', e);
      }

      api.startPathCalculation({
        point_a: pf.pointA,
        point_b: pf.pointB,
        machine_width_m: 3,
        max_slope_deg: 15,
        min_turn_radius_m: 8,
        parcel_id: selectedEntityId || null,
        elevation_grid: elevationGrid,
      }).then((res: any) => {
        const jobId = res?.job_id;
        if (jobId) startPolling(jobId);
        else finishWithError({ code: 'UNKNOWN' });
      }).catch((err: any) => {
        finishWithError(err instanceof ApiError
          ? { code: err.code || 'UNKNOWN', params: err.params, detail: err.detail }
          : { code: 'UNKNOWN', detail: err?.message });
      });
    };

    const finishWithError = (error: PfError) => {
      clearPolling();
      pf.state = 'done';
      emitPfState('done', error);
    };

    const startPolling = (jobId: string) => {
      const startedAt = Date.now();
      let inFlight = false;
      const timer = setInterval(async () => {
        if (inFlight) return;
        if (Date.now() - startedAt >= POLL_MAX_MS) { finishWithError({ code: 'JOB_TIMEOUT' }); return; }
        inFlight = true;
        try {
          const result: any = await api.getPathResult(jobId);
          if (pf.pollTimer !== timer) return; // cancelled while the request was in flight
          if (result?.status === 'completed') {
            clearPolling();
            pf.alternatives = result.alternatives || [];
            pf.state = 'done';
            emitPfState('done');
            renderAlternatives();
          } else if (result?.status === 'failed') {
            finishWithError({
              code: result.error_code || 'UNKNOWN',
              params: result.error_params || {},
              detail: result.error,
            });
          }
          // queued | running: keep polling
        } catch {
          // transient read error: the next tick retries until the deadline
        } finally {
          inFlight = false;
        }
      }, POLL_INTERVAL_MS);
      pf.pollTimer = timer;
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

  return cfgDrawn || planDrawn ? <MapLegend className="fixed bottom-4 left-4 z-20" /> : null;
};
