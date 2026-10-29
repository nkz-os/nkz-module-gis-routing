import React from 'react';
import { act, cleanup, render } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../../../i18n';

const viewer: any = {};
vi.mock('@nekazari/sdk', async (importOriginal) => {
  const { createInstance } = await import('i18next');
  const i18n = createInstance();
  i18n.init({ lng: 'es', fallbackLng: 'en', defaultNS: 'gis-routing', resources: {}, interpolation: { escapeValue: false } });
  const actual = await importOriginal<Record<string, any>>();
  const { default: es } = await import('../../../locales/es.json');
  i18n.addResourceBundle('es', 'gis-routing', es, true, true);
  return {
    ...actual, i18n,
    useTranslation: (ns?: string) => ({ t: i18n.getFixedT(null, ns ?? 'gis-routing'), i18n }),
    useViewer: () => ({ cesiumViewer: viewer }),
  };
});
import { ParcelConfigDrawTool } from '../ParcelConfigDrawTool';
import { EV } from '../routingMode';

let actions: Record<string, (e: any) => void> = {};
const added: any[] = [];

beforeEach(() => {
  actions = {}; added.length = 0;
  const color = (n: string) => { const c: any = { n }; c.withAlpha = () => c; return c; };
  let n = 0;
  (window as any).Cesium = {
    Cartesian3: { fromDegrees: (...a: number[]) => ({ a }), fromDegreesArray: (a: number[]) => ({ a }) },
    Cartesian2: class { constructor(public x: number, public y: number) {} },
    Cartographic: { fromCartesian: (c: any) => ({ longitude: c.lon, latitude: c.lat }) },
    Math: { toDegrees: (x: number) => x },
    PolygonHierarchy: class { constructor(public p: any, public h: any) {} },
    Color: { fromCssColorString: (s: string) => color(s), WHITE: color('white') },
    VerticalOrigin: { BOTTOM: 1, TOP: 2, CENTER: 3 },
    HeightReference: { CLAMP_TO_GROUND: 1 },
    ScreenSpaceEventHandler: class {
      setInputAction(fn: any, type: string) { actions[type] = fn; }
      destroy() {} isDestroyed() { return false; }
    },
    ScreenSpaceEventType: { LEFT_CLICK: 'click', MOUSE_MOVE: 'move', LEFT_DOUBLE_CLICK: 'dbl' },
    defined: (x: any) => x != null,
    CallbackProperty: class { constructor(public f: any) {} },
  };
  viewer.entities = { add: vi.fn((o: any) => { added.push(o); return o; }), removeById: vi.fn() };
  viewer.isDestroyed = () => false;
  viewer.scene = {
    canvas: {}, pickPositionSupported: true,
    pickPosition: () => ({ lon: 1 + (n += 1) / 10, lat: 2 + n / 10 }),
  };
});
afterEach(() => { cleanup(); vi.clearAllMocks(); });

const activate = (mode: string) => act(() => { window.dispatchEvent(new CustomEvent(EV.activateDraw, { detail: { mode } })); });

describe('cockpit draw tool labels', () => {
  it('labels the gate being placed "Portón", never a colour code', () => {
    render(<ParcelConfigDrawTool />);
    activate('access');
    act(() => actions.click({ position: {} }));
    const gate = added.find((e) => e.billboard);
    expect(gate.label.text).toBe('Portón');
  });

  it('labels the zone being drawn "NO-GO"', () => {
    render(<ParcelConfigDrawTool />);
    activate('zone');
    for (let i = 0; i < 3; i++) act(() => actions.click({ position: {} }));
    act(() => actions.dbl({}));
    const zone = added.find((e) => e.polygon);
    expect(zone.label.text).toBe('NO-GO');
    expect(zone.position).toBeTruthy();
  });
});
