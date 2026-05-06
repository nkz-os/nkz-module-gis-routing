/**
 * RoutingDesigner — Main route generation component.
 *
 * Allows users to configure A-B line parameters, generate swaths,
 * and export in multiple formats (ISOXML, GeoJSON, GPX).
 * Fetches real parcel and equipment data from Orion-LD via the module backend.
 */
import React, { useState, useCallback, useEffect } from 'react';
import { useTranslation } from '@nekazari/sdk';
import {
  MapPin,
  Settings2,
  Tractor,
  Ruler,
  Compass,
  Loader2,
  Download,
  AlertCircle,
  RefreshCw,
  CheckCircle2,
  ClipboardList,
  Layers,
} from 'lucide-react';
import { api, type OperationSummary, type ZoneData, type ActiveOperationInfo, ApiError } from '../services/api';
import manifest from '../../manifest.json';

const NS = 'gis-routing';
const { accent } = manifest;

interface ParcelOption { id: string; name: string; area?: number }
interface EquipmentOption {
  id: string;
  name: string;
  category?: string;
  implementWidth?: number;
  trackWidth?: number;
  wheelbase?: number;
  gpsOffsetX?: number;
  gpsOffsetY?: number;
  gpsOffsetZ?: number;
  hitchType?: string;
  hitchOffsetX?: number;
  implementLength?: number;
  implementOffsetX?: number;
  steeringType?: string;
  steeringAxles?: string;
}
type OperationType = 'spraying' | 'fertilizing' | 'seeding' | 'tillage';

