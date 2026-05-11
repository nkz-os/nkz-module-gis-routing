import React, { useState, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Layers, Loader2, ChevronDown } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props {
  enabled: boolean;
  source: string;
  baseRate: number;
  rateUnit: string;
  zoneIds: string[];
  parcelId: string | null;
  onEnabledChange: (v: boolean) => void;
  onSourceChange: (s: any) => void;
  onBaseRateChange: (r: number) => void;
  onZoneIdsChange: (ids: string[]) => void;
  onExternalFileChange: (f: any) => void;
}

export const StepVRA: React.FC<Props> = ({
  enabled, source, baseRate, zoneIds, parcelId,
  onEnabledChange, onSourceChange, onBaseRateChange, onZoneIdsChange,
}) => {
  const { t } = useTranslation(NS);
  const [expanded, setExpanded] = useState(false);
  const [zones, setZones] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!enabled || !parcelId) { setZones([]); return; }
    let cancelled = false;
    setLoading(true);
    api.getVRAZones(parcelId)
      .then(d => {
        if (!cancelled) {
          const z = d?.data?.zones || [];
          setZones(z);
          if (z.length > 0 && zoneIds.length === 0) onZoneIdsChange(z.map((z: any) => z.id));
        }
      })
      .catch(() => { if (!cancelled) setZones([]); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [enabled, parcelId]);

  return (
    <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-nkz-md py-3 text-nkz-sm font-semibold">
        <span className="flex items-center gap-nkz-sm">
          <span className="w-6 h-6 rounded-full bg-nkz-text-accent text-white text-nkz-xs flex items-center justify-center">4</span>
          <Layers className="w-4 h-4 text-nkz-text-accent" />
          {t('vra.enabled')}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="px-nkz-md pb-3 space-y-2">
          <label className="flex items-center gap-2 cursor-pointer">
            <input type="checkbox" checked={enabled} onChange={e => onEnabledChange(e.target.checked)}
              className="rounded-nkz-md border-nkz-default text-nkz-text-accent" />
            <span className="text-nkz-xs text-nkz-text-primary">{t('vra.enabled')}</span>
          </label>

          {enabled && (
            <>
              <select value={source} onChange={e => onSourceChange(e.target.value)}
                className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface">
                <option value="vegetation-health">Vegetation Health</option>
                <option value="orion">Orion-LD</option>
                <option value="external">External file</option>
              </select>

              <div>
                <label className="text-nkz-xs text-nkz-text-secondary">{t('vra.baseRate')}</label>
                <input type="number" min={0} value={baseRate}
                  onChange={e => onBaseRateChange(Number(e.target.value))}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-1.5 text-nkz-sm bg-nkz-surface" />
              </div>

              {loading ? <Loader2 className="w-3 h-3 animate-spin" /> : zones.length > 0 ? (
                <div className="space-y-1 max-h-32 overflow-auto">
                  {zones.map(z => (
                    <label key={z.id} className="flex items-center gap-2 text-nkz-xs">
                      <input type="checkbox" checked={zoneIds.includes(z.id)}
                        onChange={e => {
                          onZoneIdsChange(e.target.checked ? [...zoneIds, z.id] : zoneIds.filter(id => id !== z.id));
                        }}
                        className="rounded-nkz-md border-nkz-default text-nkz-text-accent" />
                      <span>{t('zoning.zoneLabel', { id: z.zone_id || z.id })}</span>
                      <span className="text-nkz-text-secondary ml-auto">{z.prescription_rate?.toFixed(2)}x</span>
                    </label>
                  ))}
                </div>
              ) : <p className="text-nkz-xs text-nkz-text-secondary">{t('vra.noZonesForParcel')}</p>}
            </>
          )}
        </div>
      )}
    </div>
  );
};
