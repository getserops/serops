import { describe, it, expect } from 'vitest';
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

// Review item 19: inputs without an accessible name (the chat box, General,
// Sentinel, Preferences, Audit Log). Their visible label was a sibling with
// no link to the control. Each control now names itself with the same
// translated text. This reads the sources so that a new control added to
// one of these pages without a name fails here, not in an audit.
const FILES = [
  'ChatIssues.jsx',
  'settings/GeneralSettings.jsx',
  'settings/SentinelSettings.jsx',
  'settings/UserPreferencesSettings.jsx',
  'settings/AuditLogSettings.jsx',
];
const CONTROL = /<(input|select|textarea|Form\.Select|Form\.Control)\b[^>]*?>/gs;

describe.each(FILES)('%s', (file) => {
  const src = readFileSync(resolve(__dirname, '..', file), 'utf8');
  const controls = src.match(CONTROL) || [];

  it('has controls to check', () => {
    expect(controls.length).toBeGreaterThan(0);
  });

  it('every control has an accessible name', () => {
    const unnamed = controls
      .filter((tag) => !/type="(file|hidden)"/.test(tag))
      .filter((tag) => !/\b(aria-label|aria-labelledby|id)=/.test(tag));
    expect(unnamed).toEqual([]);
  });
});
