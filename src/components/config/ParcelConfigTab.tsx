import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { MapPin, Loader2, AlertCircle, ShieldOff, Save } from 'lucide-react';
import { accent } from '../../config/accent';
import { api } from '../../services/api';

const NS = 'gis-routing';

const ACTIVATE_EVENT = 'nekazari:gis-routing:parcelConfig:activate';
const CLEAR_EVENT = 'nekazari:gis-routing:parcelConfig:clear';
const ACCESS_PICKED_EVENT = 'nekazari:gis-routing:parcelConfig:accessPicked';
const ZONE_DRAWN_EVENT = 'nekazari:gis-routing:parcelConfig:zoneDrawn';
const SHOW_EVENT = 'nekazari:gis-routing:parcelConfig:show';
const HIDE_EVENT = 'nekazari:gis-routing:parcelConfig:hide';

interface Zone {
  id: string;
  ring: number[][];
}

function dispatchActivate(mode: 'access' | 'zone' | 'off') {
  window.dispatchEvent(
    new CustomEvent(ACTIVATE_EVENT, { detail: { mode } }),
  );
}

function dispatchClear() {
  window.dispatchEvent(new CustomEvent(CLEAR_EVENT));
}

export const ParcelConfigTab: React.FC = () => {
  const { t } = useTranslation(NS);

  const [parcels, setParcels] = useState<any[]>([]);
  const [parcelsLoading, setParcelsLoading] = useState(true);
  const [parcelsError, setParcelsError] = useState<string | null>(null);

  const [parcelId, setParcelId] = useState<string | null>(null);
  const [configLoading, setConfigLoading] = useState(false);

  const [accessPoint, setAccessPoint] = useState<[number, number] | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);

  const [saving, setSaving] = useState(false);
  const [status, setStatus] = useState<'idle' | 'saved' | 'error'>('idle');

  // Load parcel list once on mount
  useEffect(() => {
    let cancelled = false;
    setParcelsLoading(true);
    api.listParcels()
      .then(d => { if (!cancelled) setParcels(d || []); })
      .catch(e => { if (!cancelled) setParcelsError(e?.message || 'Failed to load parcels'); })
      .finally(() => { if (!cancelled) setParcelsLoading(false); });
    return () => { cancelled = true; };
  }, []);

  // Subscribe to draw-tool CustomEvents
  useEffect(() => {
    const onAccessPicked = (e: Event) => {
      const lonlat = (e as CustomEvent).detail?.lonlat as [number, number] | undefined;
      if (lonlat) {
        setAccessPoint(lonlat);
        dispatchActivate('off');
      }
    };
    const onZoneDrawn = (e: Event) => {
      const ring = (e as CustomEvent).detail?.ring as number[][] | undefined;
      if (ring) {
        const id =
          typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
            ? crypto.randomUUID()
            : String(Date.now()) + String(Math.random());
        setZones(prev => [...prev, { id, ring }]);
        dispatchActivate('off');
      }
    };

    window.addEventListener(ACCESS_PICKED_EVENT, onAccessPicked);
    window.addEventListener(ZONE_DRAWN_EVENT, onZoneDrawn);

    return () => {
      window.removeEventListener(ACCESS_PICKED_EVENT, onAccessPicked);
      window.removeEventListener(ZONE_DRAWN_EVENT, onZoneDrawn);
      dispatchActivate('off');
      window.dispatchEvent(new CustomEvent(HIDE_EVENT));
    };
  }, []);

  // Load config when a parcel is selected
  const handleParcelSelect = useCallback(async (id: string) => {
    if (!id) {
      setParcelId(null);
      setAccessPoint(null);
      setZones([]);
      dispatchClear();
      dispatchActivate('off');
      return;
    }

    setParcelId(id);
    setAccessPoint(null);
    setZones([]);
    setStatus('idle');
    dispatchClear();
    dispatchActivate('off');

    setConfigLoading(true);
    try {
      const cfg = await api.getParcelConfig(id);
      // Hydrate access point
      if (cfg?.accessPoint?.coordinates) {
        setAccessPoint(cfg.accessPoint.coordinates as [number, number]);
      }
      // Hydrate zones
      if (cfg?.exclusionZones?.features) {
        const hydrated: Zone[] = (cfg.exclusionZones.features as any[]).map(f => ({
          id:
            (f.properties?.id as string | undefined) ??
            (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
              ? crypto.randomUUID()
              : String(Date.now()) + String(Math.random())),
          ring: f.geometry?.coordinates?.[0] ?? [],
        }));
        setZones(hydrated);
      }
      // Notify the viewer layer so it can render the config overlay
      window.dispatchEvent(new CustomEvent(SHOW_EVENT, { detail: { parcelId: id } }));
    } catch {
      // Config may not exist yet — that is OK, start fresh
    } finally {
      setConfigLoading(false);
    }
  }, []);

  const handleMarkAccessPoint = useCallback(() => {
    if (!parcelId) return;
    dispatchActivate('access');
  }, [parcelId]);

  const handleDrawZone = useCallback(() => {
    if (!parcelId) return;
    dispatchActivate('zone');
  }, [parcelId]);

  const handleDeleteZone = useCallback((id: string) => {
    setZones(prev => prev.filter(z => z.id !== id));
  }, []);

  const handleSave = useCallback(async () => {
    if (!parcelId) return;
    setSaving(true);
    setStatus('idle');
    try {
      const payload = {
        accessPoint: accessPoint
          ? { type: 'Point', coordinates: accessPoint }
          : null,
        exclusionZones: {
          type: 'FeatureCollection',
          features: zones.map(z => ({
            type: 'Feature',
            properties: { id: z.id },
            geometry: { type: 'Polygon', coordinates: [z.ring] },
          })),
        },
      };
      await api.saveParcelConfig(parcelId, payload as any);
      setStatus('saved');
    } catch {
      setStatus('error');
    } finally {
      setSaving(false);
    }
  }, [parcelId, accessPoint, zones]);

  return (
    <div className="space-y-nkz-stack">
      {/* Parcel selector */}
      <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
        <div className="px-nkz-md py-3 border-b border-nkz-default flex items-center gap-nkz-sm">
          <MapPin className="w-4 h-4 text-nkz-text-accent" />
          <span className="text-nkz-sm font-semibold text-nkz-text-primary">
            {t('parcelConfig.tab')}
          </span>
        </div>
        <div className="px-nkz-md py-3 space-y-2">
          {parcelsLoading ? (
            <Loader2 className="w-4 h-4 animate-spin text-nkz-text-secondary" />
          ) : parcelsError ? (
            <p className="text-nkz-sm text-nkz-text-error flex items-center gap-1">
              <AlertCircle className="w-3 h-3" />
              {parcelsError}
            </p>
          ) : parcels.length === 0 ? (
            <p className="text-nkz-sm text-nkz-text-secondary">{t('parcel.empty')}</p>
          ) : (
            <select
              value={parcelId || ''}
              onChange={e => handleParcelSelect(e.target.value)}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface"
            >
              <option value="">{t('parcelConfig.selectParcel')}</option>
              {parcels.map(p => (
                <option key={p.id} value={p.id}>
                  {p.name}{p.area ? ` (${p.area.toFixed(1)} ha)` : ''}
                </option>
              ))}
            </select>
          )}
          {configLoading && (
            <p className="text-nkz-xs text-nkz-text-secondary flex items-center gap-1">
              <Loader2 className="w-3 h-3 animate-spin" />
              Loading...
            </p>
          )}
        </div>
      </div>

      {/* Instructions */}
      {parcelId && (
        <p className="text-nkz-xs text-nkz-text-secondary px-1">
          {t('parcelConfig.instructions')}
        </p>
      )}

      {/* No parcel hint */}
      {!parcelId && !parcelsLoading && (
        <p className="text-nkz-sm text-nkz-text-secondary text-center py-4">
          {t('parcelConfig.selectParcel')}
        </p>
      )}

      {/* Access point section */}
      {parcelId && (
        <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
          <div className="px-nkz-md py-3 border-b border-nkz-default">
            <span className="text-nkz-sm font-semibold text-nkz-text-primary">
              {t('parcelConfig.accessPoint')}
            </span>
          </div>
          <div className="px-nkz-md py-3 space-y-2">
            <div className="text-nkz-xs text-nkz-text-secondary">
              {accessPoint
                ? `${accessPoint[1].toFixed(6)}, ${accessPoint[0].toFixed(6)}`
                : t('parcelConfig.noAccessPoint')}
            </div>
            <button
              onClick={handleMarkAccessPoint}
              disabled={!parcelId}
              className="w-full py-2 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent disabled:opacity-50 transition-opacity"
              style={{ backgroundColor: accent.base }}
            >
              {t('parcelConfig.dropAccessPoint')}
            </button>
          </div>
        </div>
      )}

      {/* No-go zones section */}
      {parcelId && (
        <div className="rounded-nkz-lg border border-nkz-default bg-nkz-surface-alt">
          <div className="px-nkz-md py-3 border-b border-nkz-default flex items-center justify-between">
            <span className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-1">
              <ShieldOff className="w-4 h-4 text-nkz-text-accent" />
              {t('parcelConfig.noGoZones')}
            </span>
            {zones.length > 0 && (
              <span className="text-nkz-xs text-nkz-text-secondary">
                {t('parcelConfig.zonesCount', { count: zones.length })}
              </span>
            )}
          </div>
          <div className="px-nkz-md py-3 space-y-2">
            {zones.length > 0 && (
              <div className="divide-y divide-nkz-default rounded-nkz-md border border-nkz-default bg-nkz-surface max-h-40 overflow-y-auto">
                {zones.map((z, idx) => (
                  <div key={z.id} className="flex items-center justify-between px-3 py-2">
                    <span className="text-nkz-xs text-nkz-text-primary">
                      {t('parcelConfig.noGoZones')} {idx + 1}
                      <span className="text-nkz-text-secondary ml-1">({z.ring.length} pts)</span>
                    </span>
                    <button
                      onClick={() => handleDeleteZone(z.id)}
                      className="text-nkz-xs text-nkz-text-secondary hover:text-nkz-text-error transition-colors px-2 py-0.5"
                    >
                      {t('parcelConfig.deleteZone')}
                    </button>
                  </div>
                ))}
              </div>
            )}
            <button
              onClick={handleDrawZone}
              disabled={!parcelId}
              className="w-full py-2 rounded-nkz-md text-nkz-xs font-semibold border border-nkz-default text-nkz-text-primary bg-nkz-surface hover:bg-nkz-surface-alt disabled:opacity-50 transition-colors"
            >
              {t('parcelConfig.drawZone')}
            </button>
          </div>
        </div>
      )}

      {/* Save button */}
      {parcelId && (
        <button
          onClick={handleSave}
          disabled={saving || !parcelId}
          className="w-full py-2.5 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent disabled:opacity-50 flex items-center justify-center gap-1 transition-opacity"
          style={{ backgroundColor: accent.base }}
        >
          {saving ? (
            <Loader2 className="w-4 h-4 animate-spin" />
          ) : (
            <Save className="w-4 h-4" />
          )}
          {t('parcelConfig.save')}
        </button>
      )}

      {/* Status feedback */}
      {status === 'saved' && (
        <div className="rounded-nkz-md bg-green-50 border border-green-200 px-nkz-md py-2 text-nkz-sm text-green-700 font-medium text-center">
          ✓ {t('parcelConfig.saved')}
        </div>
      )}
      {status === 'error' && (
        <div className="rounded-nkz-md border border-nkz-default bg-nkz-surface-alt px-nkz-md py-2 text-nkz-sm text-nkz-text-error text-center flex items-center justify-center gap-1">
          <AlertCircle className="w-3 h-3" />
          {t('parcelConfig.saveError')}
        </div>
      )}
    </div>
  );
};
