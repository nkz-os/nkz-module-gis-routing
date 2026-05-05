/**
 * API Client for GIS Routing module.
 *
 * Provides access to the module's own backend (sync, generate, export)
 * via the Nekazari authentication context and tenant-aware headers.
 */

const BASE_URL = (() => {
  const env = (window as any).__ENV__;
  return (env?.VITE_API_URL || 'https://nkz.robotika.cloud') + '/api/routing';
})();

function getTenantId(): string | undefined {
  const ctx = (window as any).__nekazariAuthContext;
  return ctx?.tenantId;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  const tid = getTenantId();
  if (tid) headers['X-Tenant-ID'] = tid;
  const resp = await fetch(`${BASE_URL}${path}`, {
    ...options,
    headers,
    credentials: 'include',
  });
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new ApiError(resp.status, error);
  }
  return resp.json();
}

export class ApiError extends Error {
  status: number;
  body: any;

  constructor(status: number, body: any) {
    super(body?.error?.message || body?.detail || `HTTP ${status}`);
    this.status = status;
    this.body = body;
  }
}

export interface SyncPullResponse {
  changes: {
    parcels: any;
    equipment: any;
    operations: any;
  };
  timestamp: number;
}

export interface CollectionChanges {
  created: any[];
  updated: any[];
  deleted: string[];
}

export const api = {
  pull(
    collections: string[],
    lastPulledAt: number,
    schemaVersion = 3,
  ): Promise<SyncPullResponse> {
    return request(
      `/sync?collections=${collections.join(',')}&last_pulled_at=${lastPulledAt}&schema_version=${schemaVersion}`,
    );
  },

  push(
    collections: string[],
    body: { changes: any; last_pulled_at: number },
  ): Promise<SyncPullResponse> {
    return request(`/sync?collections=${collections.join(',')}`, {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  generate(body: any) {
    return request('/generate', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  generateWithVRA(body: any) {
    return request('/generate/with-vra', {
      method: 'POST',
      body: JSON.stringify(body),
    });
  },

  getExportUrl(operationId: string, format: 'isoxml' | 'geojson' | 'gpx'): string {
    return `${BASE_URL}/export/${encodeURIComponent(operationId)}?format=${format}`;
  },

  // Zoning — fetched from Orion-LD via our backend
  getZones(parcelId: string) {
    return request(`/zones/${encodeURIComponent(parcelId)}`);
  },

  generateZones(parcelId: string, nZones: number) {
    return request(`/zones/${encodeURIComponent(parcelId)}/generate`, {
      method: 'POST',
      body: JSON.stringify({ n_zones: nZones }),
    });
  },

  listParcels() {
    return request<any[]>('/parcels');
  },

  getParcelGeometry(parcelId: string) {
    return request<{ id: string; name: string; geometry: any }>(
      `/parcels/${encodeURIComponent(parcelId)}/geometry`,
    );
  },

  listEquipment() {
    return request<any[]>('/equipment');
  },

  listOperations(limit = 20) {
    return request<any[]>(`/operations?limit=${limit}`);
  },
};
