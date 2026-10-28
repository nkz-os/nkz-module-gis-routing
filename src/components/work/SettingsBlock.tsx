import React, { useEffect, useRef, useState } from 'react';
import { useAuth, useTranslation } from '@nekazari/sdk';
import { Select } from '@nekazari/ui-kit';
import { api, ApiError, type DispatchNotification } from '../../services/api';

const NS = 'gis-routing';
const ADMIN_ROLES = ['TenantAdmin', 'PlatformAdmin'];
const VALUES: readonly DispatchNotification[] = ['immediate', 'digest', 'none'];

/** Tenant setting for the alert raised on save. Admins only (the backend enforces it too). */
export const SettingsBlock: React.FC = () => {
  const { t } = useTranslation(NS);
  const auth = useAuth();
  const isAdmin = auth.hasAnyRole(ADMIN_ROLES);
  const [value, setValue] = useState<DispatchNotification>('immediate');
  const [msg, setMsg] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const alive = useRef(true);

  useEffect(() => () => { alive.current = false; }, []);
  useEffect(() => {
    if (!isAdmin) return undefined;
    let cancelled = false;
    api.getSettings()
      .then((s) => { if (!cancelled) setValue(s.dispatch_notification); })
      .catch((e) => {
        console.warn('[gis-routing] settings load failed', e);
        if (!cancelled) setMsg({ kind: 'error', text: t('settings.loadFailed') });
      });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAdmin]);

  if (!isAdmin) return null;

  const change = async (next: string) => {
    const previous = value;
    const dispatch = next as DispatchNotification;
    setValue(dispatch);
    setBusy(true);
    setMsg(null);
    try {
      const saved = await api.putSettings(dispatch);
      if (alive.current) { setValue(saved.dispatch_notification); setMsg({ kind: 'ok', text: t('settings.saved') }); }
    } catch (e) {
      if (!alive.current) return;
      setValue(previous);
      const forbidden = e instanceof ApiError && e.code === 'FORBIDDEN';
      setMsg({ kind: 'error', text: t(forbidden ? 'settings.forbidden' : 'settings.saveFailed') });
    } finally {
      if (alive.current) setBusy(false);
    }
  };

  return (
    <section className="space-y-2" aria-label={t('settings.title')}>
      <h2 className="text-nkz-sm font-semibold">{t('settings.title')}</h2>
      <label className="block">
        <span className="text-nkz-xs text-nkz-text-secondary">{t('settings.dispatch.label')}</span>
        <Select
          value={value}
          disabled={busy}
          onValueChange={(v: string) => { void change(v); }}
          options={VALUES.map((v) => ({ value: v, label: t(`settings.dispatch.${v}`) }))}
        />
      </label>
      {msg && (
        <p
          role={msg.kind === 'error' ? 'alert' : 'status'}
          className={msg.kind === 'error' ? 'text-nkz-xs text-nkz-danger' : 'text-nkz-xs text-nkz-text-secondary'}
        >
          {msg.text}
        </p>
      )}
    </section>
  );
};
