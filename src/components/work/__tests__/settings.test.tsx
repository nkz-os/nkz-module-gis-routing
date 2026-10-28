import React from 'react';
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { i18n } from '@nekazari/sdk';
import '../../../i18n';

vi.mock('@nekazari/ui-kit', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@nekazari/ui-kit')>();
  const Select = (p: any) => (
    <select id={p.id} value={p.value} onChange={(e) => p.onValueChange(e.target.value)} disabled={p.disabled}>
      {p.options.map((o: any) => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  );
  return { ...actual, Select };
});
vi.mock('../../../services/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('../../../services/api')>();
  return { ...actual, api: { getSettings: vi.fn(), putSettings: vi.fn() } };
});
import { api, ApiError } from '../../../services/api';
import { SettingsBlock } from '../SettingsBlock';

const setRoles = (roles: string[]) => {
  (window as any).__nekazariAuthContext = { token: 't', user: { roles } };
};

beforeAll(async () => { await i18n.changeLanguage('es'); });
beforeEach(() => {
  vi.clearAllMocks();
  (api.getSettings as any).mockResolvedValue({ dispatch_notification: 'immediate' });
  (api.putSettings as any).mockResolvedValue({ dispatch_notification: 'digest' });
});
afterEach(() => { cleanup(); delete (window as any).__nekazariAuthContext; });

describe('SettingsBlock', () => {
  it('renders nothing and does not call the API for non-admins', () => {
    setRoles(['Farmer']);
    const { container } = render(<SettingsBlock />);
    expect(container).toBeEmptyDOMElement();
    expect(api.getSettings).not.toHaveBeenCalled();
  });

  it.each(['TenantAdmin', 'PlatformAdmin'])('shows a labelled select with the stored value for %s', async (role) => {
    setRoles([role]);
    (api.getSettings as any).mockResolvedValue({ dispatch_notification: 'none' });
    render(<SettingsBlock />);
    const select = await screen.findByLabelText('Aviso al guardar una ruta');
    await waitFor(() => expect((select as HTMLSelectElement).value).toBe('none'));
  });

  it('saves the new value and confirms', async () => {
    setRoles(['TenantAdmin']);
    render(<SettingsBlock />);
    const select = await screen.findByLabelText('Aviso al guardar una ruta');
    await waitFor(() => expect(api.getSettings).toHaveBeenCalled());
    fireEvent.change(select, { target: { value: 'digest' } });
    await waitFor(() => expect(api.putSettings).toHaveBeenCalledWith('digest'));
    expect(await screen.findByText('Ajuste guardado')).toBeInTheDocument();
  });

  it('reverts and shows the forbidden message on 403', async () => {
    setRoles(['TenantAdmin']);
    (api.putSettings as any).mockRejectedValue(new ApiError(403, { code: 'FORBIDDEN', detail: 'x' }));
    render(<SettingsBlock />);
    const select = (await screen.findByLabelText('Aviso al guardar una ruta')) as HTMLSelectElement;
    await waitFor(() => expect(api.getSettings).toHaveBeenCalled());
    fireEvent.change(select, { target: { value: 'none' } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Solo los administradores');
    expect(select.value).toBe('immediate');
  });

  it('under StrictMode (simulated unmount) a change still re-enables the select and confirms', async () => {
    setRoles(['TenantAdmin']);
    render(<React.StrictMode><SettingsBlock /></React.StrictMode>);
    const select = (await screen.findByLabelText('Aviso al guardar una ruta')) as HTMLSelectElement;
    await waitFor(() => expect(api.getSettings).toHaveBeenCalled());
    fireEvent.change(select, { target: { value: 'digest' } });
    expect(await screen.findByText('Ajuste guardado')).toBeInTheDocument();
    await waitFor(() => expect(select.disabled).toBe(false));
  });
});
