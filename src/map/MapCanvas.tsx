import React, { useEffect, useRef, useState } from 'react';
import type { GeoJSONSource, LayerSpecification, Map as MapLibreMap } from 'maplibre-gl';
import type { TerraDraw } from 'terra-draw';
import { basemapFor, rasterSource, type BasemapId } from './basemap';
import { injectMapCss } from './injectMapCss';
import { buildSources, layerSpecs, planBounds, SOURCE_IDS, type MapModel, type SourceId } from './model';
import { ringToPolygon } from '../services/geo';

export type DrawMode = 'none' | 'zone' | 'access';
export type LayerGroup = 'zones' | 'access' | 'route' | 'swaths' | 'warnings';

export interface MapCanvasProps {
  model: MapModel;
  drawMode: DrawMode;
  /** Changes → fitBounds(planBounds(model)). */
  fitKey: string | null;
  onZoneDrawn: (polygon: GeoJSON.Polygon) => void;
  onZoneEdited: (id: string, polygon: GeoJSON.Polygon) => void;
  /** A vertex delete left the zone with fewer than 3 vertices. */
  onZoneRemoved?: (id: string) => void;
  onAccessPlaced: (point: GeoJSON.Point) => void;
  onSwathHover: (index: number | null) => void;
  onWarningClick: (n: number) => void;
  onReady?: () => void;
  onError?: (e: Error) => void;
  visibleLayers?: Partial<Record<LayerGroup, boolean>>;
  /** Pixels at the bottom covered by an overlay; added to the fitBounds bottom padding. */
  bottomInset?: number;
}

const FIT_PADDING = 40;
const fitPadding = (bottomInset = 0) => ({
  top: FIT_PADDING, left: FIT_PADDING, right: FIT_PADDING, bottom: FIT_PADDING + Math.max(0, bottomInset),
});

const DEFAULT_CENTER: [number, number] = [-3.7, 40.4];
const GROUP_SOURCES: Record<LayerGroup, SourceId[]> = {
  zones: ['zones', 'zones-margin'],
  access: ['access'],
  route: ['route'],
  swaths: ['swaths'],
  warnings: ['warnings'],
};
const GROUPS = Object.keys(GROUP_SOURCES) as LayerGroup[];

function centreOf(parcel: GeoJSON.Polygon | null): [number, number] {
  if (!parcel) return DEFAULT_CENTER;
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const [x, y] of parcel.coordinates[0]) {
    x0 = Math.min(x0, x); x1 = Math.max(x1, x);
    y0 = Math.min(y0, y); y1 = Math.max(y1, y);
  }
  return [(x0 + x1) / 2, (y0 + y1) / 2];
}

/** Drops the closing vertex and consecutive duplicates (a double-click close adds one). */
function dedupeRing(ring: number[][]): number[][] {
  const out: number[][] = [];
  for (const p of ring) {
    const prev = out[out.length - 1];
    if (!prev || prev[0] !== p[0] || prev[1] !== p[1]) out.push(p);
  }
  if (out.length > 1) {
    const f = out[0];
    const l = out[out.length - 1];
    if (f[0] === l[0] && f[1] === l[1]) out.pop();
  }
  return out;
}

function toError(e: unknown): Error {
  return e instanceof Error ? e : new Error(String(e));
}

