import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';
import { createInstance } from 'i18next';

// @nekazari/sdk's i18n singleton is initialised by the host, not in jsdom.
// Replace `i18n` and `useTranslation` with a minimal i18next instance so
// `src/i18n.ts` can register the locale bundles and components render real text.
vi.mock('@nekazari/sdk', async (importOriginal) => {
  const actual = await importOriginal<Record<string, unknown>>();
  const i18n = createInstance();
  i18n.init({ lng: 'es', fallbackLng: 'en', defaultNS: 'gis-routing', resources: {}, interpolation: { escapeValue: false } });
  const useTranslation = (ns?: string) => ({ t: i18n.getFixedT(null, ns ?? 'gis-routing'), i18n });
  return { ...actual, i18n, useTranslation };
});

(window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };

Object.defineProperty(window, 'matchMedia', {
  writable: true,
  value: () => ({
    matches: false,
    addEventListener() {},
    removeEventListener() {},
    addListener() {},
    removeListener() {},
  }),
});

if (!(globalThis as any).ResizeObserver) {
  (globalThis as any).ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
