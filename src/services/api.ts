import type {
  Feature, Geometry, FeatureCollection, LineString, MultiLineString, Point, Polygon, MultiPolygon,
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

// Client-side VRA configuration (camelCase); sent to the backend as VraRequest.
export interface VraClass { minPct: number; maxPct: number; rate: number | null; label?: string }
export interface VraConfig {
  enabled: boolean;
  source: 'orion' | 'external';
  variable: string;
  classes: VraClass[];
  unit: 'kg_ha' | 'l_ha';
  product: string;
  externalFeatures?: FeatureCollection;
}

// Backend shapes (snake_case, as returned).
export interface VraRequest {
  enabled: boolean;
  source: 'orion' | 'external';
  variable: string;
  classes: { min_pct: number; max_pct: number; rate: number; label?: string }[];
  unit: 'kg_ha' | 'l_ha';
  product: string;
  invert: boolean;
  external_features?: FeatureCollection;
}

/** Response of the zoning job proxy; only the fields the client may show are typed. */
export interface ZoningJobResponse { job_id?: string; status?: string; [key: string]: unknown }

export type IngestedZone = Feature<Geometry, Record<string, unknown> | null>;

export interface DistributionZone { id: string; mean: number; area_ha: number; geometry: Geometry }
export interface Distribution {
  source: 'orion' | 'external';
  variable: string;
  zones: DistributionZone[];
  missing: { id: string; reason: string }[];
  percentiles: number[]; // 21 values, p0..p100 step 5
  /** zoningRunId of the zones returned (latest run); null when they carry none. */
  run_id?: string | null;
}

export interface PrescriptionClass {
  index: number; min_pct: number; max_pct: number; rate: number; area_ha: number; product_total: number;
}
export interface Prescription {
  unit: 'kg_ha' | 'l_ha';
  product: string;
  classes: PrescriptionClass[];
  zones: FeatureCollection;
  swath_segments: FeatureCollection;
  warnings: { code: string; params: Record<string, unknown> }[];
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
  prescription: Prescription | null;
}

export interface GenerateResponse {
  success: boolean;
  operation_id: string | null;
  persisted: boolean;
  plan: Plan;
  /** Id of the stored plan; save it with api.saveOperation. Null when the plan is too large to save. */
  plan_id: string | null;
  alert?: AlertStatus;
}

/** Outcome of the alert raised when an operation is saved. */
export type AlertStatus = 'sent' | 'skipped' | 'failed';
export type DispatchNotification = 'immediate' | 'digest' | 'none';
export interface TenantSettings { dispatch_notification: DispatchNotification }

export interface SaveOperationResponse {
  success: boolean;
  operation_id: string;
  persisted: boolean;
  alert?: AlertStatus;
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
  vra?: VraRequest;
}

export interface ParcelConfig {
  accessPoint: Point | null;
  exclusionZones: FeatureCollection | null;
}

/** Body of PUT /parcels/{id}/config: an absent field is left unchanged, a null accessPoint deletes the gate. */
export interface ParcelConfigPatch {
  accessPoint?: Point | null;
  exclusionZones?: FeatureCollection | null;
}

/** The whole operation as drawn by the cockpit (spec 6.2); `partial` is set for operations of older phases. */
export type OperationPlan = FeatureCollection & {
  properties?: { plan_version?: number; operation_id?: string; operation_type?: string; partial?: boolean };
};

export type PathAlternativeId = 'least_slope' | 'fastest';

export interface PathAlternative {
  id: PathAlternativeId;
  label: string;
  distance_m: number;
  cumulative_climb_m: number;
  max_slope_deg_found?: number;
  geometry: { type: 'LineString'; coordinates: number[][] };
  elevation_profile: number[][];
}

export interface PathResult {
  status: 'queued' | 'running' | 'completed' | 'failed';
  alternatives?: PathAlternative[];
  report?: { max_slope_deg?: number; max_slope_deg_found?: number; search_margin_m?: number;
    warnings?: { code: string; params?: Record<string, unknown> }[] };
  error?: string;
  error_code?: string;
  error_params?: Record<string, unknown>;
}

export interface PathRequest {
  point_a: [number, number];
  point_b: [number, number];
  machine_width_m: number;
  max_slope_deg: number;
  machine_id?: string;
  parcel_id?: string | null;
  /** Deprecated and ignored by the backend; the 3D cockpit still sends them. */
  min_turn_radius_m?: number;
  elevation_grid?: unknown;
}

/** One tenant parcel as drawn on the transit map (outline, gate, no-go zones). */
export interface ContextParcel {
  id: string;
  name: string;
  geometry: GeoJSON.Geometry;
  access_point: Point | null;
  zones: GeoJSON.Geometry[];
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

  saveOperation(
    body: { kind: 'plan'; plan_id: string } |
      { kind: 'transit'; job_id: string; alternative_id: PathAlternativeId; parcel_id: string; name?: string },
  ): Promise<SaveOperationResponse> {
    return request('/operations', { method: 'POST', body: JSON.stringify(body) });
  },

  // Settings
  getSettings() { return request<TenantSettings>('/settings'); },
  putSettings(dispatch: DispatchNotification) {
    return request<TenantSettings>('/settings', {
      method: 'PUT', body: JSON.stringify({ dispatch_notification: dispatch }),
    });
  },

  // Parcels
  listParcels() { return request<any[]>('/parcels'); },
  getParcelsContext(bbox: [number, number, number, number]) {
    return request<{ parcels: ContextParcel[] }>(`/parcels/context?bbox=${bbox.join(',')}`);
  },
  getParcelGeometry(parcelId: string) {
    return request<{ id: string; name: string; geometry: any }>(`/parcels/${encodeURIComponent(parcelId)}/geometry`);
  },
  getParcelConfig(parcelId: string) {
    return request<ParcelConfig>(
      `/parcels/${encodeURIComponent(parcelId)}/config`);
  },
  saveParcelConfig(parcelId: string,
                   body: ParcelConfigPatch) {
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
  getOperationPlan(operationId: string) {
    return request<OperationPlan>(`/operations/${encodeURIComponent(operationId)}/plan`);
  },
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
  startPathCalculation(body: PathRequest) {
    return request<{ job_id: string }>('/path/calculate', { method: 'POST', body: JSON.stringify(body) });
  },
  getPathResult(jobId: string) {
    return request<PathResult>(`/path/${encodeURIComponent(jobId)}`);
  },

  // VRA by classes
  getDistribution(parcelId: string) {
    return request<Distribution>(`/zones/${encodeURIComponent(parcelId)}/distribution?source=orion`);
  },
  requestZones(parcelId: string, nZones = 8) {
    return request<ZoningJobResponse>(`/zones/${encodeURIComponent(parcelId)}/generate`, {
      method: 'POST', body: JSON.stringify({ n_zones: nZones }),
    });
  },
  prescription(args: { parcelId: string; swaths: Plan['swaths']; vra: VraRequest }) {
    return request<{ prescription: Prescription }>('/prescription', {
      method: 'POST',
      body: JSON.stringify({ parcel_id: args.parcelId, swaths: args.swaths, vra: args.vra }),
    });
  },

  // External zones
  ingestExternalZones(format: 'geojson' | 'csv' | 'shapefile' | 'isoxml', content: string) {
    return request<{ success: boolean; data: { count: number; zones: IngestedZone[]; warnings?: string[]; distribution: Distribution } }>('/zones/external/ingest', {
      method: 'POST', body: JSON.stringify({ format, content }),
    });
  },
};
