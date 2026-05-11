const BASE_URL = (() => {
  const env = (window as any).__ENV__;
  return (env?.VITE_API_URL || 'https://nkz.robotika.cloud') + '/api/routing';
})();

function getTenantId(): string | undefined {
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

export interface GenerateResult {
  success: boolean;
  alternatives: Array<{ id: string; heading_deg: number; swath_count: number; total_distance_m: number }>;
  data: { type: string; geometry: any; properties: Record<string, any> };
  prescription_map: any;
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
    return request<any>(`/path/${encodeURIComponent(jobId)}`);
  },

  // External zones
  ingestExternalZones(format: 'geojson' | 'csv', content: string) {
    return request<any>('/zones/external/ingest', {
      method: 'POST', body: JSON.stringify({ format, content }),
    });
  },
};