const RoutingDesigner: React.FC = () => {
  const { t } = useTranslation(NS);

  const [parcels, setParcels] = useState<ParcelOption[]>([]);
  const [parcelsLoading, setParcelsLoading] = useState(true);
  const [parcelsError, setParcelsError] = useState<string | null>(null);
  const [parcelId, setParcelId] = useState<string | null>(null);
  const [parcelGeometry, setParcelGeometry] = useState<any>(null);

  const [equipment, setEquipment] = useState<EquipmentOption[]>([]);
  const [equipLoading, setEquipLoading] = useState(true);
  const [equipError, setEquipError] = useState<string | null>(null);
  const [tractorId, setTractorId] = useState<string | null>(null);
  const [implementId, setImplementId] = useState<string | null>(null);

  const [heading, setHeading] = useState(0);
  const [width, setWidth] = useState(24);
  const [operationType, setOperationType] = useState<OperationType>('spraying');
  const [demCorrection, setDemCorrection] = useState(false);
  const [vraEnabled, setVraEnabled] = useState(false);
  const [baseRate, setBaseRate] = useState(100);
  const [rateUnit] = useState('l_ha');
  const [zones, setZones] = useState<ZoneData[]>([]);
  const [zonesLoading, setZonesLoading] = useState(false);
  const [zonesError, setZonesError] = useState<string | null>(null);
  const [selectedZoneIds, setSelectedZoneIds] = useState<string[]>([]);

  const [generating, setGenerating] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState<string | null>(null);
  const [lastOperationId, setLastOperationId] = useState<string | null>(null);
  const [operations, setOperations] = useState<OperationSummary[]>([]);
  const [operationsLoading, setOperationsLoading] = useState(false);
  const [operationsError, setOperationsError] = useState<string | null>(null);
  const [closingOperationId, setClosingOperationId] = useState<string | null>(null);
  const [startingOperationId, setStartingOperationId] = useState<string | null>(null);
  const [coverageByOperationId, setCoverageByOperationId] = useState<Record<string, string>>({});
  const [trajectoryAlternatives, setTrajectoryAlternatives] = useState<
    Array<{ id: string; heading_deg: number; swath_count: number }>
  >([]);
  const [selectedAlternativeId, setSelectedAlternativeId] = useState<string | null>(null);
  const [activeRemoteOperation, setActiveRemoteOperation] = useState<ActiveOperationInfo | null>(null);

  const loadActive = useCallback(async () => {
    try {
      const res = await api.getActiveOperation();
      setActiveRemoteOperation(res?.data?.operation ?? null);
    } catch {
      setActiveRemoteOperation(null);
    }
  }, []);

  useEffect(() => {
    loadActive();
  }, [loadActive]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setParcelsLoading(true);
      setParcelsError(null);
      try {
        const data = await api.listParcels();
        if (!cancelled) setParcels(data || []);
      } catch (err: any) { if (!cancelled) setParcelsError(err?.message || t('errors.generateFailed')); }
      finally { if (!cancelled) setParcelsLoading(false); }
    }
    load();
    return () => { cancelled = true; };
  }, [t]);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      setEquipLoading(true);
      setEquipError(null);
      try {
        const data = await api.listEquipment();
        if (!cancelled) setEquipment(data || []);
      } catch (err: any) { if (!cancelled) setEquipError(err?.message || t('errors.generateFailed')); }
      finally { if (!cancelled) setEquipLoading(false); }
    }
    load();
    return () => { cancelled = true; };
  }, [t]);

  useEffect(() => {
    if (!parcelId) { setParcelGeometry(null); return; }
    let cancelled = false;
    async function load() {
      try {
        const data = await api.getParcelGeometry(parcelId!);
        if (!cancelled && data?.geometry) setParcelGeometry(data.geometry);
      } catch { if (!cancelled) setParcelGeometry(null); }
    }
    load();
    return () => { cancelled = true; };
  }, [parcelId]);

  const loadOperations = useCallback(async () => {
    setOperationsLoading(true);
    setOperationsError(null);
    try {
      const data = await api.listOperations(20);
      setOperations(data || []);
    } catch (err: any) {
      setOperationsError(err?.message || t('operations.loadError'));
    } finally {
      setOperationsLoading(false);
      void loadActive();
    }
  }, [t, loadActive]);

  useEffect(() => {
    loadOperations();
  }, [loadOperations]);

  useEffect(() => {
    if (!parcelId || !vraEnabled) {
      setZones([]);
      setSelectedZoneIds([]);
      setZonesError(null);
      return;
    }
    let cancelled = false;
    const currentParcelId = parcelId;
    async function loadZones() {
      setZonesLoading(true);
      setZonesError(null);
      try {
        const response = await api.getZones(currentParcelId);
        if (!cancelled) {
          const zoneList = response?.data?.zones || [];
          setZones(zoneList);
          setSelectedZoneIds(zoneList.map((z) => z.id));
        }
      } catch (err: any) {
        if (!cancelled) {
          setZones([]);
          setSelectedZoneIds([]);
          setZonesError(err?.message || t('zoning.generateError'));
        }
      } finally {
        if (!cancelled) setZonesLoading(false);
      }
    }
    loadZones();
    return () => { cancelled = true; };
  }, [parcelId, vraEnabled, t]);

  const canGenerate = Boolean(
    parcelId && parcelGeometry && width > 0 && tractorId && implementId,
  );
  const tractors = equipment.filter((eq) => (eq.category || '').toLowerCase() === 'tractor');
  const implementOptions = equipment.filter((eq) => (eq.category || '').toLowerCase() !== 'tractor');
  const selectedTractor = tractors.find((eq) => eq.id === tractorId) || null;
  const selectedImplement = implementOptions.find((eq) => eq.id === implementId) || null;
  const sdmMessages = getSdmValidationMessages(
    operationType,
    selectedTractor,
    selectedImplement,
    t,
  );

  const handleGenerate = useCallback(async () => {
    if (!canGenerate) return;
    setGenerating(true);
    setError(null);
    setResult(null);
    try {
      const body: any = {
        parcel_geometry: parcelGeometry || { type: 'Polygon', coordinates: [] },
        start_point: parcelGeometry
          ? extractCentroid(parcelGeometry)
          : [-1.5, 42.5],
        heading_deg: heading,
        width_m: width,
        parcel_id: parcelId || undefined,
        tractor_id: tractorId || undefined,
        implement_id: implementId || undefined,
        operation_type: operationType,
        dem_correction: demCorrection,
        persist: true,
        selected_alternative_id: selectedAlternativeId || undefined,
      };

      const res: any = vraEnabled
        ? await api.generateWithVRA({
            ...body,
            base_rate: baseRate,
            rate_unit: rateUnit,
            zone_ids: selectedZoneIds,
          })
        : await api.generate(body);

      setResult(res);
      if (Array.isArray(res?.alternatives) && res.alternatives.length > 0) {
        setTrajectoryAlternatives(res.alternatives);
        const sel = res?.data?.properties?.selected_alternative_id;
        setSelectedAlternativeId(sel || res.alternatives[0]?.id || null);
      } else {
        setTrajectoryAlternatives([]);
        setSelectedAlternativeId(null);
      }
      const opId = res?.data?.properties?.operation_id;
      if (opId) setLastOperationId(opId);
      await loadOperations();
    } catch (err: any) {
      setError(err?.message || t('errors.generateFailed'));
    } finally {
      setGenerating(false);
    }
  }, [
    baseRate,
    canGenerate,
    demCorrection,
    heading,
    implementId,
    loadOperations,
    operationType,
    parcelGeometry,
    parcelId,
    rateUnit,
    selectedAlternativeId,
    selectedZoneIds,
    t,
    tractorId,
    vraEnabled,
    width,
  ]);

  const handleCloseOperation = useCallback(async (operationId: string) => {
    setClosingOperationId(operationId);
    setOperationsError(null);
    try {
      await api.closeOperationSession(operationId, new Date().toISOString(), 'ended');
      await loadOperations();
    } catch (err: any) {
      setOperationsError(err?.message || t('operations.closeError'));
    } finally {
      setClosingOperationId(null);
    }
  }, [loadOperations, t]);

  const handleStartOperation = useCallback(async (operationId: string) => {
    setStartingOperationId(operationId);
    setOperationsError(null);
    try {
      await api.startOperationSession(operationId, new Date().toISOString(), 'in_progress');
      await loadOperations();
    } catch (err: any) {
      if (err instanceof ApiError && err.status === 409) {
        const conflictId = err.body?.detail?.error?.active_operation_id;
        setOperationsError(
          conflictId
            ? t('operations.activeConflict', { id: conflictId })
            : t('operations.startError'),
        );
      } else {
        setOperationsError(err?.message || t('operations.startError'));
      }
    } finally {
      setStartingOperationId(null);
    }
  }, [loadOperations, t]);

  const handleLoadCoverage = useCallback(async (operationId: string) => {
    setOperationsError(null);
    try {
      const response = await api.getOperationCoverage(operationId);
      const summary = summarizeCoverage(response?.data?.geometry, t);
      setCoverageByOperationId((prev) => ({ ...prev, [operationId]: summary }));
    } catch (err: any) {
      setOperationsError(err?.message || t('operations.coverageError'));
    }
  }, [t]);

  return (
    <div className="p-nkz-lg max-w-2xl mx-auto space-y-nkz-stack">
      <div>
        <h2 className="text-nkz-lg font-bold text-nkz-text-primary flex items-center gap-nkz-sm">
          <MapPin className="w-5 h-5 text-nkz-text-accent" />
          {t('title')}
        </h2>
        <p className="text-nkz-sm text-nkz-text-secondary mt-1">{t('subtitle')}</p>
      </div>

      {activeRemoteOperation ? (
        <div
          className="flex items-start gap-nkz-sm rounded-nkz-lg border p-nkz-md text-nkz-sm"
          style={{ borderColor: accent.base, backgroundColor: accent.soft + '22' }}
        >
          <ClipboardList className="w-5 h-5 flex-shrink-0 mt-0.5" style={{ color: accent.base }} />
          <div>
            <p className="font-semibold text-nkz-text-primary">{t('operations.activeBannerTitle')}</p>
            <p className="text-nkz-xs text-nkz-text-secondary break-all">
              {activeRemoteOperation.name || activeRemoteOperation.id}
            </p>
            <p className="text-[11px] text-nkz-text-secondary mt-1">
              {t(`operationStatus.${activeRemoteOperation.status || 'in_progress'}`)}
            </p>
          </div>
        </div>
      ) : null}

      {error && (
        <div className="flex items-start gap-nkz-sm bg-nkz-surface border border-nkz-accent rounded-nkz-md p-nkz-md text-nkz-sm text-nkz-text-error">
          <AlertCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-nkz-stack">
        <h3 className="text-nkz-sm font-semibold text-nkz-text-primary">{t('workflow.plan')}</h3>

        <div className="grid grid-cols-2 gap-nkz-md">
          <div>
            <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
              {t('parameters.operationType')}
            </label>
            <select
              value={operationType}
              onChange={(e) => setOperationType(e.target.value as OperationType)}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            >
              <option value="spraying">{t('operationType.spraying')}</option>
              <option value="fertilizing">{t('operationType.fertilizing')}</option>
              <option value="seeding">{t('operationType.seeding')}</option>
              <option value="tillage">{t('operationType.tillage')}</option>
            </select>
          </div>
          <div className="flex items-end">
            <label className="flex items-center gap-nkz-sm cursor-pointer">
              <input
                type="checkbox"
                checked={demCorrection}
                onChange={(e) => setDemCorrection(e.target.checked)}
                className="rounded-nkz-md border-nkz-default text-nkz-text-accent focus:ring-nkz-accent"
              />
              <span className="text-nkz-sm font-medium text-nkz-text-primary">{t('parameters.demCorrection')}</span>
            </label>
          </div>
        </div>

        <h3 className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-nkz-sm">
          <Settings2 className="w-4 h-4" />
          {t('parameters.heading')} &amp; {t('parameters.width')}
        </h3>

        <div className="grid grid-cols-2 gap-nkz-md">
          <div>
            <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1 flex items-center gap-1">
              <Compass className="w-3.5 h-3.5" />
              {t('parameters.heading')}
            </label>
            <input
              type="number" min={0} max={359} value={heading}
              onChange={(e) => setHeading(Number(e.target.value) % 360)}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            />
          </div>
          <div>
            <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1 flex items-center gap-1">
              <Ruler className="w-3.5 h-3.5" />
              {t('parameters.width')}
            </label>
            <input
              type="number" min={1} max={120} value={width}
              onChange={(e) => setWidth(Number(e.target.value))}
              className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
            />
          </div>
        </div>

        <div className="pt-2 border-t border-nkz-default">
          <h3 className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-nkz-sm mb-3">
            <Tractor className="w-4 h-4" />
            {t('equipment.label')}
          </h3>
          <div className="grid grid-cols-2 gap-nkz-md">
            <div>
              <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                {t('equipment.tractorLabel')}
              </label>
              {equipLoading ? (
                <span className="text-nkz-xs text-nkz-text-secondary">
                  <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                  {t('loading')}
                </span>
              ) : equipError ? (
                <div className="text-nkz-xs text-nkz-text-error">
                  <AlertCircle className="w-3 h-3 inline mr-1" />
                  {equipError}
                  <button
                    onClick={() => { setEquipLoading(true); setEquipError(null); api.listEquipment().then(d => setEquipment(d || [])).catch((e: any) => setEquipError(e?.message)).finally(() => setEquipLoading(false)); }}
                    className="ml-2 text-nkz-text-accent hover:underline"
                  >
                    {t('actions.retry')}
                  </button>
                </div>
              ) : (
                <select
                  value={tractorId || ''}
                  onChange={(e) => setTractorId(e.target.value || null)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
                >
                  <option value="">{t('equipment.selectTractor')}</option>
                  {tractors.map((eq) => (
                    <option key={eq.id} value={eq.id}>
                      {eq.name}{eq.category ? ` (${eq.category})` : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
            <div>
              <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                {t('equipment.implementLabel')}
              </label>
              {equipLoading ? (
                <span className="text-nkz-xs text-nkz-text-secondary">
                  <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                  {t('loading')}
                </span>
              ) : (
                <select
                  value={implementId || ''}
                  onChange={(e) => setImplementId(e.target.value || null)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
                >
                  <option value="">{t('equipment.selectImplement')}</option>
                  {implementOptions.map((eq) => (
                    <option key={eq.id} value={eq.id}>
                      {eq.name}{eq.category ? ` (${eq.category})` : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>

          {(selectedTractor || selectedImplement) && (
            <div className="mt-3 border border-nkz-default rounded-nkz-md p-3 bg-nkz-surface-alt">
              <p className="text-nkz-xs font-medium text-nkz-text-secondary mb-2">
                {t('equipment.kinematicsTitle')}
              </p>
              <div className="grid grid-cols-2 gap-2 text-[11px] text-nkz-text-secondary">
                <span>{t('equipment.trackWidth')}: {formatMeters(selectedTractor?.trackWidth)}</span>
                <span>{t('equipment.wheelbase')}: {formatMeters(selectedTractor?.wheelbase)}</span>
                <span>{t('equipment.gpsOffsetX')}: {formatMeters(selectedTractor?.gpsOffsetX)}</span>
                <span>{t('equipment.gpsOffsetY')}: {formatMeters(selectedTractor?.gpsOffsetY)}</span>
                <span>{t('equipment.gpsOffsetZ')}: {formatMeters(selectedTractor?.gpsOffsetZ)}</span>
                <span>{t('equipment.steering')}: {selectedTractor?.steeringType || '-'}</span>
                <span>{t('equipment.hitchType')}: {selectedImplement?.hitchType || '-'}</span>
                <span>{t('equipment.hitchOffsetX')}: {formatMeters(selectedImplement?.hitchOffsetX)}</span>
                <span>{t('equipment.implementLength')}: {formatMeters(selectedImplement?.implementLength)}</span>
                <span>{t('equipment.implementOffsetX')}: {formatMeters(selectedImplement?.implementOffsetX)}</span>
                <span>{t('equipment.implementWidth')}: {formatMeters(selectedImplement?.implementWidth)}</span>
              </div>
            </div>
          )}

          <div className="grid grid-cols-2 gap-nkz-md">
            <div>
              <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                {t('parcel.label')}
              </label>
              {parcelsLoading ? (
                <span className="text-nkz-xs text-nkz-text-secondary">
                  <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                  {t('loading')}
                </span>
              ) : parcelsError ? (
                <div className="text-nkz-xs text-nkz-text-error">
                  <AlertCircle className="w-3 h-3 inline mr-1" />
                  {parcelsError}
                  <button
                    onClick={() => {
                      setParcelsLoading(true); setParcelsError(null);
                      api.listParcels().then(d => setParcels(d || [])).catch((e: any) => setParcelsError(e?.message)).finally(() => setParcelsLoading(false));
                    }}
                    className="ml-2 text-nkz-text-accent hover:underline"
                  >
                    {t('actions.retry')}
                  </button>
                </div>
              ) : parcels.length === 0 ? (
                <div className="text-nkz-xs text-nkz-text-secondary">
                  <p>{t('parcel.empty')}</p>
                  <button
                    onClick={() => {
                      setParcelsLoading(true);
                      api.listParcels().then(d => setParcels(d || [])).finally(() => setParcelsLoading(false));
                    }}
                    className="mt-1 flex items-center gap-1 text-nkz-text-accent hover:underline"
                  >
                    <RefreshCw className="w-3 h-3" /> {t('actions.retry')}
                  </button>
                </div>
              ) : (
                <select
                  value={parcelId || ''}
                  onChange={(e) => setParcelId(e.target.value || null)}
                  className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
                >
                  <option value="">{t('parcel.select')}</option>
                  {parcels.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.name}{p.area ? ` (${p.area.toFixed(1)} ha)` : ''}
                    </option>
                  ))}
                </select>
              )}
            </div>
          </div>
        </div>

        <div className="pt-2 border-t border-nkz-default">
          <label className="flex items-center gap-nkz-sm cursor-pointer">
            <input
              type="checkbox" checked={vraEnabled}
              onChange={(e) => setVraEnabled(e.target.checked)}
              className="rounded-nkz-md border-nkz-default text-nkz-text-accent focus:ring-nkz-accent"
            />
            <span className="text-nkz-sm font-medium text-nkz-text-primary">
              {t('vra.enabled')}
            </span>
          </label>
          {vraEnabled && (
            <div className="mt-3 space-y-3">
              <div className="grid grid-cols-2 gap-nkz-md">
                <div>
                  <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                    {t('vra.baseRate')}
                  </label>
                  <input
                    type="number" min={0} value={baseRate}
                    onChange={(e) => setBaseRate(Number(e.target.value))}
                    className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm"
                  />
                </div>
                <div>
                  <label className="block text-nkz-xs font-medium text-nkz-text-secondary mb-1">
                    {t('vra.rateUnit')}
                  </label>
                  <input
                    type="text" value={rateUnit} disabled
                    className="w-full border border-nkz-default rounded-nkz-md px-3 py-2 text-nkz-sm bg-nkz-surface-alt text-nkz-text-secondary"
                  />
                </div>
              </div>

              <div className="border border-nkz-default rounded-nkz-md p-3 space-y-2">
                <div className="flex items-center justify-between">
                  <p className="text-nkz-xs font-medium text-nkz-text-secondary flex items-center gap-1">
                    <Layers className="w-3.5 h-3.5" />
                    {t('vra.zoneSelection')}
                  </p>
                  {zones.length > 0 && (
                    <button
                      type="button"
                      className="text-nkz-xs text-nkz-text-accent hover:underline"
                      onClick={() => {
                        const selectAll = selectedZoneIds.length !== zones.length;
                        setSelectedZoneIds(selectAll ? zones.map((z) => z.id) : []);
                      }}
                    >
                      {selectedZoneIds.length === zones.length ? t('vra.clearAll') : t('vra.selectAll')}
                    </button>
                  )}
                </div>

                {zonesLoading && (
                  <p className="text-nkz-xs text-nkz-text-secondary">
                    <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
                    {t('zoning.loadingZones')}
                  </p>
                )}
                {zonesError && !zonesLoading && (
                  <p className="text-nkz-xs text-nkz-text-error">{zonesError}</p>
                )}
                {!zonesLoading && !zonesError && zones.length === 0 && (
                  <p className="text-nkz-xs text-nkz-text-secondary">{t('vra.noZonesForParcel')}</p>
                )}
                {!zonesLoading && zones.length > 0 && (
                  <div className="space-y-2 max-h-32 overflow-auto pr-1">
                    {zones.map((zone) => (
                      <label key={zone.id} className="flex items-center justify-between gap-3 text-nkz-xs">
                        <span className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            checked={selectedZoneIds.includes(zone.id)}
                            onChange={(e) => {
                              setSelectedZoneIds((prev) => (
                                e.target.checked
                                  ? [...prev, zone.id]
                                  : prev.filter((id) => id !== zone.id)
                              ));
                            }}
                            className="rounded-nkz-md border-nkz-default text-nkz-text-accent focus:ring-nkz-accent"
                          />
                          <span className="text-nkz-text-primary">
                            {t('zoning.zoneLabel', { id: zone.zone_id })}
                          </span>
                        </span>
                        <span className="text-nkz-text-secondary">
                          {zone.prescription_rate?.toFixed(2)}x
                        </span>
                      </label>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>

      <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-3">
        <h3 className="text-nkz-sm font-semibold text-nkz-text-primary">{t('workflow.validate')}</h3>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2 text-nkz-xs">
          <div className="flex items-center gap-2">
            <CheckCircle2 className={`w-3.5 h-3.5 ${parcelId ? 'text-nkz-text-success' : 'text-nkz-text-secondary'}`} />
            <span>{parcelId ? t('validation.parcelReady') : t('validation.parcelMissing')}</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className={`w-3.5 h-3.5 ${parcelGeometry ? 'text-nkz-text-success' : 'text-nkz-text-secondary'}`} />
            <span>{parcelGeometry ? t('validation.geometryReady') : t('validation.geometryMissing')}</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className={`w-3.5 h-3.5 ${width > 0 ? 'text-nkz-text-success' : 'text-nkz-text-secondary'}`} />
            <span>{width > 0 ? t('validation.widthReady') : t('validation.widthMissing')}</span>
          </div>
          <div className="flex items-center gap-2">
            <CheckCircle2 className={`w-3.5 h-3.5 ${tractorId && implementId ? 'text-nkz-text-success' : 'text-nkz-text-secondary'}`} />
            <span>{tractorId && implementId ? t('validation.equipmentReady') : t('validation.equipmentMissing')}</span>
          </div>
        </div>
        {sdmMessages.length > 0 ? (
          <div className="mt-3 rounded-nkz-md border border-nkz-accent bg-nkz-surface-alt p-3 space-y-1">
            <p className="text-nkz-xs font-medium text-nkz-text-secondary">{t('validation.sdmTitle')}</p>
            <ul className="list-disc pl-4 text-nkz-xs text-nkz-text-secondary space-y-0.5">
              {sdmMessages.map((msg) => (
                <li key={msg}>{msg}</li>
              ))}
            </ul>
          </div>
        ) : null}
      </div>

      {trajectoryAlternatives.length > 0 ? (
        <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-3">
          <h3 className="text-nkz-sm font-semibold text-nkz-text-primary">{t('trajectory.title')}</h3>
          <p className="text-nkz-xs text-nkz-text-secondary">{t('trajectory.hint')}</p>
          <div className="space-y-2">
            {trajectoryAlternatives.map((alt) => (
              <label
                key={alt.id}
                className="flex items-center gap-2 text-nkz-xs cursor-pointer"
              >
                <input
                  type="radio"
                  name="traj-alt"
                  checked={selectedAlternativeId === alt.id}
                  onChange={() => setSelectedAlternativeId(alt.id)}
                  className="border-nkz-default text-nkz-text-accent focus:ring-nkz-accent"
                />
                <span className="text-nkz-text-primary">
                  {t('trajectory.optionLabel', {
                    heading: Math.round(alt.heading_deg * 10) / 10,
                    swaths: alt.swath_count,
                  })}
                </span>
              </label>
            ))}
          </div>
          <button
            type="button"
            onClick={handleGenerate}
            disabled={generating || !canGenerate}
            className="w-full min-h-[40px] font-semibold text-nkz-xs rounded-nkz-md border border-nkz-default hover:bg-nkz-surface-alt disabled:opacity-50 text-nkz-text-primary"
          >
            {t('trajectory.applySelection')}
          </button>
        </div>
      ) : null}

      <button
        onClick={handleGenerate} disabled={generating || !canGenerate}
        className="w-full min-h-[48px] font-bold text-nkz-sm rounded-nkz-lg transition-colors flex items-center justify-center gap-nkz-sm text-nkz-text-on-accent"
        style={{
          backgroundColor: generating ? accent.soft : accent.base,
          opacity: generating || !canGenerate ? 0.7 : 1,
        }}
      >
        {generating ? (
          <><Loader2 className="w-4 h-4 animate-spin" />{t('actions.generating')}</>
        ) : (
          t('workflow.execute')
        )}
      </button>

      {lastOperationId && (
        <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-3">
          <div className="space-y-2">
            <h3 className="text-nkz-sm font-semibold text-nkz-text-primary">{t('handoff.title')}</h3>
            <p className="text-nkz-xs text-nkz-text-secondary">{t('handoff.body')}</p>
            <div className="flex flex-wrap items-center gap-2">
              <code className="text-[11px] bg-nkz-surface-alt px-2 py-1 rounded break-all max-w-full">
                {lastOperationId}
              </code>
              <button
                type="button"
                onClick={() => {
                  if (navigator.clipboard?.writeText) {
                    void navigator.clipboard.writeText(lastOperationId);
                  }
                }}
                className="text-nkz-xs text-nkz-text-accent hover:underline"
              >
                {t('handoff.copyId')}
              </button>
            </div>
          </div>
          <h3 className="text-nkz-sm font-semibold text-nkz-text-primary flex items-center gap-nkz-sm">
            <Download className="w-4 h-4" />
            {t('actions.export')}
          </h3>
          <div className="flex gap-nkz-sm">
            <button
              onClick={() => window.open(api.getExportUrl(lastOperationId, 'isoxml'), '_blank')}
              className="flex-1 min-h-[48px] font-bold text-nkz-xs uppercase rounded-nkz-md border border-nkz-accent transition-colors"
              style={{ backgroundColor: accent.strong, color: accent.base }}
            >
              {t('export.isoxml')}
            </button>
            <button
              onClick={() => window.open(api.getExportUrl(lastOperationId, 'geojson'), '_blank')}
              className="flex-1 min-h-[48px] font-bold text-nkz-xs uppercase rounded-nkz-md border border-nkz-accent text-nkz-text-success transition-colors"
              style={{ backgroundColor: accent.strong }}
            >
              {t('export.geojson')}
            </button>
            <button
              onClick={() => window.open(api.getExportUrl(lastOperationId, 'gpx'), '_blank')}
              className="flex-1 min-h-[48px] font-bold text-nkz-xs uppercase rounded-nkz-md border border-nkz-accent text-nkz-text-accent transition-colors"
              style={{ backgroundColor: accent.strong }}
            >
              {t('export.gpx')}
            </button>
          </div>
        </div>
      )}

      {result?.data?.properties && (
        <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md">
          <dl className="grid grid-cols-2 gap-nkz-md text-nkz-sm">
            <div>
              <dt className="text-nkz-xs text-nkz-text-secondary">{t('parameters.heading')}</dt>
              <dd className="font-semibold text-nkz-text-primary">{result.data.properties.heading_deg}&deg;</dd>
            </div>
            <div>
              <dt className="text-nkz-xs text-nkz-text-secondary">{t('parameters.width')}</dt>
              <dd className="font-semibold text-nkz-text-primary">{result.data.properties.width_m} m</dd>
            </div>
            <div>
              <dt className="text-nkz-xs text-nkz-text-secondary">{t('parameters.swaths')}</dt>
              <dd className="font-semibold text-nkz-text-primary">{result.data.properties.swath_count}</dd>
            </div>
            <div>
              <dt className="text-nkz-xs text-nkz-text-secondary">{t('parameters.operationType')}</dt>
              <dd className="font-semibold text-nkz-text-primary">{t(`operationType.${operationType}`)}</dd>
            </div>
            {result.data.properties.vra_enabled !== undefined && (
              <div>
                <dt className="text-nkz-xs text-nkz-text-secondary">{t('vra.label')}</dt>
                <dd className="font-semibold text-nkz-text-primary">
                  {result.data.properties.vra_enabled ? t('common.enabled') : t('common.disabled')}
                </dd>
              </div>
            )}
          </dl>
          {result?.prescription_map?.features?.length > 0 && (
            <PrescriptionSummary
              t={t}
              features={result.prescription_map.features}
              rateUnit={rateUnit}
            />
          )}
        </div>
      )}

      <div className="bg-nkz-surface rounded-nkz-lg border border-nkz-default p-nkz-md space-y-3">
        <div className="flex items-center justify-between">
          <h3 className="text-nkz-sm font-semibold text-nkz-text-primary">{t('operations.title')}</h3>
          <button
            onClick={loadOperations}
            className="text-nkz-xs text-nkz-text-accent hover:underline flex items-center gap-1"
          >
            <RefreshCw className="w-3 h-3" />
            {t('operations.refresh')}
          </button>
        </div>

        {operationsError && (
          <p className="text-nkz-xs text-nkz-text-error">{operationsError}</p>
        )}
        {operationsLoading && (
          <p className="text-nkz-xs text-nkz-text-secondary">
            <Loader2 className="w-3 h-3 inline animate-spin mr-1" />
            {t('loading')}
          </p>
        )}
        {!operationsLoading && operations.length === 0 && (
          <p className="text-nkz-xs text-nkz-text-secondary">{t('operations.empty')}</p>
        )}

        {!operationsLoading && operations.length > 0 && (
          <div className="space-y-2 max-h-72 overflow-auto pr-1">
            {operations.map((op) => (
              <div
                key={op.id}
                className={`border rounded-nkz-md p-3 ${
                  op.status === 'in_progress'
                    ? 'border-nkz-accent bg-nkz-surface-alt ring-2 ring-nkz-accent/40'
                    : 'border-nkz-default'
                }`}
              >
                <div className="flex items-center justify-between gap-2">
                  <div>
                    <p className="text-nkz-xs font-medium text-nkz-text-primary truncate">{op.id}</p>
                    <p className="text-[11px] text-nkz-text-secondary">
                      {t(`operationType.${(op.operation_type || 'spraying') as OperationType}`)} · {t(`operationStatus.${op.status || 'planned'}`)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => handleStartOperation(op.id)}
                      disabled={
                        startingOperationId === op.id
                        || op.status === 'in_progress'
                        || op.status === 'ended'
                        || op.status === 'finished'
                        || op.status === 'cancelled'
                        || Boolean(
                          activeRemoteOperation
                          && activeRemoteOperation.id !== op.id
                          && op.status !== 'in_progress',
                        )
                      }
                      className="text-[11px] px-2 py-1 rounded border border-nkz-default hover:bg-nkz-surface-alt disabled:opacity-50"
                    >
                      {startingOperationId === op.id ? t('operations.starting') : t('operations.start')}
                    </button>
                    <button
                      onClick={() => handleLoadCoverage(op.id)}
                      className="text-[11px] px-2 py-1 rounded border border-nkz-default hover:bg-nkz-surface-alt"
                    >
                      {t('operations.coverage')}
                    </button>
                    <button
                      onClick={() => handleCloseOperation(op.id)}
                      disabled={closingOperationId === op.id || op.status === 'ended' || op.status === 'finished' || op.status === 'cancelled'}
                      className="text-[11px] px-2 py-1 rounded border border-nkz-default hover:bg-nkz-surface-alt disabled:opacity-50"
                    >
                      {closingOperationId === op.id ? t('operations.closing') : t('operations.close')}
                    </button>
                  </div>
                </div>
                {coverageByOperationId[op.id] && (
                  <p className="mt-2 text-[11px] text-nkz-text-secondary">{coverageByOperationId[op.id]}</p>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

function getSdmValidationMessages(
  operationType: OperationType,
  tractor: EquipmentOption | null,
  implement: EquipmentOption | null,
  t: (k: string) => string,
): string[] {
  const out: string[] = [];
  if (!tractor || !implement) {
    out.push(t('validation.equipmentMissing'));
    return out;
  }
  const gpsMissing =
    typeof tractor.gpsOffsetX !== 'number'
    || typeof tractor.gpsOffsetY !== 'number'
    || typeof tractor.gpsOffsetZ !== 'number';
  if (gpsMissing) {
    out.push(t('validation.sdmGpsOffsets'));
  }
  if (operationType === 'spraying' || operationType === 'fertilizing') {
    if (typeof implement.implementWidth !== 'number') {
      out.push(t('validation.sdmImplementWidth'));
    }
  }
  if (operationType === 'tillage') {
    if (typeof tractor.trackWidth !== 'number') {
      out.push(t('validation.sdmTrackWidth'));
    }
    if (typeof tractor.wheelbase !== 'number') {
      out.push(t('validation.sdmWheelbase'));
    }
  }
  if (operationType === 'seeding') {
    if (typeof implement.hitchOffsetX !== 'number') {
      out.push(t('validation.sdmHitchOffset'));
    }
  }
  return out;
}

function extractCentroid(geometry: any): [number, number] {
  try {
    if (geometry.type === 'Point') return geometry.coordinates as [number, number];
    if (geometry.type === 'Polygon') {
      const ring = geometry.coordinates?.[0];
      if (Array.isArray(ring) && ring.length > 0) {
        const lng = ring.reduce((s: number, c: number[]) => s + c[0], 0) / ring.length;
        const lat = ring.reduce((s: number, c: number[]) => s + c[1], 0) / ring.length;
        return [lng, lat];
      }
    }
    if (geometry.type === 'MultiPolygon') {
      const ring = geometry.coordinates?.[0]?.[0];
      if (Array.isArray(ring) && ring.length > 0) {
        const lng = ring.reduce((s: number, c: number[]) => s + c[0], 0) / ring.length;
        const lat = ring.reduce((s: number, c: number[]) => s + c[1], 0) / ring.length;
        return [lng, lat];
      }
    }
    if (geometry.type === 'LineString') {
      const line = geometry.coordinates;
      if (Array.isArray(line) && line.length > 0) {
        const mid = line[Math.floor(line.length / 2)];
        return [mid[0], mid[1]];
      }
    }
  } catch {}
  return [-1.5, 42.5];
}

export { RoutingDesigner };
export default RoutingDesigner;

function summarizeCoverage(geometry: any, t: (key: string, options?: any) => string): string {
  if (!geometry) return t('operations.coverageNoGeometry');
  const type = geometry.type;
  if (type === 'MultiLineString') {
    const lines = Array.isArray(geometry.coordinates) ? geometry.coordinates.length : 0;
    const points = Array.isArray(geometry.coordinates)
      ? geometry.coordinates.reduce((sum: number, line: any[]) => sum + (Array.isArray(line) ? line.length : 0), 0)
      : 0;
    return t('operations.coverageSummaryLines', { lines, points });
  }
  if (type === 'LineString') {
    const points = Array.isArray(geometry.coordinates) ? geometry.coordinates.length : 0;
    return t('operations.coverageSummaryLine', { points });
  }
  return t('operations.coverageSummaryType', { type: type || 'unknown' });
}

function formatMeters(value?: number): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '-';
  return `${value.toFixed(2)} m`;
}

function PrescriptionSummary({
  t,
  features,
  rateUnit,
}: {
  t: (key: string, options?: any) => string;
  features: Array<{ properties?: { rate?: number; length_m?: number; zone_id?: string | number } }>;
  rateUnit: string;
}) {
  const valid = features.filter((f) => Number.isFinite(f?.properties?.rate) && Number.isFinite(f?.properties?.length_m));
  const segmentCount = valid.length;
  const totalLength = valid.reduce((sum, f) => sum + Number(f.properties?.length_m || 0), 0);
  const averageRate = segmentCount > 0
    ? valid.reduce((sum, f) => sum + Number(f.properties?.rate || 0), 0) / segmentCount
    : 0;
  const zoneCount = new Set(valid.map((f) => String(f.properties?.zone_id || ''))).size;

  return (
    <div className="mt-4 pt-3 border-t border-nkz-default">
      <p className="text-nkz-xs font-medium text-nkz-text-secondary mb-2">{t('vra.prescriptionSummary')}</p>
      <dl className="grid grid-cols-2 gap-2 text-nkz-xs">
        <div>
          <dt className="text-nkz-text-secondary">{t('vra.summarySegments')}</dt>
          <dd className="font-semibold text-nkz-text-primary">{segmentCount}</dd>
        </div>
        <div>
          <dt className="text-nkz-text-secondary">{t('vra.summaryZones')}</dt>
          <dd className="font-semibold text-nkz-text-primary">{zoneCount}</dd>
        </div>
        <div>
          <dt className="text-nkz-text-secondary">{t('vra.summaryLength')}</dt>
          <dd className="font-semibold text-nkz-text-primary">{totalLength.toFixed(1)} m</dd>
        </div>
        <div>
          <dt className="text-nkz-text-secondary">{t('vra.summaryRate')}</dt>
          <dd className="font-semibold text-nkz-text-primary">{averageRate.toFixed(2)} {rateUnit}</dd>
        </div>
      </dl>
    </div>
  );
}
