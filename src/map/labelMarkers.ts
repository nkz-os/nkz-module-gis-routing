import type { Map as MapLibreMap, Marker, MarkerOptions } from 'maplibre-gl';
import { GATE_COLOR, NOGO_COLOR, labelAnchor } from './markers';

/**
 * Text labels are DOM markers: the basemap style declares no `glyphs`, so symbol-layer text
 * cannot render, and adding a glyph host would be a new external dependency.
 */
export interface LabelItem { key: string; at: [number, number]; text: string; kind: 'gate' | 'nogo' }

export function gateLabels(gate: GeoJSON.Point | null | undefined, text: string): LabelItem[] {
  return gate ? [{ key: 'gate', at: labelAnchor(gate), text, kind: 'gate' }] : [];
}

export function zoneLabels(zones: { id: string; geometry: GeoJSON.Geometry }[], text: string): LabelItem[] {
  return zones.map((z) => ({ key: `zone-${z.id}`, at: labelAnchor(z.geometry), text, kind: 'nogo' as const }));
}

function element(item: LabelItem): HTMLDivElement {
  const el = document.createElement('div');
  el.setAttribute('data-testid', `map-label-${item.kind}`);
  el.textContent = item.text;
  // Map markers live outside the host's Tailwind scope; sizes are fixed pixels.
  Object.assign(el.style, {
    pointerEvents: 'none', color: '#FFFFFF', fontSize: '11px', fontWeight: '700', lineHeight: '1', letterSpacing: '0.04em',
    padding: '2px 5px', borderRadius: '4px', whiteSpace: 'nowrap', boxShadow: '0 1px 3px rgba(0,0,0,0.5)',
    background: item.kind === 'gate' ? GATE_COLOR : NOGO_COLOR, border: '1px solid #FFFFFF',
    marginTop: item.kind === 'gate' ? '4px' : '0',
  });
  return el;
}

type MarkerCtor = new (o: MarkerOptions) => Marker;

export class LabelMarkers {
  private markers = new Map<string, { marker: Marker; item: LabelItem }>();
  constructor(private readonly map: MapLibreMap, private readonly Ctor: MarkerCtor) {}

  sync(items: LabelItem[]): void {
    const keep = new Set(items.map((i) => i.key));
    for (const [key, m] of this.markers) {
      if (!keep.has(key)) { m.marker.remove(); this.markers.delete(key); }
    }
    for (const item of items) {
      const have = this.markers.get(item.key);
      if (have) {
        have.marker.setLngLat(item.at);
        const el = have.marker.getElement();
        if (el.textContent !== item.text) el.textContent = item.text;
        have.item = item;
        continue;
      }
      const marker = new this.Ctor({ element: element(item), anchor: item.kind === 'gate' ? 'top' : 'center' })
        .setLngLat(item.at).addTo(this.map);
      this.markers.set(item.key, { marker, item });
    }
  }

  clear(): void {
    for (const m of this.markers.values()) m.marker.remove();
    this.markers.clear();
  }
}
