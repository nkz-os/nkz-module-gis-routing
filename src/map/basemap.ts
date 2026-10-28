// Region rules copied from the host viewer (utils/regions.ts), imagery only.
export type BasemapId = 'pnoa' | 'esri';

export const REGION_TABLE: { id: 'navarra' | 'spain' | 'eu'; bbox: [number, number, number, number]; imagery: BasemapId }[] = [
  { id: 'navarra', bbox: [-2.5, 42.0, -1.0, 43.5], imagery: 'pnoa' },
  { id: 'spain', bbox: [-18.5, 27.0, 5.0, 44.0], imagery: 'pnoa' },
  { id: 'eu', bbox: [-12.0, 34.0, 32.0, 62.0], imagery: 'esri' },
];

// REGION_TABLE is ordered by descending priority (navarra 3, spain 2, eu 1).
export function basemapFor(lon: number, lat: number): BasemapId {
  for (const r of REGION_TABLE) {
    const [w, s, e, n] = r.bbox;
    if (lon >= w && lon <= e && lat >= s && lat <= n) return r.imagery;
  }
  return 'esri';
}

const SOURCES: Record<BasemapId, { tiles: string[]; maxzoom: number; attribution: string }> = {
  pnoa: {
    tiles: ['https://www.ign.es/wmts/pnoa-ma?SERVICE=WMTS&REQUEST=GetTile&VERSION=1.0.0&LAYER=OI.OrthoimageCoverage&STYLE=default&FORMAT=image/jpeg&TILEMATRIXSET=GoogleMapsCompatible&TILEMATRIX={z}&TILEROW={y}&TILECOL={x}'],
    maxzoom: 19,
    attribution: 'PNOA - IGN España',
  },
  esri: {
    tiles: ['https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
    maxzoom: 19,
    attribution: 'Esri World Imagery',
  },
};

export function rasterSource(id: BasemapId): { type: 'raster'; tiles: string[]; tileSize: 256; maxzoom: number; attribution: string } {
  const s = SOURCES[id];
  return { type: 'raster', tiles: [...s.tiles], tileSize: 256, maxzoom: s.maxzoom, attribution: s.attribution };
}
