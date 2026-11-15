import '@testing-library/jest-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => k }) }));
vi.mock('react-toastify', () => ({ toast: { error: vi.fn() } }));
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), delete: vi.fn() }));
vi.mock('../../../services/api-client', () => ({ default: api }));

import ScimSettings from '../ScimSettings';
import fs from 'fs';
import path from 'path';
import { strings } from '../i18n';

const TOKEN = {
    id: 7, name: 'Entra ID', prefix: 'serops_scim_Ab12', created_at: '2026-11-14T10:00:00+00:00',
    created_by: 'admin@acme.test', last_used_at: null, revoked_at: null,
};
const DATA = { licensed: true, base_url: 'https://serops.test/api/ee/scim/v2', tokens: [TOKEN] };

describe('SCIM settings (Enterprise)', () => {
    beforeEach(() => Object.values(api).forEach((fn) => fn.mockReset()));

    it('shows the base URL and the tokens, never their value', async () => {
        api.get.mockResolvedValue({ data: DATA });
        render(<ScimSettings />);
        expect(await screen.findByDisplayValue(DATA.base_url)).toBeInTheDocument();
        expect(screen.getByText('Entra ID')).toBeInTheDocument();
        expect(screen.getByText('serops_scim_Ab12…')).toBeInTheDocument();
        expect(screen.getByText('ee.scim.never')).toBeInTheDocument();
    });

    it('shows a new token once, after it is created', async () => {
        api.get.mockResolvedValue({ data: DATA });
        api.post.mockResolvedValue({ data: { ...TOKEN, id: 8, name: 'Okta', token: 'serops_scim_secretvalue' } });
        render(<ScimSettings />);
        await screen.findByDisplayValue(DATA.base_url);
        const create = screen.getByRole('button', { name: 'ee.scim.create' });
        expect(create).toBeDisabled();
        fireEvent.change(screen.getByLabelText('ee.scim.tokenName'), { target: { value: ' Okta ' } });
        fireEvent.click(create);
        expect(await screen.findByDisplayValue('serops_scim_secretvalue')).toBeInTheDocument();
        expect(api.post).toHaveBeenCalledWith('/ee/scim/tokens/', { name: 'Okta' });
    });

    it('revokes after confirmation', async () => {
        api.get.mockResolvedValue({ data: DATA });
        api.delete.mockResolvedValue({});
        const confirm = vi.spyOn(window, 'confirm').mockReturnValueOnce(false).mockReturnValueOnce(true);
        render(<ScimSettings />);
        const button = await screen.findByRole('button', { name: 'ee.scim.revoke' });
        fireEvent.click(button);
        expect(api.delete).not.toHaveBeenCalled();
        fireEvent.click(button);
        await waitFor(() => expect(api.delete).toHaveBeenCalledWith('/ee/scim/tokens/7/'));
        confirm.mockRestore();
    });

    it('marks revoked tokens and offers no button for them', async () => {
        api.get.mockResolvedValue({ data: { ...DATA, tokens: [{ ...TOKEN, revoked_at: '2026-11-14T11:00:00+00:00' }] } });
        render(<ScimSettings />);
        expect(await screen.findByText('ee.scim.revoked')).toBeInTheDocument();
        expect(screen.queryByRole('button', { name: 'ee.scim.revoke' })).not.toBeInTheDocument();
    });

    it('shows a message, not a broken panel, when the settings cannot be read', async () => {
        api.get.mockRejectedValue(new Error('403'));
        render(<ScimSettings />);
        expect(await screen.findByText('ee.scim.loadFailed')).toBeInTheDocument();
    });
});

describe('SCIM strings', () => {
    it('has every key the panel uses, in English and French', () => {
        const src = fs.readFileSync(path.resolve(__dirname, '../ScimSettings.jsx'), 'utf8');
        const used = [...src.matchAll(/\bt\(\s*'ee\.scim\.([a-zA-Z]+)'/g)].map((m) => m[1]);
        expect(used.length).toBeGreaterThan(15);
        for (const lng of ['en', 'fr']) {
            expect(used.filter((key) => !strings[lng][key])).toEqual([]);
        }
        expect(Object.keys(strings.fr).sort()).toEqual(Object.keys(strings.en).sort());
    });
});
