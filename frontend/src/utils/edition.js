/**
 * Community or Enterprise, and which Enterprise features are licensed.
 *
 * Community code never imports src/ee/. Enterprise modules live in
 * src/ee/<name>/index.js and are found by the glob below; without the
 * directory the glob is empty and the app is the complete Community
 * edition (CI builds and tests it that way).
 *
 *   const edition = useEdition();
 *   {hasFeature(edition, 'saml') && <SamlSettings />}
 */
import { useEffect, useState } from 'react';

const modules = import.meta.glob('../ee/*/index.js', { eager: true });

/**
 * What each Enterprise module adds:
 *   settingsPages: [{ path, perm, after?, label(t), Component }]   (after: menu path to follow)
 *   projectTabs:   [{ key, label(t), icon?, visible({ project, can, canOnProject }), Component({ projectId }) }]
 */
export const enterpriseModules = Object.values(modules).map((m) => m.default).filter(Boolean);

/** Settings pages added by Enterprise modules (routes under /dash/settings/). */
export const enterpriseSettingsPages = enterpriseModules.flatMap((m) => m.settingsPages || []);

/** Tabs added to a project's page by Enterprise modules. */
export const enterpriseProjectTabs = enterpriseModules.flatMap((m) => m.projectTabs || []);

/** Menu items with each Enterprise page placed after the item it names (else last). */
export const withEnterprisePages = (items, toItem) => {
    const out = [...items];
    enterpriseSettingsPages.forEach((page) => {
        const item = toItem(page);
        const at = page.after ? out.findIndex((i) => i.path === page.after) : -1;
        if (at >= 0) out.splice(at + 1, 0, item);
        else out.push(item);
    });
    return out;
};

export const COMMUNITY = { enterprise_available: false, features: [], license: null };

const UPDATED_EVENT = 'serops:edition-updated';
let pending = null;

/** The edition from the server (GET /organisation/edition/), fetched once per page load. */
export const fetchEdition = () => {
    if (!pending) {
        pending = import('../services/api-client')
            .then(({ default: apiClient }) => apiClient.get('/organisation/edition/'))
            .then((res) => ({ ...COMMUNITY, ...(res?.data || {}) }))
            .catch(() => {
                pending = null; // try again next time; meanwhile, Community
                return COMMUNITY;
            });
    }
    return pending;
};

/** Re-read the edition (after a license key is installed or removed). */
export const refreshEdition = () => {
    pending = null;
    window.dispatchEvent(new Event(UPDATED_EVENT));
};

export const hasFeature = (edition, code) => Array.isArray(edition?.features) && edition.features.includes(code);

/** Hook: the edition, Community until the server answers. */
export const useEdition = () => {
    const [edition, setEdition] = useState(COMMUNITY);
    useEffect(() => {
        let live = true;
        const load = () => fetchEdition().then((e) => live && setEdition(e));
        load();
        window.addEventListener(UPDATED_EVENT, load);
        return () => {
            live = false;
            window.removeEventListener(UPDATED_EVENT, load);
        };
    }, []);
    return edition;
};
