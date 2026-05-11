import React, { useEffect, useMemo } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Map, ExternalLink, Loader2 } from 'lucide-react';

const NS = 'gis-routing';

interface Props {
  parcelGeometry: any;
  parcelName: string;
  result: any;
  generating: boolean;
}

export const RoutePreviewMap: React.FC<Props> = ({
  parcelGeometry, parcelName, result, generating,
}) => {
  const { t } = useTranslation(NS);

  useEffect(() => {
    if (result) {
      const payload = {
        geometry: result.data?.geometry,
        prescriptionMap: result.prescription_map,
      };
      // Same-tab: custom event for embedded viewer
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: payload,
      }));
      // Cross-tab: localStorage so viewer at /entities picks it up
      localStorage.setItem('nkz-gis-routing-last', JSON.stringify(payload));
    }
  }, [result]);

  const openViewer = () => {
    window.open('/entities', '_blank', 'noopener');
  };

  const svgContent = useMemo(() => {
    if (!result?.data?.geometry) return null;
    return renderRouteSvg(result.data.geometry, parcelGeometry);
  }, [result, parcelGeometry]);

  if (generating) {
    return (
      <div className="flex flex-col items-center gap-3 py-8">
        <Loader2 className="w-6 h-6 animate-spin text-amber-500" />
        <p className="text-nkz-sm text-nkz-text-secondary">{t('actions.generating')}...</p>
      </div>
    );
  }

  if (!result) {
    return (
      <div className="flex flex-col items-center gap-3 py-12 text-center">
        <Map className="w-10 h-10 text-nkz-text-muted" />
        <p className="text-nkz-sm text-nkz-text-secondary">{t('panels.emptyState')}</p>
        <p className="text-nkz-xs text-nkz-text-secondary">{t('panels.emptyStateHint')}</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* SVG preview */}
      {svgContent && (
        <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt overflow-hidden">
          <div className="px-3 py-2 border-b border-nkz-default flex items-center justify-between">
            <span className="text-nkz-xs font-semibold text-nkz-text-secondary">
              {parcelName} — {result.data?.properties?.swath_count} {t('stats.swaths').toLowerCase()}
            </span>
            <span className="text-nkz-xs text-nkz-text-secondary">
              {result.data?.properties?.total_distance_m
                ? `${(result.data.properties.total_distance_m / 1000).toFixed(2)} km`
                : ''}
            </span>
          </div>
          <div className="p-3 flex justify-center bg-white">
            <div dangerouslySetInnerHTML={{ __html: svgContent }} />
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex gap-2">
        <button
          onClick={openViewer}
          className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
          style={{ backgroundColor: '#CA8A04' }}
        >
          <ExternalLink className="w-4 h-4" />
          {t('panels.viewOnMap')}
        </button>
      </div>
      <p className="text-nkz-xs text-nkz-text-secondary text-center">{t('panels.viewOnMapHint')}</p>
    </div>
  );
};

function renderRouteSvg(geometry: any, parcelGeometry?: any): string | null {
  if (!geometry?.coordinates) return null;

  const swaths: number[][][] = geometry.type === 'MultiLineString'
    ? geometry.coordinates
    : [geometry.coordinates];

  // Compute bbox from all coordinates
  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  const allCoords: number[][][] = [...swaths];
  if (parcelGeometry?.coordinates?.[0]) {
    allCoords.push(parcelGeometry.coordinates[0]);
  }

  for (const line of allCoords) {
    for (const [lon, lat] of line) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }

  const pad = 0.0002;
  minLon -= pad; maxLon += pad; minLat -= pad; maxLat += pad;
  const w = 400;
  const h = 300;
  const scaleX = (lon: number) => ((lon - minLon) / (maxLon - minLon)) * w;
  const scaleY = (lat: number) => h - ((lat - minLat) / (maxLat - minLat)) * h;

  let svg = `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">`;

  // Parcel polygon
  if (parcelGeometry?.coordinates?.[0]) {
    const points = parcelGeometry.coordinates[0]
      .map(([lon, lat]: number[]) => `${scaleX(lon)},${scaleY(lat)}`)
      .join(' ');
    svg += `<polygon points="${points}" fill="#e8f5e9" stroke="#4caf50" stroke-width="1.5" />`;
  }

  // Swaths
  for (const line of swaths) {
    if (line.length < 2) continue;
    const points = line
      .map(([lon, lat]: number[]) => `${scaleX(lon)},${scaleY(lat)}`)
      .join(' ');
    svg += `<polyline points="${points}" fill="none" stroke="#F59E0B" stroke-width="1.5" />`;
  }

  svg += '</svg>';
  return svg;
}
