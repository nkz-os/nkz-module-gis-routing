/**
 * ZoningTab — VRA Management Zones.
 *
 * Fetches zones from Orion-LD via our own backend (/zones/{parcel_id}).
 * Zone generation is proxied through our backend to vegetation-health
 * (server-to-server, no direct frontend dependency).
 */
import React, { useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Layers, RefreshCw, Loader2, MapPin } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface ZoneData {
  id: string;
  zone_id: number | string;
  zone_class: string;
  prescription_rate: number;
  mean_value: number;
  area_ha: number;
  geometry: any;
}

const ZONE_COLORS: Record<string, string> = {
  high: 'bg-emerald-500',
  medium: 'bg-yellow-500',
  low: 'bg-red-500',
};

const ZoningTab: React.FC = () => {
  const { t } = useTranslation(NS);
  const [parcelId, setParcelId] = useState<string>('');
  const [zones, setZones] = useState<ZoneData[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [numZones, setNumZones] = useState(3);
  const [error, setError] = useState<string | null>(null);

  const handleFetchZones = useCallback(async () => {
    if (!parcelId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result: any = await api.getZones(parcelId);
      if (result?.data?.zones) {
        setZones(result.data.zones);
      }
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setLoading(false);
    }
  }, [parcelId, t]);

  const handleGenerate = useCallback(async () => {
    if (!parcelId.trim()) return;
    setGenerating(true);
    setError(null);
    try {
      await api.generateZones(parcelId, numZones);
      // Poll for result after generation
      let attempts = 0;
      const poll = async () => {
        attempts++;
        const result: any = await api.getZones(parcelId);
        if (result?.data?.zones?.length > 0) {
          setZones(result.data.zones);
          return;
        }
        if (attempts < 15) setTimeout(poll, 2000);
      };
      setTimeout(poll, 2000);
    } catch (err: any) {
      setError(err?.message || t('zoning.generateError'));
    } finally {
      setGenerating(false);
    }
  }, [parcelId, numZones, t]);

  return (
    <div className="p-4 max-w-2xl mx-auto space-y-6">
      <div>
        <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
          <Layers className="w-5 h-5 text-emerald-500" />
          {t('zoning.title')}
        </h2>
        <p className="text-sm text-slate-500 mt-1">{t('zoning.description')}</p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">{error}</div>
      )}

      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-4">
        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">{t('parcel.label')}</label>
          <div className="flex gap-2">
            <input
              type="text"
              value={parcelId}
              onChange={(e) => setParcelId(e.target.value)}
              placeholder="urn:ngsi-ld:AgriParcel:..."
              className="flex-1 border border-slate-300 rounded px-3 py-2 text-sm"
            />
            <button
              onClick={handleFetchZones}
              disabled={loading || !parcelId.trim()}
              className="px-4 py-2 bg-slate-100 text-slate-700 rounded font-medium hover:bg-slate-200 disabled:opacity-50"
              title={t('zoning.refresh')}
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        <div>
          <label className="block text-xs font-medium text-slate-600 mb-1">{t('zoning.numZones')}</label>
          <input
            type="number"
            min={2}
            max={10}
            value={numZones}
            onChange={(e) => setNumZones(Math.max(2, Math.min(10, parseInt(e.target.value) || 2)))}
            className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
          />
          <p className="text-xs text-slate-400 mt-1">{t('zoning.numZonesHint', { zones: numZones })}</p>
        </div>

        <button
          onClick={handleGenerate}
          disabled={generating || !parcelId.trim()}
          className="w-full flex items-center justify-center gap-2 py-3 bg-emerald-600 text-white rounded-lg font-medium hover:bg-emerald-700 disabled:bg-slate-300 disabled:cursor-wait transition-colors"
        >
          {generating ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('zoning.generating')}
            </>
          ) : (
            t('zoning.generateBtn')
          )}
        </button>
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <h3 className="text-sm font-semibold text-slate-700 mb-3">
          {t('zoning.existingZones', { count: zones.length })}
        </h3>

        {zones.length === 0 ? (
          <div className="text-center py-6 text-sm text-slate-400">
            <MapPin className="w-8 h-8 mx-auto mb-2 text-slate-300" />
            <p>{t('zoning.noZones')}</p>
            <p className="text-xs mt-1">{t('zoning.noZonesHint')}</p>
          </div>
        ) : (
          <div className="space-y-2">
            {zones.map((zone) => {
              const colorClass = ZONE_COLORS[zone.zone_class] || 'bg-slate-400';
              return (
                <div key={zone.id} className="flex items-center justify-between bg-slate-50 rounded p-3 text-sm">
                  <div className="flex items-center gap-3">
                    <div className={`w-4 h-4 rounded ${colorClass}`} />
                    <div>
                      <div className="font-medium text-slate-700">
                        {t('zoning.zoneLabel', { id: zone.zone_id })}
                      </div>
                      <div className="text-xs text-slate-500">{zone.zone_class}</div>
                    </div>
                  </div>
                  <div className="text-right text-xs text-slate-500">
                    <div>{zone.mean_value?.toFixed(3) || '-'}</div>
                    <div>{zone.area_ha?.toFixed(1) || '-'} ha</div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
};

export default ZoningTab;
