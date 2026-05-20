import React, { useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Map, Loader2, Eye } from 'lucide-react';
import { accent } from '../../config/accent';

const NS = 'gis-routing';

interface Props {
  parcelGeometry: any;
  parcelName: string;
  previewResult: any;
  generating: boolean;
  onViewInCesium: () => void;
  hasSavedResult: boolean;
}

export const RoutePreviewMap: React.FC<Props> = ({
  parcelGeometry,
  parcelName,
  previewResult,
  generating,
  onViewInCesium,
  hasSavedResult,
}) => {
  const { t } = useTranslation(NS);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [selectedIndex, setSelectedIndex] = useState<number | null>(null);

  const clearHighlight = useCallback(() => setHoveredIndex(null), []);

  if (!parcelGeometry) {
    return (
      <div className="flex flex-col items-center justify-center h-full text-center px-6">
        <Map className="w-12 h-12 text-nkz-text-muted mb-3" />
        <p className="text-nkz-base font-medium text-nkz-text-secondary">
          {t('parcel.select')}
        </p>
        <p className="text-nkz-sm text-nkz-text-muted mt-1">
          {t('preview.selectParcelHint')}
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
          {t('preview.configureHint')}
        </p>
      </div>
    );
  }

  const props = previewResult.data?.properties;
  const geometry = previewResult.data?.geometry;
  const headlandCount = props?.headland_count || 0;
  const svgData = geometry ? computeSvgData(geometry, parcelGeometry, headlandCount) : null;

  return (
    <div className="flex flex-col h-full">
      {/* SVG preview */}
      {svgData && (
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
            <InteractiveSvg
              data={svgData}
              hoveredIndex={hoveredIndex}
              selectedIndex={selectedIndex}
              onHover={setHoveredIndex}
              onSelect={setSelectedIndex}
              onLeave={clearHighlight}
              swathLabel={t('preview.internalPasses')}
              headlandLabel={t('preview.headlandPasses')}
            />
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex-shrink-0 p-4 space-y-2 border-t border-nkz-default bg-nkz-surface-alt">
        {hasSavedResult && (
          <button
            onClick={onViewInCesium}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
            style={{ backgroundColor: accent.base }}
          >
            <Eye className="w-4 h-4" />
            {t('actions.viewInCesium')}
          </button>
        )}
        {hasSavedResult ? (
          <p className="text-nkz-xs text-nkz-text-secondary text-center">
            {t('preview.savedHint')}
          </p>
        ) : (
          <p className="text-nkz-xs text-nkz-text-secondary text-center">
            {t('preview.interactiveHint')}
          </p>
        )}
      </div>
    </div>
  );
};

// ---- SVG data computation ----

interface SvgLineData {
  index: number;
  points: string;
  isHeadland: boolean;
}

interface SvgRenderData {
  w: number;
  h: number;
  parcelPoints: string;
  lines: SvgLineData[];
  swathLabel: string;
  headlandLabel: string;
}

function computeSvgData(
  geometry: any,
  parcelGeometry: any,
  headlandCount: number,
): SvgRenderData | null {
  if (!geometry?.coordinates) return null;

  const allLines: number[][][] =
    geometry.type === 'MultiLineString'
      ? geometry.coordinates
      : [geometry.coordinates];

  let minLon = Infinity, maxLon = -Infinity, minLat = Infinity, maxLat = -Infinity;
  const coords: number[][][] = [...allLines];
  if (parcelGeometry?.coordinates?.[0]) {
    coords.push(parcelGeometry.coordinates[0]);
  }
  for (const line of coords) {
    for (const [lon, lat] of line) {
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  }

  const pad = 0.0002;
  minLon -= pad; maxLon += pad; minLat -= pad; maxLat += pad;
  const w = 400, h = 300;
  const scaleX = (lon: number) => ((lon - minLon) / (maxLon - minLon)) * w;
  const scaleY = (lat: number) => h - ((lat - minLat) / (maxLat - minLat)) * h;

  let parcelPoints = '';
  if (parcelGeometry?.coordinates?.[0]) {
    parcelPoints = parcelGeometry.coordinates[0]
      .map(([lon, lat]: number[]) => `${scaleX(lon)},${scaleY(lat)}`)
      .join(' ');
  }

  const lines: SvgLineData[] = allLines.map((line, i) => ({
    index: i,
    points: line.length >= 2
      ? line.map(([lon, lat]: number[]) => `${scaleX(lon)},${scaleY(lat)}`).join(' ')
      : '',
    isHeadland: i < headlandCount,
  })).filter(l => l.points);

  return {
    w, h, parcelPoints, lines,
    swathLabel: headlandCount > 0 ? 'Pasadas internas' : 'Swaths',
    headlandLabel: 'Cabeceras',
  };
}

// ---- Interactive SVG React component ----

const InteractiveSvg: React.FC<{
  data: SvgRenderData;
  hoveredIndex: number | null;
  selectedIndex: number | null;
  onHover: (i: number | null) => void;
  onSelect: (i: number) => void;
  onLeave: () => void;
  swathLabel: string;
  headlandLabel: string;
}> = ({ data, hoveredIndex, selectedIndex, onHover, onSelect, onLeave, swathLabel, headlandLabel }) => {
  return (
    <svg
      width={data.w}
      height={data.h}
      viewBox={`0 0 ${data.w} ${data.h}`}
      xmlns="http://www.w3.org/2000/svg"
      className="max-w-full max-h-full"
      onMouseLeave={onLeave}
    >
      {/* Parcel polygon */}
      {data.parcelPoints && (
        <polygon
          points={data.parcelPoints}
          fill="#e8f5e9"
          stroke="#4caf50"
          strokeWidth="1.5"
        />
      )}

      {/* Lines */}
      {data.lines.map(line => {
        const isHighlighted = hoveredIndex === line.index || selectedIndex === line.index;
        const isDimmed = (hoveredIndex !== null || selectedIndex !== null) && !isHighlighted;

        let stroke = line.isHeadland ? '#0891B2' : '#F59E0B';  // cyan for headland, amber for swaths
        let strokeWidth = 1.5;
        let opacity = 1;

        if (isHighlighted) {
          stroke = line.isHeadland ? '#06B6D4' : '#D97706';
          strokeWidth = 3;
        }
        if (isDimmed) {
          opacity = 0.2;
        }

        return (
          <polyline
            key={line.index}
            points={line.points}
            fill="none"
            stroke={stroke}
            strokeWidth={strokeWidth}
            opacity={opacity}
            style={{ cursor: 'pointer', transition: 'stroke-width 0.15s, opacity 0.15s' }}
            onMouseEnter={() => onHover(line.index)}
            onMouseLeave={() => onHover(null)}
            onClick={() => onSelect(line.index)}
          />
        );
      })}

      {/* Legend */}
      <g transform={`translate(${data.w - 120}, 10)`}>
        <rect x="0" y="0" width="112" height="36" rx="4" fill="white" fillOpacity="0.85" stroke="#e5e7eb" />
        {data.lines.some(l => l.isHeadland) && (
          <>
            <line x1="8" y1="14" x2="30" y2="14" stroke="#0891B2" strokeWidth="2" />
            <text x="35" y="18" fontSize="9" fill="#6b7280">{headlandLabel}</text>
          </>
        )}
        <line x1="8" y1="26" x2="30" y2="26" stroke="#F59E0B" strokeWidth="2" />
        <text x="35" y="30" fontSize="9" fill="#6b7280">{swathLabel}</text>
      </g>
    </svg>
  );
};
