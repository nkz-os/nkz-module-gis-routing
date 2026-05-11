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
  const [ready, setReady] = useState(false);
  const pointARef = useRef<[number, number] | null>(null);
  const pointBRef = useRef<[number, number] | null>(null);
  const markA = useRef(false);
  const markB = useRef(false);

  // Pick mode detection
  const isPickMode = useRef(false);
  useEffect(() => {
    const urlPick = new URLSearchParams(window.location.search).get('pick') === 'pathfinding';
    const storagePick = sessionStorage.getItem(PICK_FLAG_KEY) === 'true';
    if (urlPick || storagePick) {
      isPickMode.current = true;
      sessionStorage.setItem(PICK_FLAG_KEY, 'true');
      // Force re-render to show UI
      setReady(true);
    }
    return () => { sessionStorage.removeItem(PICK_FLAG_KEY); };
  }, []);

  // Register native DOM click on the Cesium canvas — avoids conflicts
  // with Cesium's own ScreenSpaceEventHandler
  useEffect(() => {
    if (!ready) return;

    // Poll for Cesium canvas
    const poll = setInterval(() => {
      const canvas = document.querySelector('canvas.cesium-widget canvas')
        || document.querySelector('.cesium-viewer canvas');
      if (!canvas) return;
      clearInterval(poll);

      const onClick = (e: MouseEvent) => {
        if (!viewer || viewer.isDestroyed?.()) return;
        const rect = canvas.getBoundingClientRect();
        const x = e.clientX - rect.left;
        const y = e.clientY - rect.top;

        const Cesium = (window as any).Cesium;
        if (!Cesium) return;

        let cartesian = viewer.scene.pickPosition(new Cesium.Cartesian2(x, y));
        if (!cartesian) {
          cartesian = viewer.camera.pickEllipsoid(
            new Cesium.Cartesian2(x, y),
            viewer.scene.globe.ellipsoid,
          );
        }
        if (!cartesian) return;

        const cg = Cesium.Cartographic.fromCartesian(cartesian);
        const lon = Cesium.Math.toDegrees(cg.longitude);
        const lat = Cesium.Math.toDegrees(cg.latitude);

        if (!markA.current) {
          markA.current = true;
          pointARef.current = [lon, lat];
          addEntity(viewer, 'pathfinding-A', lon, lat, '#ef4444', 'A');
          setPointA([lon, lat]);
          setStatus('clickB');
        } else if (!markB.current) {
          markB.current = true;
          pointBRef.current = [lon, lat];
          addEntity(viewer, 'pathfinding-B', lon, lat, '#3b82f6', 'B');
          setPointB([lon, lat]);
          setStatus('done');
          localStorage.setItem(STORAGE_KEY, JSON.stringify({
            pointA: pointARef.current,
            pointB: [lon, lat],
          }));
        }
      };

      (canvas as HTMLCanvasElement).addEventListener('click', onClick as EventListener);
      // Store for cleanup
      (canvas as any).__nkzPathfindingClick = onClick;
    }, 200);

    return () => {
      clearInterval(poll);
      const canvas = document.querySelector('canvas.cesium-widget canvas')
        || document.querySelector('.cesium-viewer canvas');
      if (canvas && (canvas as any).__nkzPathfindingClick) {
        (canvas as HTMLCanvasElement).removeEventListener('click', (canvas as any).__nkzPathfindingClick as EventListener);
      }
    };
  }, [ready, viewer]);

  const handleReset = useCallback(() => {
    markA.current = false;
    markB.current = false;
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

  if (!ready) return null;

  return (
    <div
      className="absolute top-4 left-1/2 z-50 bg-slate-900/95 border border-amber-500/50 rounded-lg px-5 py-4 text-white shadow-2xl pointer-events-auto"
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
