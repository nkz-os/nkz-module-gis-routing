import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';

/** "Calculating…" status line with the seconds elapsed since it appeared. */
export const GenerateProgress: React.FC = () => {
  const { t } = useTranslation();
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return (
    <p role="status" className="text-nkz-xs text-nkz-text-secondary">
      {t('work.actions.calculating', { s: seconds })}
    </p>
  );
};