export const MapCanvas: React.FC<MapCanvasProps> = (props) => {
  const { model, drawMode, fitKey, visibleLayers } = props;
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const drawRef = useRef<TerraDraw | null>(null);
  const basemapRef = useRef<BasemapId | null>(null);
  const editKeyRef = useRef<string>('');
  const [ready, setReady] = useState(false);

  // Latest props for the long-lived map/draw listeners.
  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    injectMapCss();
    let cancelled = false;
    let map: MapLibreMap | null = null;
    let draw: TerraDraw | null = null;

    (async () => {
      const [maplibregl, td, { TerraDrawMapLibreGLAdapter }] = await Promise.all([
        import('maplibre-gl'),
        import('terra-draw'),
        import('terra-draw-maplibre-gl-adapter'),
      ]);
      if (cancelled || !ref.current) return;

      const m0 = propsRef.current.model;
      const centre = centreOf(m0.parcel);
      const initialBasemap = basemapFor(centre[0], centre[1]);
      basemapRef.current = initialBasemap;

      const created = new maplibregl.Map({
        container: ref.current,
        style: {
          version: 8,
          sources: { basemap: rasterSource(initialBasemap) },
          layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
        },
        center: centre,
        zoom: 5,
        attributionControl: { compact: true },
      });
      created.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right');
      created.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
      map = created;
      const mapNow = created;

      mapNow.on('error', (ev) => {
        console.error('[gis-routing] map error', ev.error);
        propsRef.current.onError?.(toError(ev.error ?? ev));
      });

      mapNow.on('load', () => {
        if (cancelled) return;
        try {
        const sources = buildSources(propsRef.current.model);
        for (const id of SOURCE_IDS) mapNow.addSource(id, { type: 'geojson', data: sources[id] });
        for (const spec of layerSpecs()) mapNow.addLayer(spec);

        const m = propsRef.current.model;
        const b = planBounds(m);
        if (b) mapNow.fitBounds(b, { padding: fitPadding(propsRef.current.bottomInset), duration: 0 });

        mapNow.on('mousemove', 'swaths-line', (e) => {
          const idx = e.features?.[0]?.properties?.index;
          mapNow.getCanvas().style.cursor = 'pointer';
          propsRef.current.onSwathHover(typeof idx === 'number' ? idx : null);
        });
        mapNow.on('mouseleave', 'swaths-line', () => {
          mapNow.getCanvas().style.cursor = '';
          propsRef.current.onSwathHover(null);
        });
        const warningClick = (e: { features?: GeoJSON.Feature[] }) => {
          const n = e.features?.[0]?.properties?.n;
          if (typeof n === 'number') propsRef.current.onWarningClick(n);
        };
        mapNow.on('click', 'warnings-circle', warningClick);
        mapNow.on('click', 'warnings-label', warningClick);

        draw = new td.TerraDraw({
          adapter: new TerraDrawMapLibreGLAdapter({ map: mapNow }),
          modes: [
            new td.TerraDrawPolygonMode({
              styles: { fillOpacity: 0, outlineColor: '#F59E0B', outlineWidth: 2 },
            }),
            new td.TerraDrawPointMode({ styles: { pointColor: '#2563EB', pointWidth: 6 } }),
            new td.TerraDrawSelectMode({
              flags: {
                polygon: { feature: { draggable: false, coordinates: { midpoints: false, draggable: true, deletable: true } } },
                point: { feature: { draggable: true } },
              },
              styles: { selectedPolygonOutlineColor: '#F59E0B', selectionPointColor: '#FFFFFF' },
            }),
          ],
        });
        draw.start();
        draw.setMode('select');
        const d = draw;
        drawRef.current = d;

        d.on('finish', (id, ctx) => {
          const f = d.getSnapshotFeature(id);
          if (!f) return;
          const p = propsRef.current;
          if (ctx.action === 'draw') {
            if (f.geometry.type === 'Polygon') {
              p.onZoneDrawn(ringToPolygon(dedupeRing(f.geometry.coordinates[0])));
            } else if (f.geometry.type === 'Point') {
              p.onAccessPlaced({ type: 'Point', coordinates: f.geometry.coordinates });
            }
            d.removeFeatures([id]);
          } else if (
            ctx.action === 'dragCoordinate' ||
            ctx.action === 'dragFeature' ||
            ctx.action === 'deleteCoordinate' ||
            ctx.action === 'insertMidpoint'
          ) {
            const props = f.properties ?? {};
            if (f.geometry.type === 'Polygon' && typeof props.zoneId === 'string') {
              const polygon = ringToPolygon(dedupeRing(f.geometry.coordinates[0]));
              if (polygon.coordinates[0].length < 4) p.onZoneRemoved?.(props.zoneId);
              else p.onZoneEdited(props.zoneId, polygon);
            } else if (f.geometry.type === 'Point' && props.kind === 'access') {
              p.onAccessPlaced({ type: 'Point', coordinates: f.geometry.coordinates });
            }
          }
        });

        mapRef.current = mapNow;
        setReady(true);
        propsRef.current.onReady?.();
        } catch (err) {
          propsRef.current.onError?.(toError(err));
        }
      });
    })().catch((err) => {
      if (!cancelled) propsRef.current.onError?.(toError(err));
    });

    return () => {
      cancelled = true;
      setReady(false);
      try {
        draw?.stop();
      } catch (e) {
        console.error('[gis-routing] draw stop failed', e);
      }
      drawRef.current = null;
      mapRef.current = null;
      map?.remove();
    };
  }, []);

  // Model → sources.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const sources = buildSources(model);
    for (const id of SOURCE_IDS) (map.getSource(id) as GeoJSONSource | undefined)?.setData(sources[id]);
  }, [model, ready]);

  // Parcel → basemap by region (tiles cannot be swapped in place).
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const c = centreOf(model.parcel);
    const next = basemapFor(c[0], c[1]);
    if (next === basemapRef.current) return;
    basemapRef.current = next;
    const firstOwn = layerSpecs()[0].id;
    map.removeLayer('basemap');
    map.removeSource('basemap');
    map.addSource('basemap', rasterSource(next));
    map.addLayer({ id: 'basemap', type: 'raster', source: 'basemap' }, firstOwn);
  }, [model.parcel, ready]);

  // A map initialised or kept under a hidden tab regains its size when shown.
  useEffect(() => {
    const el = ref.current;
    if (!ready || !el || typeof ResizeObserver === 'undefined') return undefined;
    const ro = new ResizeObserver(() => mapRef.current?.resize());
    ro.observe(el);
    return () => ro.disconnect();
  }, [ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || fitKey === null) return;
    const b = planBounds(model);
    if (b) map.fitBounds(b, { padding: fitPadding(propsRef.current.bottomInset), duration: 400 });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refit only when fitKey changes
  }, [fitKey, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const specs: LayerSpecification[] = layerSpecs();
    for (const g of GROUPS) {
      const visible = visibleLayers?.[g] !== false;
      for (const spec of specs) {
        if ('source' in spec && GROUP_SOURCES[g].includes(spec.source as SourceId) && map.getLayer(spec.id)) {
          map.setLayoutProperty(spec.id, 'visibility', visible ? 'visible' : 'none');
        }
      }
    }
  }, [visibleLayers, ready]);

  // Draw mode.
  useEffect(() => {
    const draw = drawRef.current;
    if (!ready || !draw) return;
    draw.setMode(drawMode === 'zone' ? 'polygon' : drawMode === 'access' ? 'point' : 'select');
  }, [drawMode, ready]);

  // Editing copies of zones / access point inside terra-draw (select mode only).
  useEffect(() => {
    const draw = drawRef.current;
    if (!ready || !draw) return;
    if (drawMode !== 'none') {
      if (editKeyRef.current !== '') {
        draw.clear();
        editKeyRef.current = '';
        draw.setMode(drawMode === 'zone' ? 'polygon' : 'point');
      }
      return;
    }
    const key = JSON.stringify([model.zones.map((z) => [z.id, z.polygon.coordinates]), model.accessPoint?.coordinates ?? null]);
    if (key === editKeyRef.current) return;
    editKeyRef.current = key;
    draw.clear();
    const features: Parameters<TerraDraw['addFeatures']>[0] = model.zones
      .filter((z) => z.polygon.coordinates[0].length >= 4)
      .map((z) => ({ type: 'Feature', geometry: z.polygon, properties: { mode: 'polygon', zoneId: z.id } }));
    if (model.accessPoint) {
      features.push({ type: 'Feature', geometry: model.accessPoint, properties: { mode: 'point', kind: 'access' } });
    }
    if (features.length > 0) draw.addFeatures(features);
    draw.setMode('select');
  }, [model.zones, model.accessPoint, drawMode, ready]);

  // MapLibre's CSS sets position:relative on the element it owns, so it gets an
  // inner box with a real height inside the absolutely positioned wrapper.
  return (
    <div className="absolute inset-0" data-testid="map-canvas">
      <div ref={ref} className="h-full w-full" data-testid="map-container" />
    </div>
  );
};
