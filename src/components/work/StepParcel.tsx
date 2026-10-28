import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Button, Select, Spinner } from '@nekazari/ui-kit';
import { api } from '../../services/api';
import type { StepProps } from './StepList';

const NS = 'gis-routing';

interface Props extends StepProps {
  onLoadError?: (msg: string) => void;
}

export const StepParcel: React.FC<Props> = ({ state, dispatch, onLoadError }) => {
  const { t } = useTranslation(NS);
  const [parcels, setParcels] = useState<any[]>([]);
  const [listLoading, setListLoading] = useState(true);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lastId, setLastId] = useState<string | null>(null);
  const latestRequestRef = useRef(0);

  useEffect(() => {
    let cancelled = false;
    api.listParcels()
      .then((d) => { if (!cancelled) setParcels([...(d || [])].sort((a, b) => String(a.name).localeCompare(String(b.name)))); })
      .catch((e) => { if (!cancelled) setError(e?.message ?? t('errors.geoFailed')); })
      .finally(() => { if (!cancelled) setListLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const load = useCallback((id: string) => {
    if (!id) return;
    setLastId(id);
    setError(null);
    setLoading(true);
    const requestId = Math.max(Date.now(), latestRequestRef.current + 1);
    latestRequestRef.current = requestId;
    dispatch({ type: 'PARCEL_SELECTED', id, requestId });
    Promise.all([api.getParcelGeometry(id), api.getParcelConfig(id)])
      .then(([g, cfg]) => {
        dispatch({ type: 'PARCEL_LOADED', requestId, id, name: g.name, geometry: g.geometry, config: cfg });
      })
      .catch((e) => {
        if (requestId !== latestRequestRef.current) return;
        const msg = e?.message ?? t('errors.geoFailed');
        setError(msg);
        onLoadError?.(msg);
      })
      .finally(() => {
        if (requestId === latestRequestRef.current) setLoading(false);
      });
  }, [dispatch, onLoadError, t]);

  const selected = state.parcel?.id ?? lastId ?? '';

  return (
    <div className="space-y-2">
      {listLoading ? (
        <Spinner />
      ) : parcels.length === 0 && !error ? (
        <p className="text-nkz-sm text-nkz-text-secondary">{t('parcel.empty')}</p>
      ) : (
        <Select
          value={selected}
          onValueChange={load}
          options={[
            { value: '', label: t('parcel.select') },
            ...parcels.map((p) => ({
              value: p.id,
              label: p.area != null ? `${p.name} (${Number(p.area).toFixed(1)} ha)` : String(p.name),
            })),
          ]}
          placeholder={t('parcel.select')}
          className="w-full"
        />
      )}
      {loading && (
        <div className="text-nkz-sm text-nkz-text-secondary flex items-center gap-1">
          <Spinner /><span>{t('parcel.loadingGeo')}</span>
        </div>
      )}
      {error && (
        <div className="space-y-1">
          <p className="text-nkz-sm text-nkz-danger">{error}</p>
          {lastId && (
            <Button variant="secondary" size="sm" onClick={() => load(lastId)}>{t('actions.retry')}</Button>
          )}
        </div>
      )}
      {state.parcel && (
        <a className="text-nkz-xs text-nkz-accent-base" href={`/viewer?entity=${encodeURIComponent(state.parcel.id)}`}>
          {t('actions.viewInCesium')}
        </a>
      )}
    </div>
  );
};
