import type {
  Geometry, FeatureCollection, LineString, MultiLineString, Point, Polygon, MultiPolygon,
} from 'geojson';

function resolveOrigin(): string {
  const runtime = typeof window !== 'undefined' ? (window as any).__ENV__?.VITE_API_URL : undefined;
  const raw = runtime ?? (import.meta as any).env?.VITE_API_URL ?? '';
  return String(raw).replace(/\/$/, '');
}

export const API_ORIGIN: string = resolveOrigin();
const BASE_URL = `${API_ORIGIN}/api/routing`;

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options.headers as Record<string, string> || {}),
  };

  if (typeof window !== 'undefined') {
    const ctx = (window as any).__nekazariAuthContext;
    let token = ctx?.token || (window as any).keycloak?.token;
    if (ctx?.getToken) {
      const maybePromise = ctx.getToken();
      token = maybePromise instanceof Promise ? await maybePromise : maybePromise;
    }
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }

  const resp = await fetch(`${BASE_URL}${path}`, { ...options, headers, credentials: 'include' });
  if (!resp.ok) {
    const error = await resp.json().catch(() => ({ detail: resp.statusText }));
    throw new ApiError(resp.status, error);
  }
  return resp.json();
}

export class ApiError extends Error {
  status: number;
  code: string | null;
  detail: string;
  params: Record<string, unknown>;
  body: any;
  constructor(status: number, body: any) {
    const detail: string = typeof body?.detail === 'string'
      ? body.detail
      : body?.detail?.error?.message ?? body?.detail?.message ?? `HTTP ${status}`;
    super(detail);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.code = typeof body?.code === 'string' ? body.code : null;
    this.detail = detail;
    this.params = body?.params ?? {};
  }
}

export interface PlanMetrics {
  worked_distance_m: number;
  non_working_distance_m: number;
  access_distance_m: number;
  access_leg_distance_m: number;
  return_distance_m: number;
  field_efficiency: number;
  covered_area_ha: number;
  parcel_area_ha: number;
  working_area_ha: number;
}

export interface ValidationCheck {
  id: string; ok: boolean; value: number; limit: number; geometry: Geometry | null;
}
export interface ValidationWarning {
  code: string; geometry: Geometry | null; params: Record<string, unknown>;
}
export interface ValidationReport {
  ok: boolean; checks: ValidationCheck[]; fallbacks_applied: string[]; warnings: ValidationWarning[];
}

export interface Plan {
  pattern: string;
  curve_type: string;
  swath_count: number;
  headland_passes: number;
  route: LineString | MultiLineString;
  swaths: { index: number; kind: 'work' | 'headland'; geometry: LineString }[];
  access_path: LineString | null;
  return_path: LineString | null;
  access_point: Point | null;
  exit_point: Point;
  working_area: Polygon | MultiPolygon;
  unreached_parts: { geometry: Polygon; area_ha: number }[];
  metrics: PlanMetrics;
  validation: ValidationReport | null;
  exclusion_zones: FeatureCollection;
  prescription: unknown | null;
}

export interface GenerateResponse {
  success: boolean;
  operation_id: string | null;
  persisted: boolean;
  plan: Plan;
}

export interface GenerateRequest {
  parcel_geometry: Polygon;
  parcel_id: string | null;
  tractor_id: string | null;
  implement_id: string | null;
  pattern: 'auto' | 'boustrophedon' | 'snake' | 'spiral' | 'headland-only';
  pattern_config: {
    heading_deg?: number; width_m: number; overlap_pct: number; headland_passes: number;
    heading_objective: 'efficiency' | 'contour'; turning_radius_m?: number;
  };
  operation_type: string;
  return_to_access: boolean;
  persist: boolean;
  planned_start_at?: string;
  planned_end_at?: string;
}

export interface ParcelConfig {
  accessPoint: Point | null;
  exclusionZones: FeatureCollection | null;
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

export interface PatternSummary {
  id: string;
  name: string;
  pattern_type: string;
  pattern_config: any;
  created_at: number;
}

export const api = {
  // Generation
  generate(body: GenerateRequest): Promise<GenerateResponse> {
    return request('/generate', { method: 'POST', body: JSON.stringify(body) });
  },

  // Parcels
  listParcels() { return request<any[]>('/parcels'); },
  getParcelGeometry(parcelId: string) {
    return request<{ id: string; name: string; geometry: any }>(`/parcels/${encodeURIComponent(parcelId)}/geometry`);
  },
  getParcelConfig(parcelId: string) {
    return request<ParcelConfig>(
      `/parcels/${encodeURIComponent(parcelId)}/config`);
  },
  saveParcelConfig(parcelId: string,
                   body: ParcelConfig) {
    return request<{ success: boolean; updated: string[] }>(`/parcels/${encodeURIComponent(parcelId)}/config`,
      { method: 'PUT', body: JSON.stringify(body) });
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
