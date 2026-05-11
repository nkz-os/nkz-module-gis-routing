import React, { useEffect, useRef, useState, useCallback } from 'react';
import { useTranslation } from '@nekazari/sdk';

const NS = 'gis-routing';

interface Props {
  viewer?: any;
}

const STORAGE_KEY = 'nkz-pathfinding-points';

export const PathfindingPickSlot: React.FC<Props> = ({ viewer }) => {
  const { t } = useTranslation(NS);
  const [pointA, setPointA] = useState<[number, number] | null>(null);
  const [pointB, setPointB] = useState<[number, number] | null>(null);
  const [status, setStatus] = useState<string>('clickA');
  const entitiesRef = useRef<string[]>([]);
  const CesiumRef = useRef<any>(null);

  // Check URL param to enable pick mode
  const isPickMode = typeof window !== 'undefined'
    && new URLSearchParams(window.location.search).get('pick') === 'pathfinding';

  useEffect(() => {
    if (!isPickMode) {
      // Clear stored points when not in pick mode
      localStorage.removeItem(STORAGE_KEY);
      return;
    }
    CesiumRef.current = (window as any).Cesium;
  }, [isPickMode]);

  const clearEntities = useCallback(() => {
    entitiesRef.current.forEach(id => {
      if (!viewer?.isDestroyed?.()) viewer?.entities?.removeById(id);
    });
    entitiesRef.current = [];
  }, [viewer]);

  const addMarker = useCallback((lon: number, lat: number, label: string, color: string) => {
    if (!viewer || viewer.isDestroyed?.()) return;
    const Cesium = CesiumRef.current;
    if (!Cesium) return;

    const entityId = `pathfinding-${label}`;
    entitiesRef.current.push(entityId);

    viewer.entities.add({
      id: entityId,
      position: Cesium.Cartesian3.fromDegrees(lon, lat, 0),
      point: {
        pixelSize: 12,
        color: Cesium.Color.fromCssColorString(color),
        outlineColor: Cesium.Color.WHITE,
        outlineWidth: 2,
        heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
      },
      label: {
        text: label,
        font: '14px sans-serif',
        fillColor: Cesium.Color.WHITE,
        outlineColor: Cesium.Color.BLACK,
        outlineWidth: 2,
        style: Cesium.LabelStyle.FILL_AND_OUTLINE,
        verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
        pixelOffset: new Cesium.Cartesian2(0, -16),
      },
    });
  }, [viewer]);

  useEffect(() => {
    if (!isPickMode || !viewer) return;

    const Cesium = CesiumRef.current;
    if (!Cesium) return;

    const handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas);

    handler.setInputAction((click: any) => {
      let cartesian = viewer.scene.pickPosition(click.position);
      if (!cartesian) {
        cartesian = viewer.camera.pickEllipsoid(click.position, viewer.scene.globe.ellipsoid);
      }
      if (!cartesian) return;

      const cartographic = Cesium.Cartographic.fromCartesian(cartesian);
      const lon = Cesium.Math.toDegrees(cartographic.longitude);
      const lat = Cesium.Math.toDegrees(cartographic.latitude);

      if (status === 'clickA') {
        setPointA([lon, lat]);
        addMarker(lon, lat, 'A', '#ef4444');
        setStatus('clickB');
      } else if (status === 'clickB') {
        setPointB([lon, lat]);
        addMarker(lon, lat, 'B', '#3b82f6');
        setStatus('done');

        // Save to localStorage so PathfindingTab picks them up
        localStorage.setItem(STORAGE_KEY, JSON.stringify({
          pointA: [lon, lat],
          pointB: pointA,
        }));
      }
    }, Cesium.ScreenSpaceEventType.LEFT_CLICK);

    return () => {
      if (!viewer.isDestroyed?.()) {
        handler.destroy();
      }
    };
  }, [isPickMode, viewer, status, pointA, addMarker]);

  // Clear on unmount
  useEffect(() => {
    return () => {
      clearEntities();
      if (isPickMode) {
        localStorage.removeItem(STORAGE_KEY);
      }
    };
  }, [isPickMode, clearEntities]);

  if (!isPickMode) return null;

  return (
    <div
      className="absolute top-4 left-1/2 -translate-x-1/2 z-50 bg-slate-900 border border-slate-600 rounded-nkz-lg px-4 py-3 text-white shadow-xl"
      style={{ minWidth: 300 }}
    >
      <p className="text-nkz-sm font-semibold mb-2">
        {t('pathfinding.pickMode')}
      </p>
      <div className="space-y-1 text-nkz-xs">
        <div className={`flex items-center gap-2 ${status === 'clickA' ? 'text-white' : 'text-slate-500'}`}>
          <span className="w-3 h-3 rounded-full bg-red-500 flex-shrink-0" />
          {t('pathfinding.clickPointA')}
          {pointA && <span className="text-slate-400">({pointA[1].toFixed(5)}, {pointA[0].toFixed(5)})</span>}
        </div>
        <div className={`flex items-center gap-2 ${status === 'clickB' ? 'text-white' : 'text-slate-500'}`}>
          <span className="w-3 h-3 rounded-full bg-blue-500 flex-shrink-0" />
          {t('pathfinding.clickPointB')}
          {pointB && <span className="text-slate-400">({pointB[1].toFixed(5)}, {pointB[0].toFixed(5)})</span>}
        </div>
      </div>
      {status === 'done' && (
        <p className="text-nkz-xs text-green-400 mt-2">{t('pathfinding.pointsReady')}</p>
      )}
      <button
        onClick={() => {
          setPointA(null);
          setPointB(null);
          setStatus('clickA');
          clearEntities();
          localStorage.removeItem(STORAGE_KEY);
        }}
        className="mt-2 text-nkz-xs text-nkz-text-accent hover:underline"
      >
        {t('actions.retry')}
      </button>
    </div>
  );
};
