import { describe, it, expect, vi, beforeEach } from 'vitest';

const get = vi.fn();
vi.mock('../../services/api-client', () => ({ default: { get: (...args) => get(...args) } }));

describe('edition', () => {
    beforeEach(() => {
        vi.resetModules();
        get.mockReset();
    });

    it('reads the edition from the server', async () => {
        get.mockResolvedValue({ data: { enterprise_available: true, features: ['saml'], license: { status: 'valid' } } });
        const { fetchEdition, hasFeature } = await import('../edition');
        const edition = await fetchEdition();
        expect(get).toHaveBeenCalledWith('/organisation/edition/');
        expect(hasFeature(edition, 'saml')).toBe(true);
        expect(hasFeature(edition, 'scim')).toBe(false);
    });

    it('falls back to Community when the server does not answer', async () => {
        get.mockRejectedValue(new Error('offline'));
        const { fetchEdition, COMMUNITY, hasFeature } = await import('../edition');
        expect(await fetchEdition()).toEqual(COMMUNITY);
        expect(hasFeature(undefined, 'saml')).toBe(false);
    });

    it('lists Enterprise settings pages only as data (works with or without src/ee)', async () => {
        const { enterpriseSettingsPages } = await import('../edition');
        expect(Array.isArray(enterpriseSettingsPages)).toBe(true);
        enterpriseSettingsPages.forEach((page) => {
            expect(typeof page.path).toBe('string');
            expect(typeof page.label).toBe('function');
        });
    });

    it('places each Enterprise page after the menu item it names, or last', async () => {
        const { withEnterprisePages, enterpriseSettingsPages } = await import('../edition');
        const items = [{ path: '/a' }, { path: '/dash/settings/team' }, { path: '/z' }];
        const out = withEnterprisePages(items, (page) => ({ path: `/dash/settings/${page.path}`, after: page.after }));
        expect(out).toHaveLength(items.length + enterpriseSettingsPages.length);
        enterpriseSettingsPages.forEach((page) => {
            const at = out.findIndex((i) => i.path === `/dash/settings/${page.path}`);
            if (page.after) expect(out[at - 1].path).toBe(page.after);
        });
        expect(items).toHaveLength(3); // input untouched
    });
});
