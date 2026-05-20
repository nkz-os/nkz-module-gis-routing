import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Play, Loader2, AlertCircle, CheckCircle2, Circle } from 'lucide-react';
import { accent } from '../../config/accent';

const NS = 'gis-routing';

interface Props {
  onGenerate: () => void;
  generating: boolean;
  canGenerate: boolean;
  error: string | null;
  hasParcel?: boolean;
  hasGeometry?: boolean;
  hasValidWidth?: boolean;
}

interface ValidationItem {
  key: string;
  label: string;
  pass: boolean;
}

export const StepGenerate: React.FC<Props> = ({
  onGenerate,
  generating,
  canGenerate,
  error,
  hasParcel = false,
  hasGeometry = false,
  hasValidWidth = false,
}) => {
  const { t } = useTranslation(NS);

  const items: ValidationItem[] = [
    { key: 'parcel', label: t('validation.parcelReady'), pass: hasParcel },
    { key: 'geometry', label: t('validation.geometryReady'), pass: hasGeometry },
    { key: 'width', label: t('validation.widthReady'), pass: hasValidWidth },
  ];

  return (
    <div className="space-y-nkz-stack">
      {/* Granular validation checklist */}
      <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt space-y-1.5">
        <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase tracking-wider mb-2">
          {t('workflow.validate')}
        </h3>
        {items.map(item => (
          <div key={item.key} className="flex items-center gap-2 text-nkz-xs">
            {item.pass ? (
              <CheckCircle2 className="w-3.5 h-3.5 text-nkz-text-success flex-shrink-0" />
            ) : (
              <Circle className="w-3.5 h-3.5 text-nkz-text-secondary flex-shrink-0" />
            )}
            <span className={item.pass ? 'text-nkz-text-success' : 'text-nkz-text-secondary'}>
              {item.label}
            </span>
          </div>
        ))}
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-nkz-surface border border-nkz-accent rounded-nkz-md p-3 text-nkz-xs text-nkz-text-error">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <button
        onClick={onGenerate}
        disabled={generating || !canGenerate}
        className="w-full min-h-[48px] font-bold text-nkz-sm rounded-nkz-lg transition-colors flex items-center justify-center gap-2 text-nkz-text-on-accent disabled:opacity-50"
        style={{ backgroundColor: accent.base }}
      >
        {generating ? (
          <><Loader2 className="w-4 h-4 animate-spin" />{t('actions.generating')}</>
        ) : (
          <><Play className="w-4 h-4" />{t('actions.generate')}</>
        )}
      </button>
    </div>
  );
};
