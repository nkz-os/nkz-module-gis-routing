/**
 * Global type declarations for the Nekazari host runtime.
 * In Module Federation 2.0, shared dependencies (React, SDK, UI-kit, etc.)
 * are resolved as federation singletons — not via window globals.
 * Only CesiumJS and the auth context are exposed on window.
 */

declare global {
  interface Window {
    /** CesiumJS — available in the viewer context */
    Cesium?: unknown;
    /** Runtime env vars injected by host entrypoint */
    __ENV__?: Record<string, string>;
    /** Auth context injected by the host for API calls */
    __nekazariAuthContext?: {
      tenantId?: string;
      token?: string;
      user?: unknown;
    };
  }
}

export {};
