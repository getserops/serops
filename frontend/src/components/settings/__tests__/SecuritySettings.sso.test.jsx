import '@testing-library/jest-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';

vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: (k) => k }) }));
vi.mock('react-toastify', () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const svc = vi.hoisted(() => ({
    getSecuritySettings: vi.fn(), updateSecuritySettings: vi.fn(), getSSOConfig: vi.fn(), updateSSOConfig: vi.fn(),
}));
vi.mock('../../../services/enterpriseSettings.service', () => ({ default: svc }));
vi.mock('../../../services/organisation.service', () => ({
    OrganisationService: { getRoles: vi.fn().mockResolvedValue({ custom: [] }), getTeams: vi.fn().mockResolvedValue([]) },
}));
const edition = vi.hoisted(() => ({ features: [], section: null, scim: null }));
vi.mock('../../../utils/edition', () => ({
    useEdition: () => ({ enterprise_available: true, features: edition.features, license: null }),
    hasFeature: (e, code) => e.features.includes(code),
    get enterpriseSecuritySections() {
        return {
            ...(edition.section ? { saml: { key: 'saml', feature: 'saml', Component: edition.section } } : {}),
            ...(edition.scim ? { scim: { key: 'scim', feature: 'scim', Component: edition.scim } } : {}),
        };
    },
}));

import SecuritySettings from '../SecuritySettings';

const SSO = {
    sso_enabled: true, sso_provider: 'oidc', sso_enforced: false, sso_client_id: 'c', sso_discovery_url: 'https://idp/.well-known',
    sso_role_mappings: [], sso_default_role: 'viewer', sso_team_mappings: [], sso_domains: [], sso_groups_claim: 'groups',
};

const renderWith = async (sso) => {
    svc.getSecuritySettings.mockResolvedValue({ session: { timeout_minutes: 480 } });
    svc.getSSOConfig.mockResolvedValue({ ...SSO, ...sso });
    render(<SecuritySettings />);
    await screen.findByText('security.protocol');
};

describe('Security settings: SSO protocol', () => {
    beforeEach(() => {
        Object.values(svc).forEach((fn) => fn.mockReset());
        svc.updateSecuritySettings.mockResolvedValue({});
        svc.updateSSOConfig.mockResolvedValue({});
        edition.features = [];
        edition.section = null;
        edition.scim = null;
    });

    it('offers SAML with the Enterprise label, and explains it without a license', async () => {
        await renderWith({});
        fireEvent.click(screen.getByRole('radio', { name: /security.protocolSaml/ }));
        expect(await screen.findByText('security.samlEnterprise')).toBeInTheDocument();
        // One notice for SAML, one for SCIM provisioning, both to the pricing page.
        const links = screen.getAllByRole('link', { name: 'enterprise.seePricing' });
        expect(links).toHaveLength(2);
        links.forEach((a) => expect(a).toHaveAttribute('href', 'https://serops.ai/pricing'));
        // No group rules or enforcement for a protocol that cannot be used.
        expect(screen.queryByText('security.ssoRoles')).not.toBeInTheDocument();
        expect(screen.queryByText('security.enforceSso')).not.toBeInTheDocument();
    });

    it('shows the Enterprise panel when licensed, and saves it with the page', async () => {
        const save = vi.fn().mockResolvedValue();
        edition.features = ['saml'];
        edition.section = ({ registerSave }) => { registerSave(save); return <div>saml-panel</div>; };
        await renderWith({ sso_provider: 'saml' });
        expect(screen.getByText('saml-panel')).toBeInTheDocument();
        expect(screen.getByText('security.groupsAttribute')).toBeInTheDocument();
        expect(screen.queryByText('security.extraScopes')).not.toBeInTheDocument();
        fireEvent.click(screen.getByRole('switch', { name: /^security\.enforceSso / }));
        fireEvent.click(screen.getByRole('button', { name: 'common.saveChanges' }));
        await waitFor(() => expect(svc.updateSSOConfig).toHaveBeenCalled());
        expect(save).toHaveBeenCalled();
        expect(svc.updateSSOConfig.mock.calls[0][0]).toMatchObject({ sso_provider: 'saml', sso_enforced: true });
    });

    it('OIDC keeps its fields and can be enforced without a license', async () => {
        await renderWith({});
        expect(screen.getByText('security.oidcConfig')).toBeInTheDocument();
        fireEvent.click(screen.getByRole('switch', { name: /^security\.enforceSso / }));
        fireEvent.click(screen.getByRole('button', { name: 'common.saveChanges' }));
        await waitFor(() => expect(svc.updateSSOConfig).toHaveBeenCalled());
        expect(svc.updateSSOConfig.mock.calls[0][0]).toMatchObject({ sso_provider: 'oidc', sso_enforced: true });
    });

    it('turning SSO off sends enforcement off', async () => {
        await renderWith({ sso_enforced: true });
        fireEvent.click(screen.getByRole('switch', { name: /^security\.enableSso / }));
        fireEvent.click(screen.getByRole('button', { name: 'common.saveChanges' }));
        await waitFor(() => expect(svc.updateSSOConfig).toHaveBeenCalled());
        expect(svc.updateSSOConfig.mock.calls[0][0]).toMatchObject({ sso_provider: 'none', sso_enforced: false });
    });

    it('explains SCIM provisioning without the license', async () => {
        edition.scim = () => <div>scim-panel</div>;
        await renderWith({});
        expect(screen.getByText('security.scimEnterprise')).toBeInTheDocument();
        expect(screen.queryByText('scim-panel')).not.toBeInTheDocument();
    });

    it('shows the SCIM panel when licensed', async () => {
        edition.features = ['scim'];
        edition.scim = () => <div>scim-panel</div>;
        await renderWith({});
        expect(screen.getByText('scim-panel')).toBeInTheDocument();
        expect(screen.queryByText('security.scimEnterprise')).not.toBeInTheDocument();
    });
});
