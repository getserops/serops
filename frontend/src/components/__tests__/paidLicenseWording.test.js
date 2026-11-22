import { describe, it, expect } from 'vitest';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';

// The paid features start with the Business plan, so the key is a "paid
// license" ("licence payante"), never an "Enterprise license".
// The strings of the paid modules have the same check in
// src/ee/license/__tests__/paidLicenseWording.test.js: this file must not
// import from src/ee/, which the Community build does not have.
const texts = (value) => {
  if (typeof value === 'string') return [value];
  if (value && typeof value === 'object') return Object.values(value).flatMap(texts);
  return [];
};
const naming = /enterprise licen[sc]e|licence enterprise|serops enterprise|enterprise features|fonctionnalités (de gouvernance )?enterprise/i;

describe('paid license wording', () => {
  it('no app string names the key or the features "Enterprise"', () => {
    const all = [en, fr].flatMap(texts);
    expect(all.length).toBeGreaterThan(1000);
    expect(all.filter((s) => naming.test(s))).toEqual([]);
  });

  it('the notice and the badge say "paid license" in both languages', () => {
    expect(en.enterprise.label).toBe('Paid license');
    expect(fr.enterprise.label).toBe('Licence payante');
    for (const s of [en.enterprise.notice, en.security.samlEnterprise, en.security.scimEnterprise, en.auditLog.streamingEnterprise]) {
      expect(s).toMatch(/paid license/);
    }
    for (const s of [fr.enterprise.notice, fr.security.samlEnterprise, fr.security.scimEnterprise, fr.auditLog.streamingEnterprise]) {
      expect(s).toMatch(/licence payante/);
    }
  });
});
