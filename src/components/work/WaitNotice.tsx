import React, { useEffect, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';

export function formatElapsed(totalSeconds: number): string {
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${String(s).padStart(2, '0')}`;
}

/** Seconds since the component mounted, ticking once a second. */
export function useElapsedSeconds(): number {
  const [seconds, setSeconds] = useState(0);
  useEffect(() => {
    const started = Date.now();
    const id = setInterval(() => setSeconds(Math.floor((Date.now() - started) / 1000)), 1000);
    return () => clearInterval(id);
  }, []);
  return seconds;
}

/**
 * "This takes a while" notice shown from the first moment of a long job, with the elapsed
 * time (m:ss). Mount it while the job runs and unmount it when the job ends.
 */
export const WaitNotice: React.FC<{ messageKey: string; showElapsed?: boolean }> = ({
  messageKey, showElapsed = true,
}) => {
  const { t } = useTranslation(NS);
  const seconds = useElapsedSeconds();
  return (
    <p role="status" aria-live="polite" className="text-nkz-xs text-nkz-text-secondary" data-testid="wait-notice">
      {t(messageKey)}
      {showElapsed && <span className="tabular-nums"> ({formatElapsed(seconds)})</span>}
    </p>
  );
};
