import { describe, it, expect } from 'vitest';
import { pageTitle } from '../PageTitle';

describe('pageTitle', () => {
  it('tells members, teams and roles apart', () => {
    const t = (k) => k;
    expect(pageTitle('/dash/settings/team', t)).toContain('settings.team.title');
    expect(pageTitle('/dash/settings/teams', t)).toContain('teams.title');
    expect(pageTitle('/dash/settings/roles', t)).toContain('roles.title');
  });

  it('names the pages of the paid modules, and falls back to "Settings" without them', () => {
    const names = { 'ee.auditStream.menuLabel': 'Audit Streaming', 'ee.license.menuLabel': 'Paid license', 'auditLog.title': 'Audit Log', 'nav.settings': 'Settings' };
    const withEe = (k) => names[k] ?? k;
    expect(pageTitle('/dash/settings/audit-streaming', withEe)).toBe('Audit Streaming · SerOps');
    expect(pageTitle('/dash/settings/license', withEe)).toBe('Paid license · SerOps');
    expect(pageTitle('/dash/settings/audit', withEe)).toBe('Audit Log · SerOps');
    // Community build: the ee names are not loaded, so t() gives the key back.
    const community = (k) => (k.startsWith('ee.') ? k : names[k] ?? k);
    expect(pageTitle('/dash/settings/license', community)).toBe('Settings · SerOps');
    expect(pageTitle('/dash/settings/audit-streaming', community)).toBe('Settings · SerOps');
  });
});
