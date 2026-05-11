import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';

interface Props {
  viewer?: any;
}

const STORAGE_KEY = 'nkz-pathfinding-points';
const PICK_FLAG_KEY = 'nkz-pathfinding-pick';

export const PathfindingPickSlot: React.FC<Props> = ({ viewer }) => {
  const { t } = useTranslation(NS);
  const [pointA, setPointA] = useState<[number, number] | null>(null);
  const [pointB, setPointB] = useState<[number, number] | null>(null);
  const [status, setStatus] = useState<string>('clickA');
  const [isPickMode, setIsPickMode] = useState(false);
  const entitiesRef = useRef<string[]>([]);
  const viewerRef = useRef<any>(viewer);
  viewerRef.current = viewer;

  // Check both URL param and sessionStorage for pick mode
  useEffect(() => {
    const urlPick = typeof window !== 'undefined'
      && new URLSearchParams(window.location.search).get('pick') === 'pathfinding';
    const storagePick = typeof sessionStorage !== 'undefined'
      && sessionStorage.getItem(PICK_FLAG_KEY) === 'true';

    if (urlPick || storagePick) {
      setIsPickMode(true);
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.setItem(PICK_FLAG_KEY, 'true');
      }
    }

    return () => {
      setIsPickMode(false);
      if (typeof sessionStorage !== 'undefined') {
        sessionStorage.removeItem(PICK_FLAG_KEY);
      }
      if (typeof localStorage !== 'undefined') {
        localStorage.removeItem(STORAGE_KEY);
      }
    };
  }, []);

  const clearEntities = useCallback(() => {
    const v = viewerRef.current;
    entitiesRef.current.forEach(id => {
      if (!v?.isDestroyed?.()) v?.entities?.removeById(id);
    });
    entitiesRef.current = [];
  }, []);

  const addMarker = useCallback((lon: number, lat: number, label: string, color: string) => {
    const v = viewerRef.current;
    if (!v || v.isDestroyed?.()) return;
    const Cesium = (window as any).Cesium;
    if (!Cesium) return;

    const entityId = `pathfinding-${label}-${Date.now()}`;
    entitiesRef.current.push(entityId);

    v.entities.add({
      id: entityId,
      position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
      point: {
        pixelSize: 14,
        color: Cesium.Color.fromCssColorString(color),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
      label: {
        text: label,
        font: '16px sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 3,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -20),
        disableDepthTestDistance: Number.POSITIVE_INFINITY,
      },
    });
  }, []);

  // Register Cesium click handler
  useEffect(() => {
    if (!isPickMode) return;

    // Poll for viewer and Cesium readiness
    const interval = setInterval(() => {
      const v = viewerRef.current;
      const Cesium = (window as any).Cesium;
      if (!v || v.isDestroyed?.() || !Cesium) return;
      clearInterval(interval);

      const handler = new Cesium.ScreenSpaceEventHandler(v.scene.canvas);

      handler.setInputAction((click: any) => {
        let cartesian = v.scene.pickPosition(click.position);
        if (!cartesian) {
          cartesian = v.camera.pickEllipsoid(click.position, v.scene.globe.ellipsoid);
        }
        if (!cartesian) return;

        const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
        const lon = Cesium.Math.toDegrees(cartographic.longitude);
        const lat = Cesium.Math.toDegrees(cartographic.latitude);

        // Use a callback to get the latest state without re-running the effect
        setStatus(prevStatus => {
          if (prevStatus === 'clickA') {
            setPointA([lon, lat]);
            addMarker(lon, lat, 'A', '#ef4444');
            return 'clickB';
          } else if (prevStatus === 'clickB') {
            setPointB(prev => {
              const pa = prev || [lon, lat];
              addMarker(lon, lat, 'B', '#3b82f6');
              localStorage.setItem(STORAGE_KEY, JSON.stringify({
                pointA: pa,
                pointB: [lon, lat],
              }));
              return [lon, lat];
            });
            return 'done';
          }
          return prevStatus;
        });
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

      // Store cleanup
      const cleanupRef = handler;
      return () => {
        if (!v.isDestroyed?.()) {
          cleanupRef.destroy();
        }
      };
    }, 200);

    return () => {
      clearInterval(interval);
      clearEntities();
    };
  }, [isPickMode, addMarker, clearEntities]);

  if (!isPickMode) return null;

  return (
    <div
      className="absolute top-4 left-1/2 z-50 bg-slate-900/95 border border-amber-500/50 rounded-nkz-lg px-5 py-4 text-white shadow-2xl backdrop-blur"
      style={{ transform: 'translateX(-50%)', minWidth: 340 }}
    >
      <div className="flex items-center gap-2 mb-3">
        <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
        <p className="text-nkz-sm font-bold">{t('pathfinding.pickMode')}</p>
      </div>

      <div className="space-y-2 text-nkz-sm">
        <div className={`flex items-center gap-3 p-2 rounded-nkz-md transition-colors ${
          status === 'clickA' ? 'bg-red-500/20 text-white' : 'text-slate-400'
        }`}>
          <span className="w-4 h-4 rounded-full bg-red-500 flex-shrink-0 flex items-center justify-center text-[10px] font-bold">A</span>
          <span>{t('pathfinding.clickPointA')}</span>
          {pointA && (
            <span className="ml-auto text-nkz-xs text-slate-300 font-mono">
              {pointA[1].toFixed(5)}, {pointA[0].toFixed(5)}
            </span>
          )}
        </div>

        <div className={`flex items-center gap-3 p-2 rounded-nkz-md transition-colors ${
          status === 'clickB' ? 'bg-blue-500/20 text-white' : 'text-slate-400'
        }`}>
          <span className="w-4 h-4 rounded-full bg-blue-500 flex-shrink-0 flex items-center justify-center text-[10px] font-bold">B</span>
          <span>{t('pathfinding.clickPointB')}</span>
          {pointB && (
            <span className="ml-auto text-nkz-xs text-slate-300 font-mono">
              {pointB[1].toFixed(5)}, {pointB[0].toFixed(5)}
            </span>
          )}
        </div>
      </div>

      {status === 'done' && (
        <div className="mt-3 pt-3 border-t border-slate-700">
          <p className="text-nkz-xs text-green-400 mb-2">{t('pathfinding.pointsReady')}</p>
          <button
            onClick={() => {
              setPointA(null);
              setPointB(null);
              setStatus('clickA');
              clearEntities();
              localStorage.removeItem(STORAGE_KEY);
            }}
            className="text-nkz-xs text-amber-400 hover:text-amber-300 underline"
          >
            {t('actions.retry')} — {t('pathfinding.pickMode')}
          </button>
        </div>
      )}
    </div>
  );
};
