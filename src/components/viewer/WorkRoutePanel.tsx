import React, { useEffect, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Loader2, Play, Save } from 'lucide-react';
import { GenerateProgress } from '../work/GenerateProgress';
import { api, ApiError, type AlertStatus, type GenerateRequest, type GenerateResponse } from '../../services/api';
import { EV } from './routingMode';
import { Button, Select } from '@nekazari/ui-kit';

const NS = 'gis-routing';
const PATTERNS = ['boustrophedon', 'snake', 'spiral', 'headland-only'] as const;

interface Props { parcelId: string; }

const num = (v: unknown): number | null => {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(String(v).replace(',', '.'));
  return Number.isFinite(n) && n > 0 ? n : null;
};

export const WorkRoutePanel: React.FC<Props> = ({ parcelId }) => {
  const { t } = useTranslation(NS);
  const [equipment, setEquipment] = useState<any[]>([]);
  const [implementId, setImplementId] = useState<string>('');
  const [pattern, setPattern] = useState<string>('boustrophedon');
  // Typed as text so a half-typed number is not rewritten under the cursor.
  const [widthText, setWidthText] = useState('');
  const [radiusText, setRadiusText] = useState('');
  const [busy, setBusy] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<GenerateResponse | null>(null);
  const [saved, setSaved] = useState<{ operationId: string; alert?: AlertStatus } | null>(null);

  const applyMachine = (list: any[], id: string) => {
    const m = list.find((x) => x.id === id);
    const w = num(m?.implementWidth);
    const r = num(m?.minTurningRadius);
    setWidthText(w === null ? '' : String(w));
    setRadiusText(r === null ? '' : String(r));
  };

  useEffect(() => {
    api.listEquipment().then((e: any[]) => {
      const list = e || [];
      setEquipment(list);
      const impl = list.find((m: any) => m.machine_role === 'implement') || list[0];
      if (impl) { setImplementId(impl.id); applyMachine(list, impl.id); }
    }).catch(() => setEquipment([]));
  }, []);

  const message = (err: unknown): string => {
    if (err instanceof ApiError) {
      const code = err.code || 'UNKNOWN';
      return t(`work.errors.${code}`, { ...err.params, detail: err.detail, defaultValue: '' })
        || t('work.errors.UNKNOWN', { detail: err.detail });
    }
    return t('cockpit.generateError');
  };

  const onMachine = (id: string) => { setImplementId(id); applyMachine(equipment, id); };

  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => { abortRef.current?.abort(); }, [parcelId]);

  const generate = async () => {
    abortRef.current?.abort();   // a new run supersedes the one in flight
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const { signal } = ctrl;
    setError(null); setResult(null); setSaved(null);
    const widthM = num(widthText);
    if (widthM === null) { setError(t('work.errors.MACHINE_WIDTH_MISSING')); return; }
    const radiusM = num(radiusText);
    setBusy(true);
    try {
      const geom = await api.getParcelGeometry(parcelId);
      if (signal.aborted) return;
      const res = await api.generate({
        parcel_id: parcelId,
        parcel_geometry: geom.geometry,
        tractor_id: null,
        implement_id: implementId || null,
        pattern: pattern as GenerateRequest['pattern'],
        pattern_config: {
          width_m: widthM, overlap_pct: 10, headland_passes: 1, heading_objective: 'efficiency',
          ...(radiusM !== null ? { turning_radius_m: radiusM } : {}),
        },
        operation_type: 'spraying',
        return_to_access: false,
        persist: false,
      }, { signal });
      if (signal.aborted) return;
      setResult(res);
      if (res.plan_id === null) setError(t('work.errors.PLAN_TOO_LARGE_TO_SAVE'));
      // Preview only: the plan is not an operation until the user saves it.
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
        detail: { geometry: res.plan.route, prescriptionMap: null },
      }));
    } catch (err) {
      if (signal.aborted) return;
      setError(message(err));
    } finally {
      if (!signal.aborted) setBusy(false);
    }
  };

  const save = async () => {
    if (!result?.plan_id) return;
    setSaving(true); setError(null);
    try {
      const res = await api.saveOperation({ kind: 'plan', plan_id: result.plan_id });
      if (!res.persisted || !res.operation_id) {
        throw new ApiError(502, { code: 'PERSIST_FAILED', detail: 'Plan was not persisted' });
      }
      setSaved({ operationId: res.operation_id, alert: res.alert });
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
        detail: { geometry: result.plan.route, prescriptionMap: null, operation_id: res.operation_id },
      }));
    } catch (err) {
      setError(message(err));
    } finally {
      setSaving(false);
    }
  };

  const metrics = result?.plan.metrics;
  const missing = num(widthText) === null || num(radiusText) === null;

  return (
    <div className="space-y-2">
      <div>
        <label className="text-nkz-xs text-nkz-text-secondary">{t('cockpit.pattern')}</label>
        <div className="grid grid-cols-2 gap-1 mt-1">
          {PATTERNS.map(p => (
            <Button variant="ghost" key={p} onClick={() => setPattern(p)}
              className={`py-1.5 rounded-nkz-md text-nkz-xs font-medium border ${
                pattern === p ? 'border-nkz-accent-base bg-nkz-surface text-nkz-accent-base'
                              : 'border-nkz-border text-nkz-text-secondary'}`}>
              {t(`patternLabels.${p}`)}
            </Button>
          ))}
        </div>
      </div>
      <div>
        <label className="text-nkz-xs text-nkz-text-secondary">{t('cockpit.equipment')}</label>
        <Select
          value={implementId}
          onValueChange={onMachine}
          options={[
            { value: '', label: t('cockpit.noEquipment') },
            ...equipment.map((m: any) => ({ value: m.id, label: m.name }))
          ]}
          className="w-full mt-1"
        />
      </div>
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label htmlFor="cockpit-width" className="text-nkz-xs text-nkz-text-secondary">{t('work.machine.width')}</label>
          <input id="cockpit-width" inputMode="decimal" value={widthText}
            onChange={(e) => setWidthText(e.target.value)}
            className="w-full mt-1 px-2 py-1 rounded-nkz-md border border-nkz-border bg-nkz-surface text-nkz-sm text-nkz-text-primary" />
        </div>
        <div>
          <label htmlFor="cockpit-radius" className="text-nkz-xs text-nkz-text-secondary">{t('work.machine.radius')}</label>
          <input id="cockpit-radius" inputMode="decimal" value={radiusText}
            onChange={(e) => setRadiusText(e.target.value)}
            className="w-full mt-1 px-2 py-1 rounded-nkz-md border border-nkz-border bg-nkz-surface text-nkz-sm text-nkz-text-primary" />
        </div>
      </div>
      {missing && <p className="text-nkz-xs text-nkz-text-secondary">{t('cockpit.typeManually')}</p>}
      <Button onClick={generate} disabled={busy || saving}
        className="w-full flex items-center justify-center gap-1.5 py-2">
        {busy ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
        {t('cockpit.generate')}
      </Button>
      {busy && <GenerateProgress />}
      {error && <p className="text-nkz-xs text-nkz-danger">{error}</p>}
      {metrics && (
        <div className="text-nkz-xs text-nkz-text-secondary flex gap-3">
          <span>{t('stats.fieldEfficiency')}: {(metrics.field_efficiency * 100).toFixed(0)}%</span>
          <span>{metrics.covered_area_ha?.toFixed(2)} ha</span>
        </div>
      )}
      {result?.plan_id && !saved && (
        <Button onClick={save} disabled={saving || busy}
          className="w-full flex items-center justify-center gap-1.5 py-2">
          {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
          {t(saving ? 'actions.saving' : 'actions.save')}
        </Button>
      )}
      {saved && (
        <div className="text-nkz-xs text-nkz-success space-y-1">
          <p>{t('cockpit.saved')}</p>
          {saved.alert && <p className="text-nkz-text-secondary">{t(`work.alert.${saved.alert}`)}</p>}
        </div>
      )}
    </div>
  );
};
