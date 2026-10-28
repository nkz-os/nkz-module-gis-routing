import React, { useEffect, useRef, useState } from 'react';
import type { GeoJSONSource, Map as MapLibreMap, Marker } from 'maplibre-gl';
import { basemapFor, rasterSource, type BasemapId } from './basemap';
import { injectMapCss } from './injectMapCss';
import {
  TRANSIT_COLORS, buildTransitSources, changedTransitSources, transitBounds, transitLayerSpecs,
  type TransitMapModel, type TransitSourceId,
} from './transitModel';
import type { LonLat } from '../state/transitMachine';

export interface TransitViewChange { bbox: [number, number, number, number]; zoom: number }

export interface TransitMapCanvasProps {
  model: TransitMapModel;
  /** A map click places this point. */
  pick: 'a' | 'b' | null;
  /** Markers are not draggable and clicks are ignored while a request runs. */
  locked?: boolean;
  /** Changes: fit A, B and the alternatives. */
  fitKey: string | null;
  /** Initial view when there are no points yet. */
  homeBounds?: [number, number, number, number] | null;
  onPick: (which: 'a' | 'b', point: LonLat) => void;
  onMarkerMoved: (which: 'a' | 'b', point: LonLat) => void;
  onViewChange: (v: TransitViewChange) => void;
  onReady?: () => void;
  onError?: (e: Error) => void;
}

const DEFAULT_CENTER: [number, number] = [-3.7, 40.4];
const FIT_PADDING = 60;

function toError(e: unknown): Error {
  return e instanceof Error ? e : new Error(String(e));
}

function markerElement(label: string): HTMLDivElement {
  const el = document.createElement('div');
  el.setAttribute('data-testid', `marker-${label}`);
  el.textContent = label;
  // Map markers live outside the host's Tailwind scope; sizes are fixed pixels.
  Object.assign(el.style, {
    width: '26px', height: '26px', borderRadius: '9999px', color: '#FFFFFF', fontSize: '13px', fontWeight: '700',
    display: 'flex', alignItems: 'center', justifyContent: 'center', border: '2px solid #FFFFFF', cursor: 'grab',
    boxShadow: '0 1px 4px rgba(0,0,0,0.5)',
  });
  return el;
}

