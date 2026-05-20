import React, { useMemo } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Map, Loader2, Eye, Save } from 'lucide-react';
import { accent } from '../../config/accent';

const NS = 'gis-routing';

interface Props {
  parcelGeometry: any;
  parcelName: string;
  previewResult: any;
  generating: boolean;
  onSave: () => void;
  onViewInCesium: () => void;
  hasSavedResult: boolean;
}

export const RoutePreviewMap: React.FC<Props> = ({
  parcelGeometry,
  parcelName,
  previewResult,
  generating,
  onSave,
  onViewInCesium,
  hasSavedResult,
}) => {
  const { t } = useTranslation(NS);

  const svgContent = useMemo(() => {
    if (!previewResult?.data?.geometry) return null;
    return renderRouteSvg(previewResult.data.geometry, parcelGeometry);
  }, [previewResult, parcelGeometry]);

  if (!parcelGeometry) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <Map className="w-12 h-12 text-nkz-text-muted mb-3" />
        <p className="text-nkz-base font-medium text-nkz-text-secondary">
          {t('parcel.select')}
        </p>
        <p className="text-nkz-sm text-nkz-text-muted mt-1">
          Selecciona una parcela en el panel izquierdo para comenzar
        </p>
      </div>
    );
  }

  if (generating) {
    return (
      <div className="flex flex-col items-center justify-center h-full gap-3">
        <Loader2 className="w-8 h-8 animate-spin" style={{ color: accent.base }} />
        <p className="text-nkz-base text-nkz-text-secondary">
          {t('actions.generating')}...
        </p>
      </div>
    );
  }

  if (!previewResult) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <Map className="w-10 h-10 text-nkz-text-muted mb-2" />
        <p className="text-nkz-base text-nkz-text-secondary">
          {parcelName || t('parcel.select')}
        </p>
        <p className="text-nkz-sm text-nkz-text-muted mt-1">
          Configura el patrón para ver la previsualización
        </p>
      </div>
    );
  }

  const props = previewResult.data?.properties;

  return (
    <div className="flex flex-col h-full">
      {/* SVG preview */}
      {svgContent && (
        <div className="flex-1 flex flex-col min-h-0">
          <div className="px-4 py-2 border-b border-nkz-default flex items-center justify-between bg-nkz-surface-alt flex-shrink-0">
            <span className="text-nkz-sm font-semibold text-nkz-text-secondary">
              {parcelName || 'Parcela'} — {props?.swath_count ?? '-'} {t('stats.swaths').toLowerCase()}
            </span>
            <span className="text-nkz-sm text-nkz-text-secondary">
              {props?.total_distance_m
                ? `${(props.total_distance_m / 1000).toFixed(2)} km`
                : ''}
            </span>
          </div>
          <div className="flex-1 flex items-center justify-center p-4 bg-white overflow-auto min-h-0">
            <div
              className="max-w-full max-h-full"
              dangerouslySetInnerHTML={{ __html: svgContent }}
            />
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex-shrink-0 p-4 space-y-2 border-t border-nkz-default bg-nkz-surface-alt">
        <div className="flex gap-2">
          <button
            onClick={onSave}
            className="flex-1 flex items-center justify-center gap-2 py-2.5 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
            style={{ backgroundColor: accent.base }}
          >
            <Save className="w-4 h-4" />
            {t('actions.save')}
          </button>
          {hasSavedResult && (
            <button
              onClick={onViewInCesium}
              className="flex items-center justify-center gap-2 py-2.5 px-4 rounded-nkz-md text-nkz-sm font-semibold border border-nkz-accent text-nkz-text-accent hover:bg-nkz-surface transition-colors"
            >
              <Eye className="w-4 h-4" />
              Cesium
            </button>
          )}
        </div>
        {hasSavedResult && (
          <p className="text-nkz-xs text-nkz-text-secondary text-center">
            Ruta guardada. Ve al visor unificado para verla en el mapa 3D.
          </p>
        )}
        {!hasSavedResult && (
          <p className="text-nkz-xs text-nkz-text-secondary text-center">
            La previsualización no se guarda hasta que pulses Guardar.
          </p>
        )}
      </div>
    </div>
  );
};

function renderRouteSvg(geometry: any, parcelGeometry?: any): string | null {
  if (!geometry?.coordinates) return null;

  const swaths: number[][][] =
    geometry.type === 'MultiLineString'
      ? geometry.coordinates
      : [geometry.coordinates];

  let minLon = Infinity,
    maxLon = -Infinity,
    minLat = Infinity,
    maxLat = -Infinity;
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
  minLon -= pad;
  maxLon += pad;
  minLat -= pad;
  maxLat += pad;
  const w = 400;
  const h = 300;
  const scaleX = (lon: number) => ((lon - minLon) / (maxLon - minLon)) * w;
  const scaleY = (lat: number) => h - ((lat - minLat) / (maxLat - minLat)) * h;

  let svg = `<svg width="${w}" height="${h}" xmlns="http://www.w3.org/2000/svg">`;

  if (parcelGeometry?.coordinates?.[0]) {
    const points = parcelGeometry.coordinates[0]
      .map(([lon, lat]: number[]) => `${scaleX(lon)},${scaleY(lat)}`)
      .join(' ');
    svg += `<polygon points="${points}" fill="#e8f5e9" stroke="#4caf50" stroke-width="1.5" />`;
  }

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
