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
