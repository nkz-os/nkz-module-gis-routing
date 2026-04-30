/**
 * ZoningTab — VRA Zoning management tab.
 *
 * Displays existing management zones and allows generating new ones
 * from parcel geometry.
 */
import React, { useState, useEffect, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';
import { Layers, RefreshCw, Loader2, MapPin } from 'lucide-react';
import { api } from '../../services/api';

const NS = 'gis-routing';

interface Zone {
  id: string;
  label: string;
  zoneClass: string;
  areaHa: number;
}

const ZoningTab: React.FC = () => {
  const { t } = useTranslation(NS);
  const [generating, setGenerating] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [zones, setZones] = useState<Zone[]>([]);
  const [loading, setLoading] = useState(false);
  const [numZones, setNumZones] = useState(3);
  const [error, setError] = useState<string | null>(null);

  const handleGenerate = useCallback(async () => {
    setGenerating(true);
    setError(null);
    try {
      const result = await api.generateWithVRA({
        parcel_geometry: { type: 'Polygon', coordinates: [] },
        start_point: [-1.5, 42.5],
        heading_deg: 0,
        width_m: 24,
        base_rate: 100,
        persist: false,
      });
      if (result?.properties?.operation_id) {
        setTaskId(result.properties.operation_id);
      }
    } catch (err: any) {
      setError(err?.message || t('zoning.generateError', 'Error starting zone generation'));
    } finally {
      setGenerating(false);
    }
  }, [t]);

  return (
    <div className="p-4 max-w-2xl mx-auto space-y-6">
      <div>
        <h2 className="text-lg font-bold text-slate-800 flex items-center gap-2">
          <Layers className="w-5 h-5 text-emerald-500" />
          {t('zoning.title', 'VRA Zoning')}
        </h2>
        <p className="text-sm text-slate-500 mt-1">
          {t('zoning.description', 'Generate Variable Rate Application (VRA) management zones.')}
        </p>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded p-3 text-sm text-red-700">
          {error}
        </div>
      )}

      <div className="bg-white rounded-lg border border-slate-200 p-4 space-y-4">
        <div className="flex items-start gap-3">
          <MapPin className="w-5 h-5 text-slate-400 mt-0.5" />
          <div>
            <p className="text-sm text-slate-700">{t('zoning.selectParcel', 'Select a parcel')}</p>
            <p className="text-xs text-slate-400 mt-1">
              {t('zoning.selectParcelHint', 'Access this module from a parcel in the main viewer.')}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          <div className="flex-1">
            <label className="block text-xs font-medium text-slate-600 mb-1">
              {t('zoning.numZones', 'Number of Zones')}
            </label>
            <input
              type="number"
              min={2}
              max={10}
              value={numZones}
              onChange={(e) => setNumZones(Math.max(2, Math.min(10, parseInt(e.target.value) || 2)))}
              className="w-full border border-slate-300 rounded px-3 py-2 text-sm"
            />
            <p className="text-xs text-slate-400 mt-1">
              {t('zoning.numZonesHint', '{{zones}} zones will be created.', { zones: numZones })}
            </p>
          </div>
        </div>

        <button
          onClick={handleGenerate}
          disabled={generating}
          className="w-full min-h-[48px] font-bold text-sm bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-400 text-white rounded-lg transition-colors flex items-center justify-center gap-2"
        >
          {generating ? (
            <>
              <Loader2 className="w-4 h-4 animate-spin" />
              {t('zoning.generating', 'Generating...')}
            </>
          ) : (
            t('zoning.generateBtn', 'Generate VRA Zones')
          )}
        </button>

        {taskId && (
          <div className="text-xs text-slate-500 bg-slate-50 rounded p-2">
            {t('zoning.taskId', 'Task ID: {{taskId}}', { taskId })}
          </div>
        )}
      </div>

      <div className="bg-white rounded-lg border border-slate-200 p-4">
        <div className="flex items-center justify-between mb-3">
          <h3 className="text-sm font-semibold text-slate-700">
            {t('zoning.existingZones', 'Existing Zones ({{count}})', { count: zones.length })}
          </h3>
          <button
            onClick={() => setLoading(true)}
            disabled={loading}
            className="p-1.5 rounded hover:bg-slate-100 text-slate-400"
            title={t('zoning.refresh', 'Refresh zoning data')}
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>

        {zones.length === 0 ? (
          <div className="text-center py-6 text-sm text-slate-400">
            <p>{t('zoning.noZones', 'No zones generated')}</p>
            <p className="text-xs mt-1">
              {t('zoning.noZonesHint', 'Click Generate to create zones.')}
            </p>
          </div>
        ) : (
          <div className="space-y-2">
            {zones.map((zone) => (
              <div
                key={zone.id}
                className="flex items-center justify-between bg-slate-50 rounded p-2 text-sm"
              >
                <span className="font-medium text-slate-700">
                  {zone.label}
                </span>
                <span className="text-xs text-slate-400">
                  {zone.areaHa.toFixed(1)} ha
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

export default ZoningTab;
