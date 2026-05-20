import React, { useState, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { MapPin, Loader2, AlertCircle, ChevronDown } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Props {
  parcelId: string | null;
  onParcelChange: (id: string, geometry: any, name: string) => void;
}

export const StepParcel: React.FC<Props> = ({ parcelId, onParcelChange }) => {
  const { t } = useTranslation(NS);
  const [parcels, setParcels] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [geoLoading, setGeoLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(true);
  const selectedName = parcels.find(p => p.id === parcelId)?.name || '';

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api.listParcels()
      .then(d => { if (!cancelled) setParcels(d || []); })
      .catch(e => { if (!cancelled) setError(e?.message); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, []);

  const handleSelect = async (id: string) => {
    if (!id) return;
    setGeoLoading(true);
    setError(null);
    try {
      const data = await api.getParcelGeometry(id);
      onParcelChange(id, data?.geometry || null, data?.name || '');
    } catch (e: any) {
      setError(e?.message || 'Failed to load parcel geometry');
      onParcelChange(id, null, '');
    } finally {
      setGeoLoading(false);
    }
  };

  return (
    <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
      <button onClick={() => setExpanded(!expanded)}
        className="w-full flex items-center justify-between px-nkz-md py-3 text-nkz-sm font-semibold">
        <span className="flex items-center gap-nkz-sm">
          <span className="w-6 h-6 rounded-full bg-nkz-text-accent text-white text-nkz-sm flex items-center justify-center">1</span>
          <MapPin className="w-4 h-4 text-nkz-text-accent" />
          {t('parcel.label')}
        </span>
        <ChevronDown className={`w-4 h-4 transition-transform ${expanded ? '' : '-rotate-90'}`} />
      </button>
      {expanded && (
        <div className="px-nkz-md pb-3 space-y-2">
          {loading ? (
            <Loader2 className="w-4 h-4 animate-spin text-nkz-text-secondary" />
          ) : error ? (
            <p className="text-nkz-sm text-nkz-text-error flex items-center gap-1"><AlertCircle className="w-3 h-3" />{error}</p>
          ) : parcels.length === 0 ? (
            <p className="text-nkz-sm text-nkz-text-secondary">{t('parcel.empty')}</p>
          ) : (
            <select value={parcelId || ''} onChange={e => handleSelect(e.target.value)}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface">
              <option value="">{t('parcel.select')}</option>
              {parcels.map(p => (
                <option key={p.id} value={p.id}>{p.name}{p.area ? ` (${p.area.toFixed(1)} ha)` : ''}</option>
              ))}
            </select>
          )}
          {geoLoading && (
            <p className="text-nkz-sm text-nkz-text-secondary flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" />Loading geometry...</p>
          )}
          {selectedName && !geoLoading && <p className="text-nkz-sm text-nkz-text-success">{selectedName}</p>}
        </div>
      )}
    </div>
  );
};
