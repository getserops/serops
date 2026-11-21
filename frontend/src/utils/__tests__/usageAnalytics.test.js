import { describe, it, expect, beforeEach, vi } from 'vitest';
import { routeName, pageEvent, externalReferrer, outboundEvent, startUsageAnalytics, trackPage, trackEvent, _reset } from '../usageAnalytics';

const reply = (usage, ok = true) => vi.fn().mockResolvedValue({ ok, json: async () => ({ usage }) });
const USAGE = { script_path: '/_stats/script.js', website_id: '1a7ebe10-2af1-4cd1-9112-0cd037c77b70' };
const tag = () => document.head.querySelector('script[data-website-id]');

describe('route names', () => {
  it('never carries a record id, token or query string', () => {
    expect(routeName('/dash/data/details/acme-batch-20261118-42')).toBe('/dash/data/details/:id');
    expect(routeName('/dash/traces/4bf92f3577b34da6a3ce929d0e0e4736')).toBe('/dash/traces/:id');
    expect(routeName('/dash/traces/batch/b-1')).toBe('/dash/traces/batch/:id');
    expect(routeName('/dash/projects/17')).toBe('/dash/projects/:id');
    expect(routeName('/password/reset/MTI/abc-token')).toBe('/password/reset/:id/:id');
    expect(routeName('/dash/issues?search=customer+name#x')).toBe('/dash/issues');
    expect(routeName('/dash/settings/ai')).toBe('/dash/settings/ai');
    expect(routeName('/')).toBe('/');
  });

  it('names the two pages that are also events', () => {
    expect(pageEvent('/dash/data/details/:id')).toBe('analysis_opened');
    expect(pageEvent('/dash/chat')).toBe('chat_opened');
    expect(pageEvent('/dash/issues')).toBeNull();
  });

  it('names clicks out to GitHub and the docs, and nothing inside the app', () => {
    const origin = 'https://app.serops.ai';
    expect(outboundEvent('https://github.com/getserops/serops/issues/12', origin)).toBe('github_click');
    expect(outboundEvent('https://serops.ai/docs/user-guide/issues/', origin)).toBe('docs_click');
    expect(outboundEvent('https://docs.serops.ai/', origin)).toBe('docs_click');
    expect(outboundEvent('https://serops.ai/pricing', origin)).toBe('outbound_click');
    expect(outboundEvent('https://gitlab.acme.cloud/x/y/-/commit/abc', origin)).toBe('outbound_click');
    expect(outboundEvent('/dash/issues', origin)).toBeNull();
    expect(outboundEvent('https://app.serops.ai/dash/data/details/b-1', origin)).toBeNull();
    expect(outboundEvent('mailto:someone@example.com', origin)).toBeNull();
  });

  it('keeps only the site of an outside referrer', () => {
    expect(externalReferrer('https://serops.ai/pricing?utm_source=x', 'https://app.serops.ai')).toBe('https://serops.ai/');
    expect(externalReferrer('https://app.serops.ai/dash/data/details/b-1', 'https://app.serops.ai')).toBe('');
    expect(externalReferrer('', 'https://app.serops.ai')).toBe('');
  });
});

describe('usage counting', () => {
  beforeEach(() => {
    _reset();
    document.head.querySelectorAll('script[data-website-id]').forEach((s) => s.remove());
    delete window.umami;
  });

  it('loads nothing when the server has no usage setting', async () => {
    expect(await startUsageAnalytics(reply(null))).toBe(false);
    expect(await startUsageAnalytics(reply(USAGE, false))).toBe(false);
    expect(await startUsageAnalytics(vi.fn().mockRejectedValue(new Error('offline')))).toBe(false);
    expect(tag()).toBeNull();
    trackPage('/dash');
    trackEvent('demo_signin');
    expect(tag()).toBeNull();
  });

  it('refuses a script from another origin', async () => {
    expect(await startUsageAnalytics(reply({ ...USAGE, script_path: 'https://elsewhere.example/script.js' }))).toBe(false);
    expect(await startUsageAnalytics(reply({ ...USAGE, script_path: '//elsewhere.example/script.js' }))).toBe(false);
    expect(tag()).toBeNull();
  });

  it('loads the same-origin script with automatic tracking off, and reports names only', async () => {
    expect(await startUsageAnalytics(reply(USAGE))).toBe(true);
    const s = tag();
    expect(s.getAttribute('src')).toBe('/_stats/script.js');
    expect(s.getAttribute('data-auto-track')).toBe('false');
    expect(s.getAttribute('data-do-not-track')).toBe('true');
    expect(s.getAttribute('data-host-url')).toBe(`${window.location.origin}/_stats`);

    // Reported before the script has loaded: kept, then sent.
    trackPage('/dash/data/details/acme-batch-42');
    const sent = [];
    window.umami = { track: (fn) => sent.push(fn({ url: 'https://app/dash/data/details/acme-batch-42?x=1', title: 'acme-batch-42', website: USAGE.website_id })) };
    s.onload();
    trackEvent('demo_signin');

    expect(sent.map((p) => [p.name || 'pageview', p.url])).toEqual([
      ['pageview', '/dash/data/details/:id'],
      ['analysis_opened', '/dash/data/details/:id'],
      ['demo_signin', routeName(window.location.pathname)],
    ]);
    expect(JSON.stringify(sent)).not.toContain('acme-batch-42');
    expect(sent.every((p) => p.website === USAGE.website_id)).toBe(true);
  });
});
