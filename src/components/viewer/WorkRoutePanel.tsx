import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Loader2, Play } from 'lucide-react';
import { accent } from '../../config/accent';
import { api, routeOf, metricsOf } from '../../services/api';
import { EV } from './routingMode';

const NS = 'gis-routing';
const PATTERNS = ['boustrophedon', 'snake', 'spiral', 'headland-only'] as const;

interface Props { parcelId: string; }

export const WorkRoutePanel: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation(NS);
  const [equipment, setEquipment] = useState<any[]>([]);
  const [implementId, setImplementId] = useState<string>('');
  const [pattern, setPattern] = useState<string>('boustrophedon');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [metrics, setMetrics] = useState<any>(null);

  useEffect(() => {
    api.listEquipment().then((e: any[]) => {
      setEquipment(e || []);
      const impl = (e || []).find((m: any) => m.machine_role === 'implement') || (e || [])[0];
      if (impl) setImplementId(impl.id);
    }).catch(() => setEquipment([]));
  }, []);

  const generate = async () => {
    setBusy(true); setError(null); setMetrics(null);
    try {
      const geom = await api.getParcelGeometry(parcelId);
      const res = await api.generate({
        parcel_id: parcelId,
        parcel_geometry: geom.geometry,
        implement_id: implementId || null,
        pattern,
        pattern_config: { width_m: 24, overlap_pct: 10, headland_passes: 1,
                          heading_objective: 'efficiency' },
        operation_type: 'spraying',
        persist: true,
      });
      const route = routeOf(res);
      setMetrics(metricsOf(res));
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
        detail: { geometry: route, prescriptionMap: res.prescription_map || null },
      }));
    } catch (err: any) {
      setError(err?.message || t('cockpit.generateError'));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-2">
      <div>
        <label className="text-nkz-xs text-nkz-text-secondary">{t('cockpit.pattern')}</label>
        <div className="grid grid-cols-2 gap-1 mt-1">
          {PATTERNS.map(p => (
            <button key={p} onClick={() => setPattern(p)}
              className={`py-1.5 rounded-nkz-md text-nkz-xs font-medium border ${
                pattern === p ? 'border-nkz-accent bg-nkz-surface text-nkz-text-accent'
                              : 'border-nkz-default text-nkz-text-secondary'}`}>
              {t(`patternLabels.${p}`)}
            </button>
          ))}
        </div>
      </div>
      <div>
        <label className="text-nkz-xs text-nkz-text-secondary">{t('cockpit.equipment')}</label>
        <select value={implementId} onChange={e => setImplementId(e.target.value)}
          className="w-full border border-nkz-default rounded-nkz-md px-2 py-1.5 text-nkz-xs bg-nkz-surface mt-1">
          <option value="">{t('cockpit.noEquipment')}</option>
          {equipment.map((m: any) => <option key={m.id} value={m.id}>{m.name}</option>)}
        </select>
      </div>
      <button onClick={generate} disabled={busy}
        className="w-full flex items-center justify-center gap-1.5 py-2 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent disabled:opacity-50"
        style={{ backgroundColor: accent.base }}>
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
        {t('cockpit.generate')}
      </button>
      {error && <p className="text-nkz-xs text-nkz-text-error">{error}</p>}
      {metrics && (
        <div className="text-nkz-xs text-nkz-text-secondary flex gap-3">
          <span>{t('stats.fieldEfficiency')}: {(metrics.field_efficiency * 100).toFixed(0)}%</span>
          <span>{metrics.covered_area_ha?.toFixed(2)} ha</span>
        </div>
      )}
    </div>
  );
};
