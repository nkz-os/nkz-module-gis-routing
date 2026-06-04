/**
 * ContextPanelSlot — Viewer cockpit: mode FSM driving gate/no-go, work-route
 * generation, and A→B transit via window-event bridge to GisRoutingMapLayer.
 */
import React, { useEffect, useState } from 'react';
import { SlotShell } from '@nekazari/viewer-kit';
import { useViewer, useTranslation } from '@nekazari/sdk';
import { ExternalLink, Eye, Loader2, MapPin, Flag, Ban, Save, Trash2 } from 'lucide-react';
import { accent } from '../../config/accent';
import { api } from '../../services/api';
import { ModeBar } from '../viewer/ModeBar';
import { ConstraintsStatus } from '../viewer/ConstraintsStatus';
import { WorkRoutePanel } from '../viewer/WorkRoutePanel';
import { TransitPanel, startTransit } from '../viewer/TransitPanel';
import { EV, emitMode, type RoutingMode } from '../viewer/routingMode';

const NS = 'gis-routing';

// ── Local sub-components (extracted from the original flat render) ──────────

const SavedRoutes: React.FC<{
  patterns: any[]; loading: boolean; onShow: (p: any) => void; t: any;
}> = ({ patterns, loading, onShow, t }) => {
  if (loading) {
    return (
      <div className="flex items-center gap-2 text-nkz-text-secondary">
        <Loader2 className="w-4 h-4 animate-spin" />
        <span className="text-nkz-xs">{t('loading')}</span>
      </div>
    );
  }
  if (patterns.length === 0) {
    return (
      <div className="text-center py-3">
        <MapPin className="w-5 h-5 text-nkz-text-muted mx-auto mb-1" />
        <p className="text-nkz-xs text-nkz-text-secondary">{t('patterns.noSaved')}</p>
      </div>
    );
  }
  return (
    <div className="space-y-1.5 max-h-64 overflow-y-auto">
      {patterns.map((p: any) => (
        <div
          key={p.id}
          className="flex items-center gap-2 rounded-nkz-md border border-nkz-default p-2.5 bg-nkz-surface-alt"
        >
          <div className="flex-1 min-w-0">
            <p className="text-nkz-sm font-medium text-nkz-text-primary truncate">{p.name}</p>
            <p className="text-nkz-xs text-nkz-text-secondary">
              {p.pattern_type}
              {p.created_at ? ` · ${new Date(p.created_at * 1000).toLocaleDateString()}` : ''}
            </p>
          </div>
          <button
            onClick={() => onShow(p)}
            className="flex-shrink-0 flex items-center gap-1 px-2.5 py-1.5 rounded-nkz-md text-nkz-xs font-semibold text-nkz-text-on-accent hover:opacity-90 transition-opacity"
            style={{ backgroundColor: accent.base }}
            title={t('patterns.loadFromContext')}
          >
            <Eye className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
    </div>
  );
};

const DrawControls: React.FC<{
  zones: any[]; onRemoveZone: (id: string) => void;
  onSave: () => void; saving: boolean; status: string; t: any;
}> = ({ zones, onRemoveZone, onSave, saving, status, t }) => {
  const markAccess = () => window.dispatchEvent(new CustomEvent(
    EV.activateDraw, { detail: { mode: 'access' } }));
  const drawZone = () => window.dispatchEvent(new CustomEvent(
    EV.activateDraw, { detail: { mode: 'zone' } }));

  return (
    <div className="space-y-2">
      <p className="text-nkz-xs text-nkz-text-secondary">{t('parcelConfig.instructions')}</p>
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
      {zones.length > 0 && (
        <div className="space-y-1 max-h-32 overflow-y-auto">
          {zones.map((z, i) => (
            <div
              key={z.id}
              className="flex items-center justify-between text-nkz-xs bg-nkz-surface-alt rounded-nkz-md px-2 py-1"
            >
              <span>{t('parcelConfig.noGoZones')} {i + 1}</span>
              <button
                onClick={() => onRemoveZone(z.id)}
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
        onClick={onSave}
        disabled={saving}
        className="w-full flex items-center justify-center gap-1.5 py-2 rounded-nkz-md text-nkz-sm font-semibold text-nkz-text-on-accent hover:opacity-90 disabled:opacity-50"
        style={{ backgroundColor: accent.base }}
      >
        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
        {t('parcelConfig.save')}
      </button>
      {status === 'saved' && (
        <p className="text-nkz-xs text-nkz-text-success text-center">{t('parcelConfig.saved')}</p>
      )}
      {status === 'error' && (
        <p className="text-nkz-xs text-nkz-text-error text-center">{t('parcelConfig.saveError')}</p>
      )}
    </div>
  );
};

// ── Main slot component ─────────────────────────────────────────────────────

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
  // Cockpit mode FSM
  const [mode, setMode] = useState<RoutingMode>('idle');

  // Load saved patterns for selected parcel
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
      setMode('idle');
      return;
    }
    let cancelled = false;
    setCfgStatus('idle');
    setMode('idle');
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
      // Tear down BOTH map click tools so none survives a parcel switch.
      window.dispatchEvent(new CustomEvent(EV.activateDraw, { detail: { mode: 'off' } }));
      window.dispatchEvent(new CustomEvent('nekazari:gis-routing:pickPathCancel'));
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
    window.addEventListener(EV.gatePicked, onAccess);
    window.addEventListener(EV.zoneDrawn, onZone);
    return () => {
      window.removeEventListener(EV.gatePicked, onAccess);
      window.removeEventListener(EV.zoneDrawn, onZone);
    };
  }, []);

  // Listen for pathfinding events from GisRoutingMapLayer
  useEffect(() => {
    const onState = (e: Event) => setPfState((e as CustomEvent).detail?.state || 'idle');
    const onAlt = (e: Event) => { setPfAlt((e as CustomEvent).detail); setPfState('done'); };
    window.addEventListener('nekazari:pf:stateChange', onState);
    window.addEventListener(EV.transitAltSelected, onAlt);
    return () => {
      window.removeEventListener('nekazari:pf:stateChange', onState);
      window.removeEventListener(EV.transitAltSelected, onAlt);
    };
  }, []);

  // Mirror map-driven pf state into cockpit mode
  useEffect(() => {
    const transit = ['picking-a', 'picking-b', 'calculating', 'done'] as const;
    if ((transit as readonly string[]).includes(pfState) && pfState !== mode) {
      setMode(pfState as RoutingMode);
    }
  }, [pfState, mode]);

  // ── Mode selector ───────────────────────────────────────────────────────

  const selectMode = (m: RoutingMode) => {
    // Leaving draw modes turns the map draw tool off.
    window.dispatchEvent(new CustomEvent(EV.activateDraw, { detail: { mode: 'off' } }));
    if (mode !== 'idle' && (mode === 'picking-a' || mode === 'picking-b')) {
      window.dispatchEvent(new CustomEvent(EV.transitCancel));
    }
    setMode(m);
    emitMode(m);
    if (m === 'placing-gate') window.dispatchEvent(new CustomEvent(EV.activateDraw, { detail: { mode: 'access' } }));
    if (m === 'drawing-zone') window.dispatchEvent(new CustomEvent(EV.activateDraw, { detail: { mode: 'zone' } }));
    if (m === 'picking-a') { setPfAlt(null); startTransit(); }
  };

  // ── Handlers ─────────────────────────────────────────────────────────────

  const handleShowOnMap = (p: any) => {
    try {
      const geom = typeof p.route_geojson === 'string'
        ? JSON.parse(p.route_geojson)
        : p.route_geojson;
      window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
        detail: { geometry: geom, prescriptionMap: p.vra_prescription_map || null },
      }));
    } catch { /* ignore parse errors */ }
  };

  const handleSavePfAlt = (alt: any) => {
    if (!alt?.geometry) return;
    window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
      detail: { geometry: alt.geometry, prescriptionMap: null },
    }));
    setPfState('idle');
    setPfAlt(null);
    setMode('idle');
  };
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

  const handleSavePfAlt = (alt: any) => {
    if (!alt?.geometry) return;
    window.dispatchEvent(new CustomEvent(EV.routeGenerated, {
      detail: { geometry: alt.geometry, prescriptionMap: null },
    }));
    setPfState('idle');
    setPfAlt(null);
    setMode('idle');
  };

  // ── Empty state (no parcel selected) ────────────────────────────────────

  if (!selectedEntityId || selectedEntityType !== 'AgriParcel') {
    return (
      <SlotShell moduleId="nkz-module-gis-routing" accent={accent}>
        <div className="p-4 text-nkz-sm text-nkz-text-secondary text-center">
          {t('zoning.selectParcel')}
        </div>
      </SlotShell>
    );
  }

  // ── Cockpit render ──────────────────────────────────────────────────────

  return (
    <SlotShell moduleId="nkz-module-gis-routing" accent={accent}>
      <div className="p-4 space-y-3 text-nkz-sm">
        <p className="font-semibold text-nkz-text-primary">{t('title')}</p>
        <ConstraintsStatus hasGate={!!accessPoint} zoneCount={zones.length} />
        <ModeBar mode={mode} onSelect={selectMode} />

        <div className="border-t border-nkz-default pt-3">
          {mode === 'idle' && (
            <SavedRoutes patterns={patterns} loading={loading} onShow={handleShowOnMap} t={t} />
          )}
          {(mode === 'placing-gate' || mode === 'drawing-zone') && (
            <DrawControls zones={zones} onRemoveZone={removeZone}
              onSave={saveCfg} saving={cfgSaving} status={cfgStatus} t={t} />
          )}
          {mode === 'work-route' && <WorkRoutePanel parcelId={selectedEntityId} />}
          {(mode === 'picking-a' || mode === 'picking-b' ||
            mode === 'calculating' || mode === 'done') && (
            <TransitPanel pfState={pfState} alt={pfAlt}
              onSave={handleSavePfAlt}
              onCancel={() => selectMode('idle')} />
          )}
        </div>

        <a
          href={`/gis-routing?parcel=${encodeURIComponent(selectedEntityId)}`}
          target="_blank"
          rel="noopener noreferrer"
          className="flex items-center justify-center gap-1.5 py-2 rounded-nkz-md text-nkz-sm font-semibold border border-nkz-accent text-nkz-text-accent"
        >
          <ExternalLink className="w-3.5 h-3.5" />{t('zoning.openModule')}
        </a>
      </div>
    </SlotShell>
  );
};
