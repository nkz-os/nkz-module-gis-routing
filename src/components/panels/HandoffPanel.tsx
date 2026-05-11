import React from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Smartphone } from 'lucide-react';

const NS = 'gis-routing';

interface Props { operationId: string | undefined; }

export const HandoffPanel: React.FC<Props> = ({ operationId }) => {
  const { t } = useTranslation(NS);
  if (!operationId) return null;

  return (
    <div className="rounded-nkz-lg border border-nkz-default p-nkz-md bg-nkz-surface-alt">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1 mb-3">
        <Smartphone className="w-3.5 h-3.5" />
        {t('handoff.title')}
      </h3>
      <p className="text-nkz-xs text-nkz-text-secondary mb-2">{t('handoff.body')}</p>
      <div className="flex items-center gap-2">
        <code className="text-[11px] bg-nkz-surface px-2 py-1 rounded break-all flex-1">
          {operationId}
        </code>
        <button
          onClick={() => { if (navigator.clipboard?.writeText) { void navigator.clipboard.writeText(operationId); } }}
          className="text-nkz-xs text-nkz-text-accent hover:underline flex-shrink-0"
        >
          {t('handoff.copyId')}
        </button>
      </div>
    </div>
  );
};
