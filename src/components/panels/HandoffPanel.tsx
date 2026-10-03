import React, { useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Smartphone, Copy, Check } from 'lucide-react';
import { Button } from '@nekazari/ui-kit';

const NS = 'gis-routing';

interface Props { operationId: string | undefined; }

export const HandoffPanel: React.FC<Props> = ({ operationId }) => {
  const { t } = useTranslation(NS);
  const [copied, setCopied] = useState(false);
  if (!operationId) return null;

  const handleCopy = () => {
    const text = operationId;
    const done = () => { setCopied(true); setTimeout(() => setCopied(false), 2000); };
    if (navigator.clipboard?.writeText) {
      navigator.clipboard.writeText(text).then(done).catch(() => {
        // Fallback for older browsers
        const ta = document.createElement('textarea');
        ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
        document.body.appendChild(ta); ta.select();
        try { document.execCommand('copy'); done(); } catch { /* unsupported */ }
        document.body.removeChild(ta);
      });
    } else {
      const ta = document.createElement('textarea');
      ta.value = text; ta.style.position = 'fixed'; ta.style.opacity = '0';
      document.body.appendChild(ta); ta.select();
      try { document.execCommand('copy'); done(); } catch { /* unsupported */ }
      document.body.removeChild(ta);
    }
  };

  return (
    <div className="rounded-nkz-lg border border-nkz-border p-nkz-stack bg-nkz-surface-raised">
      <h3 className="text-nkz-xs font-semibold text-nkz-text-secondary uppercase flex items-center gap-1 mb-3">
        <Smartphone className="w-3.5 h-3.5" />
        {t('handoff.title')}
      </h3>
      <p className="text-nkz-xs text-nkz-text-secondary mb-2">{t('handoff.body')}</p>
      <div className="flex items-center gap-2">
        <code className="text-[11px] bg-nkz-surface px-2 py-1 rounded break-all flex-1">
          {operationId}
        </code>
        <Button
          onClick={handleCopy}
          className={`px-2 py-1 flex items-center gap-1 flex-shrink-0 ${copied ? 'text-nkz-success bg-nkz-surface' : 'text-nkz-accent-base bg-nkz-surface'}`}
        >
          {copied ? <Check className="w-3 h-3" /> : <Copy className="w-3 h-3" />}
          {copied ? t('handoff.copied') : t('handoff.copyId')}
        </Button>
      </div>
      <p className="text-nkz-xs text-nkz-text-secondary mt-2">
        nkz://operations/{operationId}
      </p>
    </div>
  );
};

