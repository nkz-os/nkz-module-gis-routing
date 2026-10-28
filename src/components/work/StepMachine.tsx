import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Input, Select, Slider, Spinner } from '@nekazari/ui-kit';
import { api } from '../../services/api';
import type { MachineConfig } from '../../state/workMachine';
import type { StepProps } from './StepList';

const NS = 'gis-routing';
const OPERATIONS = ['spraying', 'fertilizing', 'seeding', 'tillage'] as const;

const num = (v: unknown): number | null => {
  const n = v === null || v === undefined || v === '' ? NaN : Number(v);
  return Number.isFinite(n) && n > 0 ? n : null;
};

// Keeps the typed text locally so partial input ("0.", "0.5") is never rewritten;
// the draft only follows the state when the value changes from outside (prefill).
const NumberField: React.FC<{ value: number | null; onValue: (v: number | null) => void }> = ({ value, onValue }) => {
  const [draft, setDraft] = useState<string>(value === null ? '' : String(value));
  useEffect(() => {
    if (num(draft) !== value) setDraft(value === null ? '' : String(value));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);
  return (
    <Input
      type="number" min={0.1} step={0.1}
      value={draft}
      onChange={(e) => { setDraft(e.target.value); onValue(num(e.target.value)); }}
      className="w-full mt-1"
    />
  );
};

export const StepMachine: React.FC<StepProps> = ({ state, dispatch }) => {
  const { t } = useTranslation(NS);
  const [equipment, setEquipment] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const m = state.machine;

  useEffect(() => {
    let cancelled = false;
    api.listEquipment()
      .then((d) => { if (!cancelled) setEquipment(d || []); })
      .catch(() => { /* list stays empty; fields remain editable by hand */ })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Implement preferred, then tractor (matches backend _resolve_machine).
  const resolve = (list: any[], implementId: string | null, tractorId: string | null) => {
    const sel = list.find((e) => e.id === implementId) || list.find((e) => e.id === tractorId);
    return { widthM: num(sel?.implementWidth), turningRadiusM: num(sel?.minTurningRadius) };
  };

  const prefill = (r: { widthM: number | null; turningRadiusM: number | null }, onlyEmpty: boolean): Partial<MachineConfig> => {
    const out: Partial<MachineConfig> = {};
    if (r.widthM !== null) {
      if (!onlyEmpty || m.widthM === null) { out.widthM = r.widthM; out.widthSource = 'machine'; }
    } else if (!onlyEmpty && m.widthSource === 'machine') {
      out.widthM = null; out.widthSource = null;
    }
    if (r.turningRadiusM !== null) {
      if (!onlyEmpty || m.turningRadiusM === null) { out.turningRadiusM = r.turningRadiusM; out.radiusSource = 'machine'; }
    } else if (!onlyEmpty && m.radiusSource === 'machine') {
      out.turningRadiusM = null; out.radiusSource = null;
    }
    return out;
  };

  // Equipment arrives after a restored selection: fill only what is still empty.
  useEffect(() => {
    if (equipment.length === 0 || (!m.implementId && !m.tractorId)) return;
    const patch = prefill(resolve(equipment, m.implementId, m.tractorId), true);
    if (Object.keys(patch).length > 0) dispatch({ type: 'MACHINE_CHANGED', machine: patch });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [equipment]);

  const pick = (kind: 'implement' | 'tractor', id: string) => {
    const next = id || null;
    const implementId = kind === 'implement' ? next : m.implementId;
    const tractorId = kind === 'tractor' ? next : m.tractorId;
    const patch = prefill(resolve(equipment, implementId, tractorId), false);
    dispatch({
      type: 'MACHINE_CHANGED',
      machine: kind === 'implement' ? { implementId: next, ...patch } : { tractorId: next, ...patch },
    });
  };

  const tractors = equipment.filter((e) => (e.category || '').toLowerCase() === 'tractor');
  const implementsList = equipment.filter((e) => (e.category || '').toLowerCase() === 'implement');
  const source = (s: 'machine' | 'manual' | null) =>
    s === null ? null : (
      <Badge intent={s === 'machine' ? 'positive' : 'default'}>
        {s === 'machine' ? t('work.machine.fromMachine') : t('work.machine.manual')}
      </Badge>
    );
  const effective = m.widthM !== null && m.widthM > 0
    ? Math.round(m.widthM * (1 - m.overlapPct / 100) * 100) / 100
    : null;

  if (loading) return <Spinner />;

  return (
    <div className="space-y-3">
      <div>
        <label className="text-nkz-sm text-nkz-text-secondary">{t('parameters.operationType')}</label>
        <Select
          value={m.operationType}
          onValueChange={(v) => dispatch({ type: 'MACHINE_CHANGED', machine: { operationType: v } })}
          options={OPERATIONS.map((o) => ({ value: o, label: t(`operationType.${o}`) }))}
          className="w-full mt-1"
        />
      </div>
      <div>
        <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.tractorLabel')}</label>
        <Select
          value={m.tractorId ?? ''}
          onValueChange={(v) => pick('tractor', v)}
          options={[{ value: '', label: t('equipment.selectTractor') }, ...tractors.map((e) => ({ value: e.id, label: e.name }))]}
          placeholder={t('equipment.selectTractor')}
          className="w-full mt-1"
        />
      </div>
      <div>
        <label className="text-nkz-sm text-nkz-text-secondary">{t('equipment.implementLabel')}</label>
        <Select
          value={m.implementId ?? ''}
          onValueChange={(v) => pick('implement', v)}
          options={[{ value: '', label: t('equipment.selectImplement') }, ...implementsList.map((e) => ({ value: e.id, label: e.name }))]}
          placeholder={t('equipment.selectImplement')}
          className="w-full mt-1"
        />
      </div>
      <div>
        <div className="flex items-center justify-between">
          <label className="text-nkz-sm text-nkz-text-secondary">{t('work.machine.width')}</label>
          {source(m.widthSource)}
        </div>
        <NumberField value={m.widthM} onValue={(v) => dispatch({ type: 'MACHINE_CHANGED', machine: { widthM: v, widthSource: 'manual' } })} />
      </div>
      <div>
        <div className="flex items-center justify-between">
          <label className="text-nkz-sm text-nkz-text-secondary">{t('work.machine.radius')}</label>
          {source(m.radiusSource)}
        </div>
        <NumberField value={m.turningRadiusM} onValue={(v) => dispatch({ type: 'MACHINE_CHANGED', machine: { turningRadiusM: v, radiusSource: 'manual' } })} />
      </div>
      <Slider
        label={t('work.machine.overlap')}
        unit="%"
        min={0} max={30} step={1}
        value={m.overlapPct}
        onChange={(v) => dispatch({ type: 'MACHINE_CHANGED', machine: { overlapPct: v } })}
      />
      {effective !== null && (
        <p className="text-nkz-sm text-nkz-text-secondary">{t('work.machine.effectiveWidth', { w: effective })}</p>
      )}
    </div>
  );
};