export const TransitMapCanvas: React.FC<TransitMapCanvasProps> = (props) => {
  const { model, pick, fitKey, locked = false } = props;
  const ref = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const markersRef = useRef<{ a: Marker | null; b: Marker | null }>({ a: null, b: null });
  const prevModelRef = useRef<TransitMapModel | null>(null);
  const [ready, setReady] = useState(false);

  const propsRef = useRef(props);
  propsRef.current = props;

  useEffect(() => {
    injectMapCss();
    let cancelled = false;
    let map: MapLibreMap | null = null;

    (async () => {
      const maplibregl = await import('maplibre-gl');
      if (cancelled || !ref.current) return;
      const home = propsRef.current.homeBounds;
      const centre: [number, number] = home ? [(home[0] + home[2]) / 2, (home[1] + home[3]) / 2] : DEFAULT_CENTER;
      const basemap: BasemapId = basemapFor(centre[0], centre[1]);

      const created = new maplibregl.Map({
        container: ref.current,
        style: {
          version: 8,
          sources: { basemap: rasterSource(basemap) },
          layers: [{ id: 'basemap', type: 'raster', source: 'basemap' }],
        },
        center: centre,
        zoom: 5,
        attributionControl: { compact: true },
      });
      created.addControl(new maplibregl.NavigationControl({ visualizePitch: false }), 'top-right');
      created.addControl(new maplibregl.ScaleControl({ unit: 'metric' }), 'bottom-left');
      map = created;

      created.on('error', (ev) => {
        const e = ev as { error?: unknown; tile?: unknown; sourceId?: unknown };
        if (e.tile || e.sourceId) {
          console.warn('[gis-routing] map tile/source error', e.error);
          return;
        }
        console.error('[gis-routing] map error', e.error);
        propsRef.current.onError?.(toError(e.error ?? ev));
      });

      created.on('load', () => {
        if (cancelled) return;
        try {
          const m = propsRef.current.model;
          const sources = buildTransitSources(m);
          for (const id of Object.keys(sources) as TransitSourceId[]) created.addSource(id, { type: 'geojson', data: sources[id] });
          for (const spec of transitLayerSpecs()) created.addLayer(spec);

          const view = (): TransitViewChange => {
            const b = created.getBounds();
            return { bbox: [b.getWest(), b.getSouth(), b.getEast(), b.getNorth()], zoom: created.getZoom() };
          };
          created.on('moveend', () => propsRef.current.onViewChange(view()));
          created.on('click', (e) => {
            const p = propsRef.current;
            if (!p.pick || p.locked) return;
            p.onPick(p.pick, [e.lngLat.lng, e.lngLat.lat]);
          });

          const b = transitBounds(m) ?? propsRef.current.homeBounds ?? null;
          if (b) created.fitBounds(b, { padding: FIT_PADDING, duration: 0, maxZoom: 16 });

          prevModelRef.current = m;
          mapRef.current = created;
          setReady(true);
          propsRef.current.onViewChange(view());
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
      markersRef.current.a?.remove();
      markersRef.current.b?.remove();
      markersRef.current = { a: null, b: null };
      mapRef.current = null;
      map?.remove();
    };
  }, []);

  // Model -> sources.
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const changed = changedTransitSources(prevModelRef.current, model);
    prevModelRef.current = model;
    if (changed.length === 0) return;
    const sources = buildTransitSources(model);
    for (const id of changed) (map.getSource(id) as GeoJSONSource | undefined)?.setData(sources[id]);
  }, [model, ready]);

  // A and B markers (draggable DOM markers).
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    let cancelled = false;
    (async () => {
      const maplibregl = await import('maplibre-gl');
      if (cancelled) return;
      for (const which of ['a', 'b'] as const) {
        const point = model[which];
        const existing = markersRef.current[which];
        if (!point) {
          existing?.remove();
          markersRef.current[which] = null;
          continue;
        }
        const bad = model.badPoint === which.toUpperCase();
        if (existing) {
          existing.setLngLat(point);
          existing.setDraggable(!locked);
          const el = existing.getElement();
          el.style.background = bad ? TRANSIT_COLORS.bad : TRANSIT_COLORS[which];
          el.style.outline = bad ? `3px solid ${TRANSIT_COLORS.bad}` : '';
          continue;
        }
        const el = markerElement(which.toUpperCase());
        el.style.background = bad ? TRANSIT_COLORS.bad : TRANSIT_COLORS[which];
        const marker = new maplibregl.Marker({ element: el, draggable: !locked }).setLngLat(point).addTo(map);
        marker.on('dragend', () => {
          const ll = marker.getLngLat();
          propsRef.current.onMarkerMoved(which, [ll.lng, ll.lat]);
        });
        markersRef.current[which] = marker;
      }
    })().catch((err) => propsRef.current.onError?.(toError(err)));
    return () => { cancelled = true; };
  }, [model.a, model.b, model.badPoint, locked, ready]);

  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    map.getCanvas().style.cursor = pick && !locked ? 'crosshair' : '';
  }, [pick, locked, ready]);

  // A map initialised under a hidden tab regains its size when shown.
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
    const b = transitBounds(model);
    if (b) map.fitBounds(b, { padding: FIT_PADDING, duration: 400, maxZoom: 16 });
    // eslint-disable-next-line react-hooks/exhaustive-deps -- refit only when fitKey changes
  }, [fitKey, ready]);

  return (
    <div className="absolute inset-0" data-testid="transit-map-canvas">
      <div ref={ref} className="h-full w-full" data-testid="transit-map-container" />
    </div>
  );
};
