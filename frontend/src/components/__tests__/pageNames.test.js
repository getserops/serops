import { describe, it, expect } from 'vitest';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';
import { pageTitle } from '../PageTitle';

// One name per page: the menu entry, the page heading and the browser tab
// say the same thing, in English and in French.
const at = (obj, key) => key.split('.').reduce((o, k) => (o == null ? o : o[k]), obj);

// [path, name in English, name in French, menu key, heading key]
const PAGES = [
  ['/dash', 'Overview', "Vue d'ensemble", 'nav.overview', 'nav.overview'],
  ['/dash/issues', 'Issues', 'Problèmes', 'nav.issues', 'issues.systemIssues'],
  ['/dash/chat', 'AI Chat', 'Chat IA', 'nav.aiChat', 'chat.aiAssistant'],
  ['/dash/traces', 'Traces', 'Traces', 'nav.traces', 'traces.dashboard.title'],
  ['/dash/settings/delivery', 'Alerts & routing', 'Alertes et routage', 'nav.alertsRouting', 'nav.alertsRouting'],
  ['/dash/settings/routing-rules', 'Alerts & routing', 'Alertes et routage', 'nav.alertsRouting', 'nav.alertsRouting'],
  ['/dash/settings/ai', 'AI Providers', 'Fournisseurs IA', 'settings.ai.title', 'ai.title'],
  ['/dash/settings/sentinel', 'Sentinel', 'Sentinel', 'sentinel.title', 'sentinel.title'],
  ['/dash/settings/data', 'Data retention', 'Rétention des données', 'settings.data.title', 'dataRetention.title'],
  ['/dash/settings/traces', 'Trace ingest keys', "Clés d'ingestion des traces", 'traces.settings.menuLabel', 'traces.settings.title'],
  ['/dash/settings/clusters', 'Clusters', 'Clusters', 'clusters.menuLabel', 'clusters.title'],
  ['/dash/settings/security', 'Security', 'Sécurité', 'settings.security.title', 'security.title'],
  ['/dash/settings/preferences', 'Notification preferences', 'Préférences de notification', 'preferences.title', 'preferences.title'],
];

describe('one name per page', () => {
  for (const [path, nameEn, nameFr, menuKey, headingKey] of PAGES) {
    it(`${path}: menu, heading and tab agree`, () => {
      for (const [locale, name] of [[en, nameEn], [fr, nameFr]]) {
        const t = (key) => at(locale, key) ?? key;
        expect(t(menuKey)).toBe(name);
        expect(t(headingKey)).toBe(name);
        expect(pageTitle(path, t)).toBe(`${name} · SerOps`);
      }
    });
  }

  it('the two tabs of Alerts & routing are named in sentence case', () => {
    expect([at(en, 'settings.delivery.title'), at(en, 'settings.routing.title')]).toEqual(['Delivery channels', 'Routing rules']);
    expect([at(fr, 'settings.delivery.title'), at(fr, 'settings.routing.title')]).toEqual(['Canaux de diffusion', 'Règles de routage']);
  });

  it('the demo landing page is named "Live demo"', () => {
    expect(at(en, 'login.demoOnlyPageName')).toBe('Live demo');
    expect(at(fr, 'login.demoOnlyPageName')).toBe('Démo en direct');
  });
});

describe('French wording', () => {
  it('says "problème" for an issue on the Overview card, as the menu does', () => {
    const card = Object.values(at(fr, 'dashboard.attention')).filter((v) => typeof v === 'string').join(' ');
    expect(card).not.toMatch(/incident/i);
    expect(card).toMatch(/problème/);
  });

  it('writes page names in sentence case', () => {
    for (const key of ['nav.dashboard', 'auditLog.title', 'settings.data.title', 'preferences.title', 'security.title']) {
      const words = at(fr, key).split(/[\s']+/).slice(1);
      expect(words.filter((w) => /^[A-ZÀ-Ý][a-zà-ÿ]/.test(w))).toEqual([]);
    }
  });
});
