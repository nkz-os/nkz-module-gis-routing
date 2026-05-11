import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Play, Loader2, AlertCircle, CheckCircle2 } from 'lucide-react';
import manifest from '../../../manifest.json';

const NS = 'gis-routing';
const { accent } = manifest;

interface Props {
  onGenerate: () => void;
  generating: boolean;
  canGenerate: boolean;
  error: string | null;
}

export const StepGenerate: React.FC<Props> = ({ onGenerate, generating, canGenerate, error }) => {
  const { t } = useTranslation(NS);

  return (
    <div className="space-y-nkz-stack">
      {/* Validation checklist */}
      <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt space-y-1">
        <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase mb-2">Prerequisites</h3>
        <div className="flex items-center gap-2 text-nkz-xs">
          <CheckCircle2 className={`w-3.5 h-3.5 ${canGenerate ? 'text-nkz-text-success' : 'text-nkz-text-secondary'}`} />
          <span>{canGenerate ? 'Ready to generate' : 'Select parcel and configure pattern'}</span>
        </div>
      </div>

      {error && (
        <div className="flex items-start gap-2 bg-nkz-surface border border-nkz-accent rounded-nkz-md p-3 text-nkz-xs text-nkz-text-error">
          <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <button onClick={onGenerate} disabled={generating || !canGenerate}
        className="w-full min-h-[48px] font-bold text-nkz-sm rounded-nkz-lg transition-colors flex items-center justify-center gap-2 text-nkz-text-on-accent disabled:opacity-50"
        style={{ backgroundColor: accent.base }}>
        {generating ? (
          <><Loader2 className="w-4 h-4 animate-spin" />{t('actions.generating')}</>
        ) : (
          <><Play className="w-4 h-4" />{t('actions.generate')}</>
        )}
      </button>
    </div>
  );
};
