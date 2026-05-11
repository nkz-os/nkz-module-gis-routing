/**
 * ZoningTab — VRA Management Zones.
 *
 * Fetches zones from Orion-LD via our own backend (/zones/{parcel_id}).
 * Zone generation is proxied through our backend to vegetation-health
 * (server-to-server, no direct frontend dependency).
 */
import React, { useState, useCallback, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Layers, RefreshCw, Loader2, MapPin, AlertCircle } from 'lucide-react';
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

interface ParcelOption {
  id: string;
  name: string;
  area?: number;
}

const ZONE_COLORS: Record<string, string> = {
  high: 'bg-nkz-text-success',
  medium: 'bg-nkz-text-accent',
  low: 'bg-nkz-text-error',
};

const ZoningTab: React.FC = () => {
  const { t } = useTranslation(NS);
  const [parcels, setParcels] = useState<ParcelOption[]>([]);
  const [parcelsLoading, setParcelsLoading] = useState(true);
  const [parcelsError, setParcelsError] = useState<string | null>(null);
  const [parcelId, setParcelId] = useState<string>('');
  const [manualUrn, setManualUrn] = useState<string>('');
  const [zones, setZones] = useState<ZoneData[]>([]);
  const [loading, setLoading] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [numZones, setNumZones] = useState(3);
  const [error, setError] = useState<string | null>(null);
  const [pollState, setPollState] = useState<'idle' | 'queued' | 'polling' | 'done' | 'timeout'>('idle');
  const [pollAttempt, setPollAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setParcelsLoading(true);
      setParcelsError(null);
      try {
        const data = await api.listParcels();
        if (!cancelled) setParcels(data || []);
      } catch (err: any) {
        if (!cancelled) setParcelsError(err?.message || t('errors.generateFailed'));
      } finally {
        if (!cancelled) setParcelsLoading(false);
      }
    }
    load();
    return () => {
      cancelled = true;
    };
  }, [t]);

  const targetParcelId = manualUrn.trim() || parcelId;

  const handleFetchZones = useCallback(async () => {
    if (!targetParcelId.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result: any = await api.getVRAZones(targetParcelId);
      if (result?.data?.zones) {
        setZones(result.data.zones);
      }
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setLoading(false);
    }
  }, [targetParcelId, t]);

  const handleGenerate = useCallback(async () => {
    if (!targetParcelId.trim()) return;
    setGenerating(true);
    setError(null);
    setPollState('queued');
    setPollAttempt(0);
    try {
      // Trigger zone generation via the standard generate endpoint
      const genResult: any = await api.generate({
        parcel_id: targetParcelId,
        vra_enabled: true,
        external_zone_feature: undefined,
        zone_ids: [],
      });
      if (genResult?.data?.properties?.operation_id) {
        // Wait for zones to be available
        let attempts = 0;
        const poll = async () => {
          attempts++;
          setPollState('polling');
          setPollAttempt(attempts);
          try {
            const result: any = await api.getVRAZones(targetParcelId);
            if (result?.data?.zones?.length > 0) {
              setZones(result.data.zones);
              setPollState('done');
              return;
            }
          } catch {
            /* polling gracefully stops on error */
          }
          if (attempts < 15) {
            setTimeout(poll, 2000);
          } else {
            setPollState('timeout');
          }
        };
        setTimeout(poll, 2000);
      } else {
        // Fallback: just fetch existing zones
        const result: any = await api.getVRAZones(targetParcelId);
        if (result?.data?.zones) {
          setZones(result.data.zones);
        }
        setPollState('done');
      }
    } catch (err: any) {
      setError(err?.message || t('zoning.generateError'));
      setPollState('idle');
    } finally {
      setGenerating(false);
    }
  }, [targetParcelId, numZones, t]);

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
          {parcelsLoading ? (
            <p className="text-nkz-xs text-nkz-text-secondary flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              {t('loading')}
            </p>
          ) : parcelsError ? (
            <p className="text-nkz-xs text-nkz-text-error flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {parcelsError}
            </p>
          ) : (
            <select
              value={parcelId}
              onChange={(e) => {
                setParcelId(e.target.value);
                setManualUrn('');
              }}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            >
              <option value="">{t('parcel.select')}</option>
              {parcels.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}{typeof p.area === 'number' ? ` (${p.area.toFixed(1)} ha)` : ''}
                </option>
              ))}
            </select>
          )}
          <div className="mt-2">
            <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
              {t('zoning.manualUrnLabel')}
            </label>
            <input
              type="text"
              value={manualUrn}
              onChange={(e) => setManualUrn(e.target.value)}
              placeholder={t('zoning.manualUrnPlaceholder')}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            />
            <p className="text-nkz-xs text-nkz-text-secondary mt-1">{t('zoning.manualUrnHint')}</p>
          </div>
          <div className="flex justify-end mt-2">
            <button
              type="button"
              onClick={handleFetchZones}
              disabled={loading || !targetParcelId.trim()}
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
          disabled={generating || !targetParcelId.trim()}
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

        {pollState !== 'idle' && (
          <p className="text-nkz-xs text-nkz-text-secondary">
            {pollState === 'queued' && t('zoning.jobQueued')}
            {pollState === 'polling' && t('zoning.jobPolling', { attempt: pollAttempt, max: 15 })}
            {pollState === 'done' && t('zoning.jobDone')}
            {pollState === 'timeout' && t('zoning.jobTimeout')}
          </p>
        )}
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
