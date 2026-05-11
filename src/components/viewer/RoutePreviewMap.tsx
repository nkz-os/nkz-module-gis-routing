import React, { useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Map, ExternalLink, Layers } from 'lucide-react';

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
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: {
          geometry: result.data?.geometry,
          prescriptionMap: result.prescription_map,
        },
      }));
    }
  }, [result]);

  const openViewer = () => {
    window.open('/', '_blank');
  };

  return (
    <div className="w-full h-full flex flex-col items-center justify-center bg-slate-900 text-slate-300 p-8 gap-4">
      {generating ? (
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 border-4 border-amber-500 border-t-transparent rounded-full animate-spin" />
          <p className="text-nkz-sm text-slate-400">{t('actions.generating')}...</p>
        </div>
      ) : !parcelGeometry ? (
        <div className="flex flex-col items-center gap-3 text-center max-w-xs">
          <Map className="w-12 h-12 text-slate-600" />
          <p className="text-nkz-sm text-slate-400">{t('panels.selectParcelHint')}</p>
        </div>
      ) : result ? (
        <div className="flex flex-col items-center gap-4 text-center max-w-sm">
          <div className="flex items-center gap-2 text-nkz-text-success">
            <Layers className="w-6 h-6" />
            <span className="text-nkz-lg font-bold">
              {result.data?.properties?.swath_count ?? '-'} {t('stats.swaths').toLowerCase()}
            </span>
          </div>
          <p className="text-nkz-sm text-slate-300">
            {parcelName} — {result.data?.properties?.total_distance_m
              ? `${(result.data.properties.total_distance_m / 1000).toFixed(2)} km`
              : ''}
          </p>
          <button
            onClick={openViewer}
            className="flex items-center gap-2 px-4 py-2 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
            style={{ backgroundColor: '#CA8A04' }}
          >
            <ExternalLink className="w-4 h-4" />
            {t('panels.viewOnMap')}
          </button>
          <p className="text-nkz-xs text-slate-500">{t('panels.viewOnMapHint')}</p>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-3 text-center max-w-xs">
          <Map className="w-12 h-12 text-slate-600" />
          <p className="text-nkz-sm text-slate-300 font-semibold">{parcelName || t('parcel.label')}</p>
          <p className="text-nkz-xs text-slate-500">{t('panels.readyToGenerate')}</p>
        </div>
      )}
    </div>
  );
};
