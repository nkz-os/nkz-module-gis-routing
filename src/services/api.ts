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
  const fromCtx = ctx?.tenantId;
  const fromProfile = ctx?.tenantProfile?.id || ctx?.tenantProfile?.tenant_id;
  const fromUser =
    ctx?.user?.tenant_id
    || ctx?.user?.tenantId
    || ctx?.user?.attributes?.tenant_id
    || ctx?.user?.attributes?.tenant;
  const tenant = fromCtx || fromProfile || fromUser;
  return typeof tenant === 'string' && tenant.trim() ? tenant.trim() : undefined;
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
    const detail = body?.detail;
    const message: string =
      typeof detail === 'string' ? detail
      : Array.isArray(detail) ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
      : typeof detail === 'object' && detail?.error?.message ? detail.error.message
      : typeof detail === 'object' ? JSON.stringify(detail)
      : body?.error?.message
      || `HTTP ${status}`;
    super(message);
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

export interface ZoneData {
  id: string;
  zone_id: number | string;
  zone_class: string;
  prescription_rate: number;
  mean_value: number;
  area_ha: number;
  geometry: any;
}

export interface EquipmentSummary {
  id: string;
  name: string;
  category?: string;
  machine_role?: 'tractor' | 'implement' | 'unknown';
  implementWidth?: number;
  trackWidth?: number;
  wheelbase?: number;
  gpsOffsetX?: number;
  gpsOffsetY?: number;
  gpsOffsetZ?: number;
  hitchType?: string;
  hitchOffsetX?: number;
  implementLength?: number;
  implementOffsetX?: number;
  steeringType?: string;
  steeringAxles?: string;
}

export interface ZonesResponse {
  success: boolean;
  data: {
    parcel_id: string;
    zones: ZoneData[];
    count: number;
  };
}

export interface ExternalZonesIngestResponse {
  success: boolean;
  data: {
    count: number;
    zones: Array<{
      type: 'Feature';
      geometry: any;
      properties: {
        zone_id: string | number;
        zone_class: string;
        prescription_rate: number;
      };
    }>;
  };
}

export interface OperationSummary {
  id: string;
  parcel_id: string;
  operation_type: string;
  implement_width: number;
  vra_enabled: boolean;
  status: string;
  started_at?: string | null;
  completed_at?: string | null;
  updated_at?: string | null;
}

export interface CoverageResponse {
  success: boolean;
  data: {
    type: 'Feature';
    geometry: any;
    properties: {
      operation_id: string;
      layer_type: string;
    };
  };
}

export interface TrajectoryAlternative {
  id: string;
  heading_deg: number;
  swath_count: number;
}

export interface ActiveOperationInfo {
  id: string;
  parcel_id: string;
  operation_type: string;
  status: string;
  started_at?: string | null;
  name?: string;
}

export interface ActiveOperationResponse {
  success: boolean;
  data: { operation: ActiveOperationInfo | null };
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
    return request<ZonesResponse>(`/zones/${encodeURIComponent(parcelId)}`);
  },

  generateZones(parcelId: string, nZones: number) {
    return request(`/zones/${encodeURIComponent(parcelId)}/generate`, {
      method: 'POST',
      body: JSON.stringify({ n_zones: nZones }),
    });
  },

  ingestExternalZones(format: 'geojson' | 'csv', content: string) {
    return request<ExternalZonesIngestResponse>('/zones/external/ingest', {
      method: 'POST',
      body: JSON.stringify({ format, content }),
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
    return request<EquipmentSummary[]>('/equipment');
  },

  listOperations(limit = 20) {
    return request<OperationSummary[]>(`/operations?limit=${limit}`);
  },

  closeOperationSession(operationId: string, endDate: string, status = 'ended') {
    return request<{ success: boolean; message: string }>('/operations/session/close', {
      method: 'POST',
      body: JSON.stringify({
        operation_id: operationId,
        end_date: endDate,
        status,
      }),
    });
  },

  startOperationSession(operationId: string, startDate: string, status = 'in_progress') {
    return request<{ success: boolean; message: string }>('/operations/session/start', {
      method: 'POST',
      body: JSON.stringify({
        operation_id: operationId,
        start_date: startDate,
        status,
      }),
    });
  },

  getOperationCoverage(operationId: string) {
    return request<CoverageResponse>(`/operations/coverage/${encodeURIComponent(operationId)}`);
  },

  getActiveOperation() {
    return request<ActiveOperationResponse>('/operations/active');
  },
};
