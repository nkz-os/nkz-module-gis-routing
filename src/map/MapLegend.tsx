import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { gateDataUrl, marginSwatchDataUrl, nogoSwatchDataUrl } from './markers';

const NS = 'gis-routing';

/** Small key to the gate and NO-GO drawing, shared by the Work, Transit and 3D maps. */
export const MapLegend: React.FC<{ margin?: boolean; className?: string; style?: React.CSSProperties }> = ({
  margin = false, className = 'absolute top-2 left-2 z-10', style,
}) => {
  const { t } = useTranslation(NS);
  const rows: { src: string; label: string }[] = [
    { src: gateDataUrl(), label: t('map.legend.gate') },
    { src: nogoSwatchDataUrl(), label: t('map.legend.nogo') },
    ...(margin ? [{ src: marginSwatchDataUrl(), label: t('map.legend.margin') }] : []),
  ];
  return (
    <ul
      data-testid="map-legend"
      style={style}
      className={`${className} flex flex-col gap-1 rounded-nkz-md bg-nkz-surface/90 px-2 py-1 text-nkz-xs text-nkz-text-primary shadow`}
    >
      {rows.map((r) => (
        <li key={r.label} className="flex items-center gap-2">
          <img src={r.src} alt="" width={20} height={14} className="h-4 w-6 object-contain" />
          <span>{r.label}</span>
        </li>
      ))}
    </ul>
  );
};
