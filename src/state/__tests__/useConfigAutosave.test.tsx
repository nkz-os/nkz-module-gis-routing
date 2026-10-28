import { act, renderHook } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { useConfigAutosave } from '../useConfigAutosave';
const poly = (x: number) => ({ type: 'Polygon', coordinates: [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]] }) as any;
const zone = (id: string, valid = true, x = 0) => ({ id, polygon: poly(x), areaHa: 1, valid });
beforeEach(() => vi.useFakeTimers()); afterEach(() => vi.useRealTimers());

describe('useConfigAutosave', () => {
  it('debounces and saves valid zones as a FeatureCollection', async () => {
    const save = vi.fn().mockResolvedValue({ success: true });
    const { result, rerender } = renderHook((p: any) => useConfigAutosave(p), { initialProps: { parcelId: 'p1', accessPoint: null, zones: [], enabled: true, save, load: vi.fn() } as any });
    rerender({ parcelId: 'p1', accessPoint: null, zones: [zone('a')], enabled: true, save, load: vi.fn() });
    expect(result.current.status.state).toBe('dirty');
    await act(async () => { vi.advanceTimersByTime(799); }); expect(save).not.toHaveBeenCalled();
    await act(async () => { vi.advanceTimersByTime(1); await Promise.resolve(); });
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][1].exclusionZones.features[0].properties.id).toBe('a');
    expect(result.current.status.state).toBe('clean');
  });
  it('invalid polygon blocks save and keeps dirty', async () => {
    const save = vi.fn();
    const { result, rerender } = renderHook((p: any) => useConfigAutosave(p), { initialProps: { parcelId: 'p1', accessPoint: null, zones: [], enabled: true, save, load: vi.fn() } as any });
    rerender({ parcelId: 'p1', accessPoint: null, zones: [zone('bad', false)], enabled: true, save, load: vi.fn() });
    await act(async () => { vi.advanceTimersByTime(1000); });
    expect(save).not.toHaveBeenCalled(); expect(result.current.status.state).toBe('dirty');
  });
  it('error keeps dirty state and retry re-saves', async () => {
    const save = vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce({ success: true });
    const { result, rerender } = renderHook((p: any) => useConfigAutosave(p), { initialProps: { parcelId: 'p1', accessPoint: null, zones: [], enabled: true, save, load: vi.fn() } as any });
    rerender({ parcelId: 'p1', accessPoint: { type: 'Point', coordinates: [0, 0] }, zones: [], enabled: true, save, load: vi.fn() });
    await act(async () => { vi.advanceTimersByTime(800); await Promise.resolve(); });
    expect(result.current.status).toEqual({ state: 'error', message: 'boom' });
    await act(async () => { result.current.retry(); await Promise.resolve(); });
    expect(save).toHaveBeenCalledTimes(2); expect(result.current.status.state).toBe('clean');
  });
  it('verifyBeforeGenerate restores a configuration the broker lost', async () => {
    const save = vi.fn().mockResolvedValue({}); const load = vi.fn().mockResolvedValue({ accessPoint: null, exclusionZones: { type: 'FeatureCollection', features: [] } });
    const { result } = renderHook(() => useConfigAutosave({ parcelId: 'p1', accessPoint: null, zones: [zone('a')], enabled: true, save, load }));
    await act(async () => { vi.advanceTimersByTime(800); await Promise.resolve(); });
    let verdict = ''; await act(async () => { verdict = await result.current.verifyBeforeGenerate(); });
    expect(verdict).toBe('restored'); expect(save).toHaveBeenCalledTimes(2);
    load.mockResolvedValue({ accessPoint: null, exclusionZones: save.mock.calls[1][1].exclusionZones });
    await act(async () => { verdict = await result.current.verifyBeforeGenerate(); }); expect(verdict).toBe('ok');
    load.mockRejectedValue(new Error('down'));
    await act(async () => { verdict = await result.current.verifyBeforeGenerate(); }); expect(verdict).toBe('failed');
  });
  it('switching parcel flushes the pending edit to the OLD parcel only', async () => {
    const save = vi.fn().mockResolvedValue({});
    const { rerender } = renderHook((p: any) => useConfigAutosave(p), { initialProps: { parcelId: 'p1', accessPoint: null, zones: [], enabled: true, save, load: vi.fn() } as any });
    rerender({ parcelId: 'p1', accessPoint: null, zones: [zone('a')], enabled: true, save, load: vi.fn() });
    rerender({ parcelId: 'p2', accessPoint: null, zones: [], enabled: true, save, load: vi.fn() });
    await act(async () => { vi.advanceTimersByTime(2000); await Promise.resolve(); });
    expect(save).toHaveBeenCalledTimes(1);
    expect(save.mock.calls[0][0]).toBe('p1');
    expect(save.mock.calls[0][1].exclusionZones.features[0].properties.id).toBe('a');
  });
  it('removing the entrance sends an explicit null accessPoint and then verifies ok', async () => {
    const save = vi.fn().mockResolvedValue({});
    const pt = { type: 'Point', coordinates: [0.5, 0.5] } as any;
    const load = vi.fn().mockResolvedValue({ accessPoint: null, exclusionZones: { type: 'FeatureCollection', features: [] } });
    const { result, rerender } = renderHook((p: any) => useConfigAutosave(p), { initialProps: { parcelId: 'p1', accessPoint: pt, zones: [], enabled: true, save, load } as any });
    rerender({ parcelId: 'p1', accessPoint: null, zones: [], enabled: true, save, load });
    await act(async () => { vi.advanceTimersByTime(800); await Promise.resolve(); });
    expect(save).toHaveBeenCalledTimes(1);
    const body = save.mock.calls[0][1];
    expect('accessPoint' in body && body.accessPoint === null).toBe(true);
    expect(JSON.parse(JSON.stringify(body))).toHaveProperty('accessPoint', null);
    let verdict = ''; await act(async () => { verdict = await result.current.verifyBeforeGenerate(); });
    expect(verdict).toBe('ok');
  });
});
