export type RoutingMode =
  | 'idle'
  | 'placing-gate'
  | 'drawing-zone'
  | 'work-route'
  | 'picking-a'
  | 'picking-b'
  | 'calculating'
  | 'done'; // transit alternatives ready (matches the existing pf 'done' event)

// Window-event names bridging ContextPanelSlot <-> GisRoutingMapLayer.
export const EV = {
  modeChange: 'nekazari:gis-routing:modeChange',          // {mode}
  gatePicked: 'nekazari:gis-routing:parcelConfig:accessPicked', // {lonlat}
  zoneDrawn: 'nekazari:gis-routing:parcelConfig:zoneDrawn',     // {ring}
  activateDraw: 'nekazari:gis-routing:parcelConfig:activate',   // {mode:'access'|'zone'|'off'}
  transitStart: 'nekazari:gis-routing:pickPathStart',
  transitCancel: 'nekazari:gis-routing:pickPathCancel',
  transitAltSelected: 'nekazari:gis-routing:pathAlternativeSelected',
  routeGenerated: 'nekazari:gis-routing:routeGenerated',
} as const;

export function emitMode(mode: RoutingMode) {
  window.dispatchEvent(new CustomEvent(EV.modeChange, { detail: { mode } }));
}
