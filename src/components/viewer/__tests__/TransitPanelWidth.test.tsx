import React from 'react';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import '../../../i18n';

vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select aria-label="machine" value={p.value} onChange={(e) => p.onValueChange(e.target.value)}>
      {p.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  return { ...actual, Select };
});
vi.mock('../../../services/api', async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()), api: { listEquipment: vi.fn() },
}));
import { api } from '../../../services/api';
import { TransitPanel } from '../TransitPanel';
import { EV } from '../routingMode';

const widths: unknown[] = [];
const onWidth = (e: Event) => widths.push((e as CustomEvent).detail.widthM);
beforeEach(() => {
  widths.length = 0;
  window.addEventListener(EV.transitWidth, onWidth);
  vi.mocked(api.listEquipment).mockResolvedValue([
    { id: 'i1', name: 'Sprayer', machine_role: 'implement', implementWidth: 24 },
    { id: 'i2', name: 'Roller', machine_role: 'implement', implementWidth: 6 },
  ] as any);
});
afterEach(() => { cleanup(); window.removeEventListener(EV.transitWidth, onWidth); vi.clearAllMocks(); });

const panel = () => render(<TransitPanel pfState="picking-a" alt={null} onSave={() => {}} onCancel={() => {}} />);

describe('cockpit A-B machine width', () => {
  it('takes the width from the chosen machine and tells the map', async () => {
    panel();
    await waitFor(() => expect(widths).toContain(24));
    fireEvent.change(screen.getByLabelText('machine'), { target: { value: 'i2' } });
    await waitFor(() => expect(widths[widths.length - 1]).toBe(6));
    expect((screen.getByLabelText(/Ancho de trabajo/) as HTMLInputElement).value).toBe('6');
  });

  it('a typed width overrides it; an empty field reports no width', async () => {
    panel();
    await waitFor(() => expect(widths).toContain(24));
    const input = screen.getByLabelText(/Ancho de trabajo/);
    fireEvent.change(input, { target: { value: '3,5' } });
    expect(widths[widths.length - 1]).toBe(3.5);
    fireEvent.change(input, { target: { value: '' } });
    expect(widths[widths.length - 1]).toBeNull();
  });

  it('a machine with no width leaves the field empty, never a default', async () => {
    vi.mocked(api.listEquipment).mockResolvedValue([{ id: 'x', name: 'Bare', machine_role: 'implement' }] as any);
    panel();
    await act(async () => {});
    expect((screen.getByLabelText(/Ancho de trabajo/) as HTMLInputElement).value).toBe('');
    expect(widths[widths.length - 1]).toBeNull();
  });
});
