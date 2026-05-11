import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';
const STORAGE_KEY = 'nkz-pathfinding-points';
const PICK_FLAG_KEY = 'nkz-pathfinding-pick';

export const PathfindingPickSlot: React.FC<{ viewer?: any }> = ({ viewer }) => {
  const { t } = useTranslation(NS);
  const [pointA, setPointA] = useState<[number, number] | null>(null);
  const [pointB, setPointB] = useState<[number, number] | null>(null);
  const [status, setStatus] = useState<string>('clickA');
  const [isPickMode, setIsPickMode] = useState(false);
  const handlerRef = useRef<any>(null);
  const pointARef = useRef<[number, number] | null>(null);
  const pointBRef = useRef<[number, number] | null>(null);

  // --- Pick mode detection ---
  useEffect(() => {
    const urlPick = new URLSearchParams(window.location.search).get('pick') === 'pathfinding';
    const storagePick = sessionStorage.getItem(PICK_FLAG_KEY) === 'true';
    if (urlPick || storagePick) {
      setIsPickMode(true);
      sessionStorage.setItem(PICK_FLAG_KEY, 'true');
    }
    return () => { sessionStorage.removeItem(PICK_FLAG_KEY); };
  }, []);

  // --- Register click handler ---
  useEffect(() => {
    if (!isPickMode) return;

    const Cesium = (window as any).Cesium;
    const poll = setInterval(() => {
      if (!viewer || viewer.isDestroyed?.()) return;
      if (!Cesium) return;
      clearInterval(poll);

      const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);
      handlerRef.current = handler;

      handler.setInputAction((click: any) => {
        const v = viewer;
        if (v.isDestroyed?.()) return;

        let cartesian = v.scene.pickPosition(click.position);
        if (!cartesian) cartesian = v.camera.pickEllipsoid(click.position, v.scene.globe.ellipsoid);
        if (!cartesian) return;

        const cg = Cesium.Cartographic.fromCartesian(cartesian);
        const lon = Cesium.Math.toDegrees(cg.longitude);
        const lat = Cesium.Math.toDegrees(cg.latitude);

        if (!pointARef.current) {
          pointARef.current = [lon, lat];
          addEntity(v, `pathfinding-A`, lon, lat, '#ef4444', 'A');
          setPointA([lon, lat]);
          setStatus('clickB');
        } else if (!pointBRef.current) {
          pointBRef.current = [lon, lat];
          addEntity(v, `pathfinding-B`, lon, lat, '#3b82f6', 'B');
          setPointB([lon, lat]);
          setStatus('done');
          localStorage.setItem(STORAGE_KEY, JSON.stringify({
            pointA: pointARef.current,
            pointB: [lon, lat],
          }));
        }
      }, Cesium.ScreenSpaceEventType.LEFT_CLICK);
    }, 300);

    return () => {
      clearInterval(poll);
      if (handlerRef.current && !viewer?.isDestroyed?.()) {
        handlerRef.current.destroy();
      }
      if (!viewer?.isDestroyed?.()) {
        try { viewer.entities.removeById('pathfinding-A'); } catch {}
        try { viewer.entities.removeById('pathfinding-B'); } catch {}
      }
    };
  }, [isPickMode, viewer]);

  // --- Reset ---
  const handleReset = useCallback(() => {
    pointARef.current = null;
    pointBRef.current = null;
    setPointA(null);
    setPointB(null);
    setStatus('clickA');
    localStorage.removeItem(STORAGE_KEY);
    if (!viewer?.isDestroyed?.()) {
      try { viewer.entities.removeById('pathfinding-A'); } catch {}
      try { viewer.entities.removeById('pathfinding-B'); } catch {}
    }
  }, [viewer]);

  if (!isPickMode) return null;

  return (
    <div
      className="absolute top-4 left-1/2 z-50 bg-slate-900/95 border border-amber-500/50 rounded-lg px-5 py-4 text-white shadow-2xl"
      style={{ transform: 'translateX(-50%)', minWidth: 340 }}
    >
      <div className="flex items-center gap-2 mb-3">
        <div className="w-2 h-2 rounded-full bg-amber-500 animate-pulse" />
        <p className="text-sm font-bold">{t('pathfinding.pickMode')}</p>
      </div>
      <div className="space-y-2 text-sm">
        <div className={`flex items-center gap-3 p-2 rounded ${status === 'clickA' ? 'bg-red-500/20' : 'text-slate-400'}`}>
          <span className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center text-[10px] font-bold">A</span>
          {t('pathfinding.clickPointA')}
          {pointA && <span className="ml-auto text-xs text-slate-300 font-mono">{pointA[1].toFixed(5)}, {pointA[0].toFixed(5)}</span>}
        </div>
        <div className={`flex items-center gap-3 p-2 rounded ${status === 'clickB' ? 'bg-blue-500/20' : 'text-slate-400'}`}>
          <span className="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center text-[10px] font-bold">B</span>
          {t('pathfinding.clickPointB')}
          {pointB && <span className="ml-auto text-xs text-slate-300 font-mono">{pointB[1].toFixed(5)}, {pointB[0].toFixed(5)}</span>}
        </div>
      </div>
      {status === 'done' && (
        <div className="mt-3 pt-3 border-t border-slate-700">
          <p className="text-xs text-green-400 mb-2">{t('pathfinding.pointsReady')}</p>
          <button onClick={handleReset} className="text-xs text-amber-400 hover:text-amber-300 underline">
            {t('actions.retry')}
          </button>
        </div>
      )}
    </div>
  );
};

function addEntity(viewer: any, id: string, lon: number, lat: number, color: string, label: string) {
  const Cesium = (window as any).Cesium;
  if (!Cesium || !viewer || viewer.isDestroyed?.()) return;
  try { viewer.entities.removeById(id); } catch {}
  viewer.entities.add({
    id,
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
}
