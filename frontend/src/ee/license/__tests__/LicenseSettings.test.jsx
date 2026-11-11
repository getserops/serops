import '@testing-library/jest-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => k }) }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn(), delete: vi.fn() }));
vi.mock('../../../services/api-client', () => ({ default: api }));

import LicenseSettings from '../LicenseSettings';
import { toast } from 'react-toastify';
import fs from 'fs';
import path from 'path';
import { strings } from '../i18n';

const VALID = {
    status: 'valid', id: 'lic_1', licensee: 'Acme Corp', expires: '2027-10-21',
    features: ['saml'], feature_labels: { saml: 'SAML 2.0 single sign-on' },
};

describe('Enterprise license settings', () => {
    beforeEach(() => Object.values(api).forEach((fn) => fn.mockReset()));

    it('says Community works fully when no key is installed', async () => {
        api.get.mockResolvedValue({ data: { status: 'none' } });
        render(<LicenseSettings />);
        expect(await screen.findByText('ee.license.none')).toBeInTheDocument();
        expect(screen.queryByText('ee.license.remove')).not.toBeInTheDocument();
        expect(screen.getByRole('button', { name: 'ee.license.install' })).toBeDisabled();
    });

    it('installs a pasted key and shows it', async () => {
        api.get.mockResolvedValue({ data: { status: 'none' } });
        api.put.mockResolvedValue({ data: VALID });
        render(<LicenseSettings />);
        fireEvent.change(await screen.findByLabelText('ee.license.keyLabel'), { target: { value: '{"format":1}' } });
        fireEvent.click(screen.getByRole('button', { name: 'ee.license.install' }));
        await waitFor(() => expect(api.put).toHaveBeenCalledWith('/ee/license/', { license: '{"format":1}' }));
        expect(await screen.findByText('Acme Corp')).toBeInTheDocument();
        expect(screen.getByText('SAML 2.0 single sign-on')).toBeInTheDocument();
        expect(toast.success).toHaveBeenCalledWith('ee.license.installed');
    });

    it('shows the server reason when a key is refused', async () => {
        api.get.mockResolvedValue({ data: { status: 'none' } });
        api.put.mockRejectedValue({ response: { data: { error: 'The signature does not match' } } });
        render(<LicenseSettings />);
        fireEvent.change(await screen.findByLabelText('ee.license.keyLabel'), { target: { value: 'x' } });
        fireEvent.click(screen.getByRole('button', { name: 'ee.license.install' }));
        await waitFor(() => expect(toast.error).toHaveBeenCalledWith('The signature does not match'));
    });

    it('explains that an expired key keeps the data', async () => {
        api.get.mockResolvedValue({ data: { ...VALID, status: 'expired' } });
        render(<LicenseSettings />);
        expect(await screen.findByText('ee.license.expiredNote')).toBeInTheDocument();
        expect(screen.getByText('ee.license.statusExpired')).toBeInTheDocument();
    });
});

describe('Enterprise license strings', () => {
    it('has every key the page uses, in English and French', () => {
        const src = fs.readFileSync(path.resolve(__dirname, '../LicenseSettings.jsx'), 'utf8');
        const used = [...src.matchAll(/\bt\(\s*'ee\.license\.([a-zA-Z]+)'/g)].map((m) => m[1]);
        expect(used.length).toBeGreaterThan(5);
        for (const lng of ['en', 'fr']) {
            expect(used.filter((key) => !strings[lng][key])).toEqual([]);
        }
        expect(Object.keys(strings.fr).sort()).toEqual(Object.keys(strings.en).sort());
    });
});
