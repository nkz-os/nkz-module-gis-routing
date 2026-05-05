/**
 * Global type declarations for the Nekazari host runtime.
 * These globals are injected by the host before module bundles execute.
 */
import type { ModuleViewerSlots } from './module-slots';

declare global {
  interface Window {
    /** Host module registry — call .register() from moduleEntry.ts */
    __NKZ__: {
      register(module: {
        id: string;
        viewerSlots: ModuleViewerSlots;
        version?: string;
        main?: import('react').ComponentType;
      }): void;
    };
    /** @nekazari/sdk exposed by the host */
    __NKZ_SDK__: typeof import('@nekazari/sdk');
    /** @nekazari/ui-kit exposed by the host */
    __NKZ_UI__: typeof import('@nekazari/ui-kit');
    /** @nekazari/design-tokens exposed by the host */
    __NKZ_DESIGN_TOKENS__: typeof import('@nekazari/design-tokens');
    /** @nekazari/viewer-kit exposed by the host */
    __NKZ_VIEWER_KIT__: typeof import('@nekazari/viewer-kit');
    /** React 18 exposed by the host */
    React: typeof import('react');
    ReactDOM: typeof import('react-dom');
    ReactRouterDOM: typeof import('react-router-dom');
    /** CesiumJS — available in the map viewer context */
    Cesium?: unknown;
    /** Auth context injected by the host for API calls */
    __nekazariAuthContext?: {
      tenantId?: string;
      token?: string;
      user?: unknown;
    };
  }
}

export {};
