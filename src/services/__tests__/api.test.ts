import { afterEach, describe, expect, it, vi } from 'vitest';

describe('api client', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

  it('resolves the origin from window.__ENV__ at runtime, without trailing slash', async () => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://runtime.test/' };
    const { API_ORIGIN } = await import('../api');
    expect(API_ORIGIN).toBe('http://runtime.test');
  });

  it('sends credentials and no X-Tenant-ID header', async () => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    const fetchMock = vi.fn().mockResolvedValue(new Response('[]', { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);
    const { api } = await import('../api');
    await api.listParcels();
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe('http://api.test/api/routing/parcels');
    expect(init.credentials).toBe('include');
    expect(Object.keys(init.headers).map((k: string) => k.toLowerCase())).not.toContain('x-tenant-id');
  });

  it('maps a coded error body to ApiError.code and params', async () => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    const body = { code: 'ACCESS_IN_ZONE', detail: 'gate in zone', params: { point: { type: 'Point', coordinates: [0, 0] } } };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status: 422 })));
    const { api, ApiError } = await import('../api');
    const err = await api.generate({} as any).catch(e => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422); expect(err.code).toBe('ACCESS_IN_ZONE'); expect(err.params.point.type).toBe('Point');
  });

  it('keeps legacy detail errors readable with code null', async () => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ detail: 'Operation not found' }), { status: 404 })));
    const { api } = await import('../api');
    const err = await api.listOperations().catch(e => e);
    expect(err.code).toBeNull(); expect(err.message).toBe('Operation not found');
  });
});

describe('api VRA calls', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });
  const setup = async (body: unknown = {}) => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    const f = vi.fn().mockImplementation(async () => new Response(JSON.stringify(body), { status: 200 }));
    vi.stubGlobal('fetch', f);
    return { f, ...(await import('../api')) };
  };
  it('getDistribution hits the distribution route', async () => {
    const { f, api } = await setup();
    await api.getDistribution('urn:p 1');
    expect(f.mock.calls[0][0]).toBe('http://api.test/api/routing/zones/urn%3Ap%201/distribution?source=orion');
  });
  it('requestZones posts n_zones, default 8', async () => {
    const { f, api } = await setup();
    await api.requestZones('p1');
    expect(f.mock.calls[0][0]).toBe('http://api.test/api/routing/zones/p1/generate');
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ n_zones: 8 });
    await api.requestZones('p1', 5);
    expect(JSON.parse(f.mock.calls[1][1].body)).toEqual({ n_zones: 5 });
  });
  it('prescription posts and returns the prescription', async () => {
    const { f, api } = await setup({ prescription: { unit: 'kg_ha' } });
    const vra = { enabled: true } as any;
    const r = await api.prescription({ parcelId: 'p1', swaths: [], vra });
    expect(f.mock.calls[0][0]).toBe('http://api.test/api/routing/prescription');
    expect(JSON.parse(f.mock.calls[0][1].body)).toEqual({ parcel_id: 'p1', swaths: [], vra });
    expect(r.prescription.unit).toBe('kg_ha');
  });
});


describe('api export download', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.resetModules(); });

  it('fetches with credentials and returns the file with the server filename', async () => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    const f = vi.fn().mockResolvedValue(new Response('<xml/>', {
      status: 200, headers: { 'Content-Disposition': 'attachment; filename="abc.xml"' } }));
    vi.stubGlobal('fetch', f);
    const { api } = await import('../api');
    const got = await api.downloadExport('urn:ngsi-ld:Op:t:abc', 'isoxml');
    const [url, init] = f.mock.calls[0];
    expect(url).toBe('http://api.test/api/routing/export/urn%3Angsi-ld%3AOp%3At%3Aabc?format=isoxml');
    expect(init.credentials).toBe('include');
    expect(got.filename).toBe('abc.xml');
    expect(await got.blob.text()).toBe('<xml/>');
  });

  it('a coded refusal becomes an ApiError with the code, not a downloaded JSON file', async () => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(
      JSON.stringify({ code: 'IMPLEMENT_WIDTH_MISSING', detail: 'x', params: {} }), { status: 422 })));
    const { api, ApiError } = await import('../api');
    const err = await api.downloadExport('op', 'isoxml').catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.code).toBe('IMPLEMENT_WIDTH_MISSING');
  });
});


describe('api.generate (job API)', () => {
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); vi.resetModules(); });
  const json = (b: unknown, status = 200) => new Response(JSON.stringify(b), { status });
  const setup = async (responses: Response[]) => {
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    const f = vi.fn();
    for (const r of responses) f.mockResolvedValueOnce(r);
    vi.stubGlobal('fetch', f);
    return { f, ...(await import('../api')) };
  };

  it('starts a job, polls every second and returns the result', async () => {
    vi.useFakeTimers();
    const result = { success: true, plan: { route: null }, plan_id: 'p1' };
    const { f, api } = await setup([
      json({ job_id: 'j1', status: 'queued' }, 202),
      json({ status: 'running' }),
      json({ status: 'running' }),
      json({ status: 'completed', result }),
    ]);
    const p = api.generate({ parcel_id: 'x' } as any);
    await vi.advanceTimersByTimeAsync(3000);
    expect(await p).toEqual(result);
    expect(f.mock.calls[0][0]).toBe('http://api.test/api/routing/generate/jobs');
    expect(f.mock.calls[0][1].method).toBe('POST');
    expect(f.mock.calls.slice(1).map((c: any[]) => c[0]))
      .toEqual(Array(3).fill('http://api.test/api/routing/generate/jobs/j1'));
  });

  it('throws the coded error of a failed job with its http status', async () => {
    vi.useFakeTimers();
    const { api, ApiError } = await setup([
      json({ job_id: 'j1' }, 202),
      json({ status: 'failed', http_status: 422,
             error: { code: 'ACCESS_IN_ZONE', detail: 'gate in zone', params: { point: { type: 'Point' } } } }),
    ]);
    const p = api.generate({} as any).catch(e => e);
    await vi.advanceTimersByTimeAsync(1000);
    const err = await p;
    expect(err).toBeInstanceOf(ApiError);
    expect(err.status).toBe(422); expect(err.code).toBe('ACCESS_IN_ZONE'); expect(err.params.point.type).toBe('Point');
  });

  it('times out after 5 minutes with GENERATE_TIMEOUT', async () => {
    vi.useFakeTimers();
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    const f = vi.fn().mockImplementation(async (url: string) =>
      String(url).endsWith('/jobs') ? json({ job_id: 'j1' }, 202) : json({ status: 'running' }));
    vi.stubGlobal('fetch', f);
    const { api } = await import('../api');
    const p = api.generate({} as any).catch(e => e);
    await vi.advanceTimersByTimeAsync(301_000);
    const err = await p;
    expect(err.code).toBe('GENERATE_TIMEOUT');
  });

  it('survives a transient network failure while polling', async () => {
    vi.useFakeTimers();
    (window as any).__ENV__ = { VITE_API_URL: 'http://api.test' };
    const f = vi.fn()
      .mockResolvedValueOnce(json({ job_id: 'j1' }, 202))
      .mockRejectedValueOnce(new TypeError('network'))
      .mockResolvedValueOnce(json({ status: 'completed', result: { success: true } }));
    vi.stubGlobal('fetch', f);
    const { api } = await import('../api');
    const p = api.generate({} as any);
    await vi.advanceTimersByTimeAsync(2000);
    expect(await p).toEqual({ success: true });
  });
});
