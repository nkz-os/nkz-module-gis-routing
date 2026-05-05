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
  high: 'bg-nkz-text-success',
  medium: 'bg-nkz-text-accent',
  low: 'bg-nkz-text-error',
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
    <div className="p-nkz-lg max-w-2xl mx-auto space-y-nkz-stack">
      <div>
        <h2 className="text-nkz-lg font-bold text-nkz-text-primary flex items-center gap-nkz-sm">
          <Layers className="w-5 h-5 text-nkz-text-success" />
          {t('zoning.title')}
        </h2>
        <p className="text-nkz-sm text-nkz-text-secondary mt-1">{t('zoning.description')}</p>
      </div>

      {error && (
        <div className="bg-nkz-surface border border-nkz-accent rounded-nkz-md p-nkz-md text-nkz-sm text-nkz-text-error">{error}</div>
      )}

      <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-nkz-stack">
        <div>
          <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">{t('parcel.label')}</label>
          <div className="flex gap-nkz-sm">
            <input
              type="text"
              value={parcelId}
              onChange={(e) => setParcelId(e.target.value)}
              placeholder="urn:ngsi-ld:AgriParcel:..."
              className="flex-1 border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            />
            <button
              onClick={handleFetchZones}
              disabled={loading || !parcelId.trim()}
              className="px-4 py-2 bg-nkz-surface-alt text-nkz-text-primary rounded-nkz-md font-medium hover:opacity-80 disabled:opacity-50"
              title={t('zoning.refresh')}
            >
              <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
            </button>
          </div>
        </div>

        <div>
          <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">{t('zoning.numZones')}</label>
          <input
            type="number"
            min={2}
            max={10}
            value={numZones}
            onChange={(e) => setNumZones(Math.max(2, Math.min(10, parseInt(e.target.value) || 2)))}
            className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
          />
          <p className="text-nkz-xs text-nkz-text-secondary mt-1">{t('zoning.numZonesHint', { zones: numZones })}</p>
        </div>

        <button
          onClick={handleGenerate}
          disabled={generating || !parcelId.trim()}
          className="w-full flex items-center justify-center gap-nkz-sm py-3 text-nkz-text-on-accent rounded-nkz-lg font-medium disabled:opacity-50 transition-colors"
          style={{ backgroundColor: '#059669' }}
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

      <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md">
        <h3 className="text-nkz-sm font-semibold text-nkz-text-primary mb-3">
          {t('zoning.existingZones', { count: zones.length })}
        </h3>

        {zones.length === 0 ? (
          <div className="text-center py-6 text-nkz-sm text-nkz-text-secondary">
            <MapPin className="w-8 h-8 mx-auto mb-2 opacity-30" />
            <p>{t('zoning.noZones')}</p>
            <p className="text-nkz-xs mt-1">{t('zoning.noZonesHint')}</p>
          </div>
        ) : (
          <div className="space-y-nkz-stack">
            {zones.map((zone) => {
              const colorClass = ZONE_COLORS[zone.zone_class] || 'bg-nkz-text-secondary';
              return (
                <div key={zone.id} className="flex items-center justify-between bg-nkz-surface-alt rounded-nkz-md p-nkz-md text-nkz-sm">
                  <div className="flex items-center gap-nkz-md">
                    <div className={`w-4 h-4 rounded-nkz-full ${colorClass}`} />
                    <div>
                      <div className="font-medium text-nkz-text-primary">
                        {t('zoning.zoneLabel', { id: zone.zone_id })}
                      </div>
                      <div className="text-nkz-xs text-nkz-text-secondary">{zone.zone_class}</div>
                    </div>
                  </div>
                  <div className="text-right text-nkz-xs text-nkz-text-secondary">
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
