import { describe, it, expect } from 'vitest';
import { strings as license } from '../i18n';
import * as access from '../../access/i18n';
import * as auditStream from '../../audit_stream/i18n';

// The strings of the paid modules: the key is a "paid license" ("licence
// payante"), never an "Enterprise license". The strings of the Community
// build have the same check in
// src/components/__tests__/paidLicenseWording.test.js.
const texts = (value) => {
  if (typeof value === 'string') return [value];
  if (value && typeof value === 'object') return Object.values(value).flatMap(texts);
  return [];
};
const naming = /enterprise licen[sc]e|licence enterprise|serops enterprise|enterprise features|fonctionnalités (de gouvernance )?enterprise/i;

describe('paid license wording, paid modules', () => {
  it('no string names the key or the features "Enterprise"', () => {
    const all = [license, access, auditStream].flatMap(texts);
    expect(all.length).toBeGreaterThan(40);
    expect(all.filter((s) => naming.test(s))).toEqual([]);
  });

  it('the license page is named "Paid license" in the menu and the heading', () => {
    expect([license.en.menuLabel, license.en.title]).toEqual(['Paid license', 'Paid license']);
    expect([license.fr.menuLabel, license.fr.title]).toEqual(['Licence payante', 'Licence payante']);
  });
});
