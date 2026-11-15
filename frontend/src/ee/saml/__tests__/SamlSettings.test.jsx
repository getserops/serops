import '@testing-library/jest-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => k }) }));
const api = vi.hoisted(() => ({ get: vi.fn(), put: vi.fn() }));
vi.mock('../../../services/api-client', () => ({ default: api }));

import SamlSettings from '../SamlSettings';
import fs from 'fs';
import path from 'path';
import { strings } from '../i18n';

const CONFIG = {
    licensed: true, configured: true, active: true,
    sp_entity_id: 'https://serops.test/api/ee/saml/abc/metadata/',
    acs_url: 'https://serops.test/api/ee/saml/abc/acs/',
    metadata_url: 'https://serops.test/api/ee/saml/abc/metadata/',
    sp_certificate: '-----BEGIN CERTIFICATE-----\nMIIB\n-----END CERTIFICATE-----',
    idp_metadata_url: 'https://login.example.test/metadata.xml',
    idp_entity_id: 'https://sts.example.test/', idp_sso_url: 'https://login.example.test/saml2',
    idp_certificates: [{ subject: 'CN=Microsoft Azure Federated SSO Certificate', expires: '2029-11-13T00:00:00', sha256: 'AA:BB' }],
    email_attribute: '', first_name_attribute: '', last_name_attribute: '',
    want_assertions_encrypted: false, allow_idp_initiated: true, clock_skew_seconds: 180,
};

describe('SAML settings (Enterprise)', () => {
    beforeEach(() => Object.values(api).forEach((fn) => fn.mockReset()));

    it('shows what to register at the identity provider and what it read from it', async () => {
        api.get.mockResolvedValue({ data: CONFIG });
        render(<SamlSettings registerSave={() => {}} />);
        expect(await screen.findByDisplayValue(CONFIG.acs_url)).toBeInTheDocument();
        expect(screen.getByDisplayValue(CONFIG.sp_entity_id)).toBeInTheDocument();
        expect(screen.getByText(CONFIG.idp_sso_url)).toBeInTheDocument();
        expect(screen.getByText(/Microsoft Azure Federated SSO Certificate/)).toBeInTheDocument();
        expect(screen.getByRole('link', { name: 'ee.saml.downloadMetadata' })).toHaveAttribute('href', CONFIG.metadata_url);
    });

    it('says when the identity provider is not configured yet', async () => {
        api.get.mockResolvedValue({ data: { ...CONFIG, configured: false, idp_certificates: [] } });
        render(<SamlSettings registerSave={() => {}} />);
        expect(await screen.findByText('ee.saml.notConfigured')).toBeInTheDocument();
    });

    it('saves only what changed, when the page is saved', async () => {
        api.get.mockResolvedValue({ data: CONFIG });
        api.put.mockResolvedValue({ data: { ...CONFIG, email_attribute: 'mail', allow_idp_initiated: false } });
        let save = null;
        render(<SamlSettings registerSave={(fn) => { save = fn; }} />);
        await screen.findByDisplayValue(CONFIG.acs_url);
        fireEvent.change(screen.getByLabelText('ee.saml.emailAttribute'), { target: { value: 'mail' } });
        fireEvent.click(screen.getByRole('switch', { name: /^ee\.saml\.idpInitiated / }));
        await waitFor(() => expect(save).toBeTypeOf('function'));
        await save();
        expect(api.put).toHaveBeenCalledWith('/ee/saml/config/', { email_attribute: 'mail', allow_idp_initiated: false });
    });

    it('sends nothing when nothing changed', async () => {
        api.get.mockResolvedValue({ data: CONFIG });
        let save = null;
        render(<SamlSettings registerSave={(fn) => { save = fn; }} />);
        await screen.findByDisplayValue(CONFIG.acs_url);
        await save();
        expect(api.put).not.toHaveBeenCalled();
    });

    it('shows a message, not a broken panel, when the settings cannot be read', async () => {
        api.get.mockRejectedValue(new Error('403'));
        render(<SamlSettings registerSave={() => {}} />);
        expect(await screen.findByText('ee.saml.loadFailed')).toBeInTheDocument();
    });
});

describe('SAML strings', () => {
    it('has every key the panel uses, in English and French', () => {
        const src = fs.readFileSync(path.resolve(__dirname, '../SamlSettings.jsx'), 'utf8');
        const used = [...src.matchAll(/\bt\(\s*'ee\.saml\.([a-zA-Z]+)'/g)].map((m) => m[1])
            .concat(['emailAttribute', 'firstNameAttribute', 'lastNameAttribute']);
        expect(used.length).toBeGreaterThan(10);
        for (const lng of ['en', 'fr']) {
            expect(used.filter((key) => !strings[lng][key])).toEqual([]);
        }
        expect(Object.keys(strings.fr).sort()).toEqual(Object.keys(strings.en).sort());
    });
});
