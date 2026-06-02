const BASE_URL = (() => {
  if (typeof window === 'undefined') return 'https://nkz.robotika.cloud/api/routing';
  const env = (window as any).__ENV__;
  return (env?.VITE_API_URL || 'https://nkz.robotika.cloud') + '/api/routing';
})();

function getTenantId(): string | undefined {
  if (typeof window === 'undefined') return undefined;
  const ctx = (window as any).__nekazariAuthContext;
  return ctx?.tenantId || ctx?.tenantProfile?.id || undefined;
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };
  const tid = getTenantId();
  if (tid) headers['X-Tenant-ID'] = tid;
  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers, credentials: 'include' });
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
    const msg = typeof detail === 'string' ? detail
      : detail?.error?.message || `HTTP ${status}`;
    super(msg);
    this.status = status;
    this.body = body;
  }
}

export interface RouteMetrics {
  worked_distance_m: number;
  non_working_distance_m: number;
  field_efficiency: number;
  covered_area_ha: number;
  parcel_area_ha: number;
}

export interface GenerateSelected {
  pattern: string;
  route: { type: string; coordinates: any };
  swath_count: number;
  headland_count: number;
  total_distance_m: number;
  pass_order: number[][];
  metrics: RouteMetrics;
  metadata: Record<string, any>;
}

export interface GenerateResult {
  success: boolean;
  selected: GenerateSelected;
  prescription_map: any;
  operation_id: string | null;
}

export interface PathAlternative {
  id: 'least_slope' | 'fastest';
  label: string;
  distance_m: number;
  cumulative_climb_m: number;
  geometry: { type: 'LineString'; coordinates: number[][] };
  elevation_profile: number[][];
}

export interface PathResult {
  status: 'queued' | 'completed' | 'failed';
  alternatives?: PathAlternative[];
  error?: string;
}

// Response selectors — single source of truth for the new contract shape.
export function routeOf(res: GenerateResult): any {
  return res?.selected?.route ?? null;
}
export function operationIdOf(res: GenerateResult): string | null {
  return res?.operation_id ?? null;
}
export function metricsOf(res: GenerateResult): RouteMetrics | null {
  return res?.selected?.metrics ?? null;
}

export interface PatternSummary {
  id: string;
  name: string;
  pattern_type: string;
  pattern_config: any;
  created_at: number;
}

export const api = {
  // Generation
  generate(body: any): Promise<GenerateResult> {
    return request('/generate', { method: 'POST', body: JSON.stringify(body) });
  },

  // Parcels
  listParcels() { return request<any[]>('/parcels'); },
  getParcelGeometry(parcelId: string) {
    return request<{ id: string; name: string; geometry: any }>(`/parcels/${encodeURIComponent(parcelId)}/geometry`);
  },

  // Equipment
  listEquipment() { return request<any[]>('/equipment'); },

  // VRA Zones
  getVRAZones(parcelId: string) {
    return request<any>(`/zones/${encodeURIComponent(parcelId)}`);
  },

  // Operations
  listOperations(limit = 20) { return request<any[]>(`/operations?limit=${limit}`); },
  startOperation(operationId: string) {
    return request('/operations/session/start', {
      method: 'POST',
      body: JSON.stringify({ operation_id: operationId, start_date: new Date().toISOString(), status: 'in_progress' }),
    });
  },
  closeOperation(operationId: string) {
    return request('/operations/session/close', {
      method: 'POST',
      body: JSON.stringify({ operation_id: operationId, end_date: new Date().toISOString(), status: 'ended' }),
    });
  },
  getActiveOperation() { return request<any>('/operations/active'); },
  getOperationCoverage(operationId: string) {
    return request<any>(`/operations/coverage/${encodeURIComponent(operationId)}`);
  },

  // Export
  getExportUrl(operationId: string, format: 'isoxml' | 'geojson' | 'gpx'): string {
    return `${BASE_URL}/export/${encodeURIComponent(operationId)}?format=${format}`;
  },

  // Patterns
  listPatterns(parcelId: string) {
    return request<any>(`/patterns?parcel_id=${encodeURIComponent(parcelId)}`);
  },
  getPattern(patternId: string) {
    return request<any>(`/patterns/${encodeURIComponent(patternId)}`);
  },
  savePattern(body: any) {
    return request('/patterns', { method: 'POST', body: JSON.stringify(body) });
  },
  deletePattern(patternId: string) {
    return request(`/patterns/${encodeURIComponent(patternId)}`, { method: 'DELETE' });
  },

  // Pathfinding
  startPathCalculation(body: any) {
    return request<any>('/path/calculate', { method: 'POST', body: JSON.stringify(body) });
  },
  getPathResult(jobId: string) {
    return request<PathResult>(`/path/${encodeURIComponent(jobId)}`);
  },

  // External zones
  ingestExternalZones(format: 'geojson' | 'csv', content: string) {
    return request<any>('/zones/external/ingest', {
      method: 'POST', body: JSON.stringify({ format, content }),
    });
  },
};
