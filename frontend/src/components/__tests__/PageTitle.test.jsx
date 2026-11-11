import { describe, it, expect } from 'vitest';
import { pageTitle } from '../PageTitle';

describe('pageTitle', () => {
  it('tells members, teams and roles apart', () => {
    const t = (k) => k;
    expect(pageTitle('/dash/settings/team', t)).toContain('settings.team.title');
    expect(pageTitle('/dash/settings/teams', t)).toContain('teams.title');
    expect(pageTitle('/dash/settings/roles', t)).toContain('roles.title');
  });
});
