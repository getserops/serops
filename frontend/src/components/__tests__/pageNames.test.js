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
  ['/dash/settings', 'General', 'Général', 'settings.general.menuLabel', 'settings.general.menuLabel'],
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

  // Final pass: every short French label, not only the page names. A word
  // after the first keeps a capital only when it is a name.
  it('has no label in English title case', () => {
    const names = new Set(('SerOps Kubernetes Slack Sentinel GitHub GitLab Jira PagerDuty Teams Microsoft Google OpenTelemetry Prometheus '
      + 'Loki Grafana Sentry Datadog Anthropic OpenAI Azure DevOps Docker Helm Git Claude Okta Entra Keycloak Community Business Enterprise '
      + 'Entreprise OpenID Connect WebP Viewer User Admin Build/Release GitLab.com Pro Mo Webhook Bitbucket Jenkins Realm Ariane').split(' '));
    const skip = new Set(['roles.builtinDesc', 'projectAccess.createTeamsFirst', 'settings.general.organisation.logoHint',
      'security.protocolOidcDesc', 'security.discoveryUrlHint', 'globalIntegrations.integrationNamePlaceholder']);
    const flat = (obj, prefix = '') => Object.entries(obj).flatMap(([k, v]) => (
      typeof v === 'string' ? [[prefix + k, v]] : flat(v, `${prefix}${k}.`)));
    const found = [];
    for (const [key, value] of flat(fr)) {
      if (value.length > 60 || skip.has(key)) continue;
      const words = value.split(' ');
      words.slice(1).forEach((word, i) => {
        if (word.startsWith('"') || /[.!?:]$/.test(words[i])) return;
        const core = word.replace(/^[.,:;()«»"']+|[.,:;()«»"']+$/g, '').replace(/^[dlDL]['’]/, '');
        if (/^[A-ZÀ-Ý][a-zà-ÿ]{2,}/.test(core) && !/^[A-ZÀ-Ý][a-zà-ÿ]+[A-Z]/.test(core) && !names.has(core)) found.push(`${key}: ${value}`);
      });
    }
    expect(found).toEqual([]);
  });

  // The menu says "Problèmes": where the English says "issue", the French
  // does not say "incident".
  it('says "problème" wherever the English says "issue"', () => {
    const flat = (obj, prefix = '') => Object.entries(obj).flatMap(([k, v]) => (
      typeof v === 'string' ? [[prefix + k, v]] : flat(v, `${prefix}${k}.`)));
    const english = Object.fromEntries(flat(en));
    const found = flat(fr).filter(([key, value]) => /incident/i.test(value)
      && /issue/i.test(english[key] || '') && !/incident/i.test(english[key] || ''));
    expect(found).toEqual([]);
  });

  it('writes page names in sentence case', () => {
    for (const key of ['nav.dashboard', 'auditLog.title', 'settings.data.title', 'preferences.title', 'security.title']) {
      const words = at(fr, key).split(/[\s']+/).slice(1);
      expect(words.filter((w) => /^[A-ZÀ-Ý][a-zà-ÿ]/.test(w))).toEqual([]);
    }
  });
});
