import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Badge, Button, Select } from '@nekazari/ui-kit';
import { canGenerate, type WorkEvent, type WorkState } from '../../state/workMachine';
import type { Plan } from '../../services/api';
import { PatternSaveLoad } from '../patterns/PatternSaveLoad';

const NS = 'gis-routing';

type ExportFormat = 'isoxml' | 'geojson' | 'gpx';
const FORMATS: readonly ExportFormat[] = ['isoxml', 'geojson', 'gpx'];
const GEOMETRIC_CODES: ReadonlySet<string> = new Set([
  'ACCESS_IN_ZONE', 'ACCESS_OUTSIDE_PARCEL', 'NO_DRIVABLE_AREA', 'INVALID_GEOMETRY',
]);

interface Props {
  state: WorkState;
  dispatch: React.Dispatch<WorkEvent>;
  onGenerate: () => void;
  onSave: () => void;
  onExport: (format: ExportFormat) => void;
  onShowError: (geometry: GeoJSON.Geometry) => void;
  plan: Plan | null;
}

function copyText(text: string, done: () => void): void {
  const fallback = () => {
    const ta = document.createElement('textarea');
    ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
    document.body.appendChild(ta); ta.select();
    try { document.execCommand('copy'); done(); } catch { /* unsupported */ }
    document.body.removeChild(ta);
  };
  if (navigator.clipboard?.writeText) {
    navigator.clipboard.writeText(text).then(done).catch(fallback);
  } else {
    fallback();
  }
}

function errorGeometry(params: Record<string, unknown>): GeoJSON.Geometry | null {
  const g = params.point ?? params.geometry;
  return g && typeof g === 'object' && 'type' in g ? (g as GeoJSON.Geometry) : null;
}

export const ActionsBar: React.FC<Props> = ({
  state, dispatch, onGenerate, onSave, onExport, onShowError, plan,
}) => {
  const { t } = useTranslation(NS);
  const [format, setFormat] = useState<ExportFormat>('isoxml');
  const [copied, setCopied] = useState(false);
  const [templateOpen, setTemplateOpen] = useState(false);

  const { phase, stale, error } = state;
  const operationId = state.result?.operationId ?? null;
  const shortId = operationId ? operationId.slice(-8) : '';
  const errGeometry = error && GEOMETRIC_CODES.has(error.code) ? errorGeometry(error.params) : null;

  const errorText = error
    ? t(`work.errors.${error.code}`, { detail: error.detail, defaultValue: '' }) ||
      t('work.errors.UNKNOWN', { detail: error.detail })
    : '';

  const handleCopy = () => {
    if (!operationId) return;
    copyText(operationId, () => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  };

  return (
    <div className="space-y-2">
      {phase === 'failed' && error && (
        <div role="alert" className="rounded-nkz-md bg-nkz-danger-soft border border-nkz-danger px-nkz-stack py-2 text-nkz-sm space-y-2">
          <p>{errorText}</p>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => dispatch({ type: 'DISMISS_ERROR' })}>
              {t('actions.retry')}
            </Button>
            {errGeometry && (
              <Button variant="ghost" onClick={() => onShowError(errGeometry)}>
                {t('result.showOnMap')}
              </Button>
            )}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          variant="primary"
          onClick={onGenerate}
          disabled={!canGenerate(state)}
          loading={phase === 'generating'}
        >
          {stale ? t('work.actions.regenerate') : t('actions.generate')}
        </Button>
        <Button
          variant="secondary"
          onClick={onSave}
          disabled={phase !== 'generated'}
          loading={phase === 'saving'}
        >
          {t('work.actions.sendToTractor')}
        </Button>
        {phase === 'saved' && operationId && (
          <>
            <Badge intent="positive">{t('work.actions.sent', { id: shortId })}</Badge>
            <code className="text-nkz-xs bg-nkz-surface px-2 py-1 rounded break-all">{operationId}</code>
            <Button variant="ghost" onClick={handleCopy}>
              {copied ? t('work.actions.copied') : t('work.actions.copyId')}
            </Button>
          </>
        )}
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-2">
          <span className="sr-only">{t('work.actions.exportFormat')}</span>
          <Select
            value={format}
            onValueChange={(v: string) => setFormat(v as ExportFormat)}
            options={FORMATS.map((f) => ({ value: f, label: f.toUpperCase() }))}
            disabled={!operationId}
          />
        </label>
        <Button variant="secondary" onClick={() => onExport(format)} disabled={!operationId}>
          {t('actions.export')}
        </Button>
        <Button
          variant="ghost"
          aria-expanded={templateOpen}
          disabled={!plan}
          onClick={() => setTemplateOpen((o) => !o)}
        >
          {t('work.actions.saveTemplate')}
        </Button>
      </div>

      {templateOpen && plan && (
        <PatternSaveLoad
          plan={plan}
          operationId={operationId}
          parcelId={state.parcel?.id ?? null}
          tractorId={state.machine.tractorId}
          implementId={state.machine.implementId}
          pattern={state.pattern.pattern === 'auto' ? plan.pattern : state.pattern.pattern}
          patternConfig={{
            width_m: state.machine.widthM,
            overlap_pct: state.machine.overlapPct,
            headland_passes: state.pattern.headlandPasses,
            turning_radius_m: state.machine.turningRadiusM,
          }}
        />
      )}
    </div>
  );
};
