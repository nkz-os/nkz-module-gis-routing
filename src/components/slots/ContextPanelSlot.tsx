/**
 * ContextPanelSlot — Viewer sidebar showing saved routes for the selected parcel.
 * Click a route to visualize it on the Cesium map via GisRoutingMapLayer.
 */
import React, { useEffect, useState } from 'react';
import { SlotShell } from '@nekazari/viewer-kit';
import { useViewer, useTranslation } from '@nekazari/sdk';
import { ExternalLink, Eye, Loader2, MapPin, Crosshair, Flag, Ban, Save, Trash2 } from 'lucide-react';
import { accent } from '../../config/accent';
import { api } from '../../services/api';

const NS = 'gis-routing';

export const ContextPanelSlot: React.FC = () => {
  const { t } = useTranslation(NS);
  const { selectedEntityId, selectedEntityType } = useViewer();
  const [patterns, setPatterns] = useState<any[]>([]);
  const [loading, setLoading] = useState(false);
  // Pathfinding state (driven by events from GisRoutingMapLayer)
  const [pfState, setPfState] = useState<string>('idle');
  const [pfAlt, setPfAlt] = useState<any>(null);
  // Parcel-config state (access point + no-go zones), drawn via ParcelConfigDrawTool
  const [accessPoint, setAccessPoint] = useState<[number, number] | null>(null);
  const [zones, setZones] = useState<Array<{ id: string; ring: number[][] }>>([]);
  const [cfgSaving, setCfgSaving] = useState(false);
  const [cfgStatus, setCfgStatus] = useState<'idle' | 'saved' | 'error'>('idle');

  useEffect(() => {
    if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
      setPatterns([]);
      return;
    }
    setLoading(true);
    api.listPatterns(selectedEntityId)
      .then((res: any) => setPatterns(res?.data || []))
      .catch(() => setPatterns([]))
      .finally(() => setLoading(false));
  }, [selectedEntityId, selectedEntityType]);

  // Load saved parcel config when a parcel is selected; render it on the globe.
  useEffect(() => {
    if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
      setAccessPoint(null); setZones([]); setCfgStatus('idle');
      return;
    }
    let cancelled = false;
    setCfgStatus('idle');
    api.getParcelConfig(selectedEntityId)
      .then((d: any) => {
        if (cancelled) return;
        setAccessPoint(d?.accessPoint?.coordinates ?? null);
        setZones((d?.exclusionZones?.features ?? []).map((f: any, i: number) => ({
          id: f?.properties?.id ?? `z${i}`,
          ring: f?.geometry?.coordinates?.[0] ?? [],
        })));
      })
      .catch(() => { if (!cancelled) { setAccessPoint(null); setZones([]); } });
    window.dispatchEvent(new CustomEvent('nekazari:gis-routing:parcelConfig:show',
      { detail: { parcelId: selectedEntityId } }));
    return () => {
      cancelled = true;
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:parcelConfig:activate',
        { detail: { mode: 'off' } }));
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:parcelConfig:hide'));
    };
  }, [selectedEntityId, selectedEntityType]);

  // Receive geometry drawn on the globe by ParcelConfigDrawTool.
  useEffect(() => {
    const onAccess = (e: Event) => setAccessPoint((e as CustomEvent).detail?.lonlat ?? null);
    const onZone = (e: Event) => {
      const ring = (e as CustomEvent).detail?.ring;
      if (ring) setZones(prev => [...prev, { id: `z${Date.now()}`, ring }]);
    };
    window.addEventListener('nekazari:gis-routing:parcelConfig:accessPicked', onAccess);
    window.addEventListener('nekazari:gis-routing:parcelConfig:zoneDrawn', onZone);
    return () => {
      window.removeEventListener('nekazari:gis-routing:parcelConfig:accessPicked', onAccess);
      window.removeEventListener('nekazari:gis-routing:parcelConfig:zoneDrawn', onZone);
    };
  }, []);

  // Listen for pathfinding events from GisRoutingMapLayer
  useEffect(() => {
    const onState = (e: Event) => setPfState((e as CustomEvent).detail?.state || 'idle');
    const onAlt = (e: Event) => { setPfAlt((e as CustomEvent).detail); setPfState('done'); };
    window.addEventListener('nekazari:pf:stateChange', onState);
    window.addEventListener('nekazari:gis-routing:pathAlternativeSelected', onAlt);
    return () => {
      window.removeEventListener('nekazari:pf:stateChange', onState);
      window.removeEventListener('nekazari:gis-routing:pathAlternativeSelected', onAlt);
    };
  }, []);

  const startPfPicking = () => {
    setPfState('picking-a'); setPfAlt(null);
    window.dispatchEvent(new CustomEvent('nekazari:gis-routing:pickPathStart'));
    // Inform context panel of state change
    window.dispatchEvent(new CustomEvent('nekazari:pf:stateChange', { detail: { state: 'picking-a' } }));
  };

  const cancelPf = () => {
    setPfState('idle'); setPfAlt(null);
    window.dispatchEvent(new CustomEvent('nekazari:gis-routing:pickPathCancel'));
  };

  const handleSavePfAlt = (alt: any) => {
    if (!alt?.geometry) return;
    window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
      detail: { geometry: alt.geometry, prescriptionMap: null },
    }));
    setPfState('idle');
    setPfAlt(null);
  };

  const markAccess = () => window.dispatchEvent(new CustomEvent(
    'nekazari:gis-routing:parcelConfig:activate', { detail: { mode: 'access' } }));
  const drawZone = () => window.dispatchEvent(new CustomEvent(
    'nekazari:gis-routing:parcelConfig:activate', { detail: { mode: 'zone' } }));
  const removeZone = (id: string) => setZones(prev => prev.filter(z => z.id !== id));
  const saveCfg = async () => {
    if (!selectedEntityId) return;
    setCfgSaving(true); setCfgStatus('idle');
    try {
      await api.saveParcelConfig(selectedEntityId, {
        accessPoint: accessPoint ? { type: 'Point', coordinates: accessPoint } : null,
        exclusionZones: {
          type: 'FeatureCollection',
          features: zones.map(z => ({
            type: 'Feature', properties: { id: z.id },
            geometry: { type: 'Polygon', coordinates: [z.ring] },
          })),
        },
      });
      setCfgStatus('saved');
    } catch {
      setCfgStatus('error');
    } finally {
      setCfgSaving(false);
    }
  };

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={accent}>
        <div className="p-4 text-nkz-sm text-nkz-text-secondary text-center">
          {t('zoning.selectParcel')}
        </div>
      </SlotShell>
    );
  }

  const handleShowOnMap = (p: any) => {
    try {
      const geom = typeof p.route_geojson === 'string'
        ? JSON.parse(p.route_geojson)
        : p.route_geojson;
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:routeGenerated', {
        detail: {
          geometry: geom,
          prescriptionMap: p.vra_prescription_map || null,
        },
      }));
    } catch {
      // ignore parse errors
    }
  };

  return (
    <SlotShell moduleId="nkz-module-gis-routing" accent={accent}>
      <div className="p-4 space-y-3 text-nkz-sm">
        <p className="font-semibold text-nkz-text-primary">{t('title')}</p>

        {loading ? (
          <div className="flex items-center gap-2 text-nkz-text-secondary">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-nkz-xs">{t('loading')}</span>
          </div>
        ) : patterns.length === 0 ? (
          <div className="text-center py-3">
            <MapPin className="w-5 h-5 text-nkz-text-muted mx-auto mb-1" />
            <p className="text-nkz-xs text-nkz-text-secondary">{t('patterns.noSaved')}</p>
          </div>
        ) : (
          <div className="space-y-1.5 max-h-64 overflow-y-auto">
            {patterns.map((p: any) => (
              <div
                key={p.id}
                className="flex items-center gap-2 rounded-nkz-md border border-nkz-default p-2.5 bg-nkz-surface-alt"
              >
                <div className="flex-1 min-w-0">
                  <p className="text-nkz-sm font-medium text-nkz-text-primary truncate">
                    {p.name}
                  </p>
                  <p className="text-nkz-xs text-nkz-text-secondary">
                    {p.pattern_type}
                    {p.created_at
                      ? ` · ${new Date(p.created_at * 1000).toLocaleDateString()}`
                      : ''}
                  </p>
                </div>
                <button
                  onClick={() => handleShowOnMap(p)}
                  className="flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
                  style={{ backgroundColor: accent.base }}
                  title={t('patterns.loadFromContext')}
                >
                  <Eye className="w-3.5 h-3.5" />
                </button>
              </div>
            ))}
          </div>
        )}

        {/* Parcel configuration: access point + no-go zones (drawn on the globe) */}
        <div className="border-t border-nkz-default pt-3 space-y-2">
          <p className="text-nkz-sm font-semibold text-nkz-text-primary">
            {t('parcelConfig.tab')}
          </p>
          <p className="text-nkz-xs text-nkz-text-secondary">
            {t('parcelConfig.instructions')}
          </p>
          <div className="flex gap-2">
            <button
              onClick={markAccess}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-nkz-md text-nkz-xs font-semibold border border-nkz-default hover:bg-nkz-surface-alt"
            >
              <Flag className="w-3.5 h-3.5" />
              {t('parcelConfig.dropAccessPoint')}
            </button>
            <button
              onClick={drawZone}
              className="flex-1 flex items-center justify-center gap-1 py-1.5 rounded-nkz-md text-nkz-xs font-semibold border border-nkz-default hover:bg-nkz-surface-alt"
            >
              <Ban className="w-3.5 h-3.5" />
              {t('parcelConfig.drawZone')}
            </button>
          </div>
          <p className="text-nkz-xs text-nkz-text-secondary">
            <span className={accessPoint ? 'text-nkz-text-success' : 'text-nkz-text-muted'}>
              {accessPoint ? t('parcel.accessBadge') : t('parcelConfig.noAccessPoint')}
            </span>
            {' · '}
            {t('parcelConfig.zonesCount', { count: zones.length })}
          </p>
          {zones.length > 0 && (
            <div className="space-y-1 max-h-32 overflow-y-auto">
              {zones.map((z, i) => (
                <div
                  key={z.id}
                  className="flex items-center justify-between text-nkz-xs bg-nkz-surface-alt rounded-nkz-md px-2 py-1"
                >
                  <span>{t('parcelConfig.noGoZones')} {i + 1}</span>
                  <button
                    onClick={() => removeZone(z.id)}
                    className="text-nkz-text-error hover:opacity-80"
                    title={t('parcelConfig.deleteZone')}
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              ))}
            </div>
          )}
          <button
            onClick={saveCfg}
            disabled={cfgSaving}
            className="w-full flex items-center justify-center gap-1.5 py-2 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent hover:opacity-90 disabled:opacity-50"
            style={{ backgroundColor: accent.base }}
          >
            {cfgSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            {t('parcelConfig.save')}
          </button>
          {cfgStatus === 'saved' && (
            <p className="text-nkz-xs text-nkz-text-success text-center">{t('parcelConfig.saved')}</p>
          )}
          {cfgStatus === 'error' && (
            <p className="text-nkz-xs text-nkz-text-error text-center">{t('parcelConfig.saveError')}</p>
          )}
        </div>

        {/* Pathfinding section */}
        <div className="border-t border-nkz-default pt-3 space-y-2">
          <p className="text-nkz-sm font-semibold text-nkz-text-primary">
            {t('pathfinding.pickOnMap')}
          </p>

          {pfState === 'idle' && (
            <button
              onClick={startPfPicking}
              className="w-full flex items-center justify-center gap-1.5 py-2 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
              style={{ backgroundColor: accent.base }}
            >
              <Crosshair className="w-3.5 h-3.5" />
              {t('pathfinding.pickOnMap')}
            </button>
          )}

          {pfState === 'picking-a' && (
            <div className="text-nkz-sm text-nkz-text-secondary text-center py-2 bg-nkz-surface-alt rounded-nkz-md">
              <div className="w-3 h-3 rounded-full bg-green-500 inline-block mr-1" />
              {t('pathfinding.pickPointA')}
            </div>
          )}

          {pfState === 'picking-b' && (
            <div className="text-nkz-sm text-nkz-text-secondary text-center py-2 bg-nkz-surface-alt rounded-nkz-md">
              <div className="w-3 h-3 rounded-full bg-red-500 inline-block mr-1" />
              {t('pathfinding.pickPointB')}
            </div>
          )}

          {pfState === 'calculating' && (
            <div className="flex items-center gap-2 text-nkz-sm text-nkz-text-secondary py-2">
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('pathfinding.calculating')}
            </div>
          )}

          {pfAlt && (
            <div className="space-y-1.5">
              <p className="text-nkz-xs font-semibold text-nkz-text-secondary">
                {t('pathfinding.selectAndSave')}
              </p>
              <div className="text-nkz-sm text-nkz-text-primary">
                {pfAlt.label}
              </div>
              <div className="text-nkz-xs text-nkz-text-secondary flex gap-2">
                <span>{(pfAlt.distance_m / 1000).toFixed(2)} km</span>
                <span>· {pfAlt.cumulative_climb_m?.toFixed(0)} m climb</span>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={() => handleSavePfAlt(pfAlt)}
                  className="flex-1 py-1.5 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent hover:opacity-90"
                  style={{ backgroundColor: accent.base }}
                >
                  {t('actions.save')}
                </button>
              </div>
            </div>
          )}

          {(pfState === 'picking-a' || pfState === 'picking-b') && (
            <button
              onClick={cancelPf}
              className="w-full py-1.5 text-nkz-xs text-nkz-text-secondary hover:text-nkz-text-primary"
            >
              Cancelar
            </button>
          )}
        </div>

        <a
          href={`/gis-routing?parcel=${encodeURIComponent(selectedEntityId)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-1.5 py-2 rounded-nkz-md text-nkz-sm font-semibold border border-nkz-accent text-nkz-text-accent hover:bg-nkz-surface transition-colors"
        >
          <ExternalLink className="w-3.5 h-3.5" />
          {t('zoning.openModule')}
        </a>
      </div>
    </SlotShell>
  );
};
