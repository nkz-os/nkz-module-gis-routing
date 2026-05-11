/**
 * RoutePreviewMap — Embedded map placeholder for the wizard center column.
 *
 * Dispatches a custom event when the generation result changes so the
 * map-layer slot (GisRoutingMapLayer) can render swaths and VRA zones
 * on the Cesium globe.
 */
import React, { useEffect, useRef } from 'react';

interface Props {
  parcelGeometry: any;
  /** Preview geometry for live editing (reserved for future use) */
  previewGeometry: any;
  result: any;
}

export const RoutePreviewMap: React.FC<Props> = ({ parcelGeometry, result }) => {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (result) {
      window.dispatchEvent(
        new CustomEvent('nekazari:gis-routing:routeGenerated', {
          detail: {
            geometry: result.data?.geometry,
            prescriptionMap: result.prescription_map,
          },
        }),
      );
    }
  }, [result]);

  return (
    <div ref={containerRef} className="w-full h-full relative bg-slate-900">
      <div className="absolute inset-0 flex items-center justify-center text-slate-500 text-nkz-sm">
        {!parcelGeometry ? (
          <div className="text-center">
            <p>Selecciona una parcela para ver la previsualización</p>
          </div>
        ) : !result ? (
          <div className="text-center">
            <p>Configura el patrón y pulsa Generar</p>
          </div>
        ) : null}
      </div>
    </div>
  );
};
