// Every t('...') key the app uses must exist in both languages. A missing key
// renders as raw text ("common.active"), and a `t(key) || 'Fallback'` guard
// never fires because i18next returns the key itself.
import { describe, it, expect } from 'vitest';
import fs from 'fs';
import path from 'path';
import en from '../en.json';
import fr from '../fr.json';

const SRC = path.resolve(__dirname, '../..');

function flatten(obj, prefix = '', out = new Set()) {
  for (const [k, v] of Object.entries(obj)) {
    const key = prefix + k;
    if (v && typeof v === 'object') flatten(v, `${key}.`, out);
    else {
      out.add(key);
      const plural = key.match(/^(.*)_(one|other|zero)$/);
      if (plural) out.add(plural[1]);
    }
  }
  return out;
}

function usedKeys() {
  const keys = new Map();
  const walk = (dir) => {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const full = path.join(dir, entry.name);
      if (entry.isDirectory()) { if (entry.name !== '__tests__') walk(full); continue; }
      if (!/\.(jsx?|tsx?)$/.test(entry.name)) continue;
      const src = fs.readFileSync(full, 'utf8');
      for (const m of src.matchAll(/\bt\(\s*['"]([a-zA-Z0-9_]+(?:\.[a-zA-Z0-9_]+)+)['"]/g)) {
        if (!keys.has(m[1])) keys.set(m[1], path.relative(SRC, full));
      }
    }
  };
  walk(SRC);
  return keys;
}

describe('translations', () => {
  const used = usedKeys();
  for (const [lang, dict] of [['en', en], ['fr', fr]]) {
    it(`${lang}.json has every key the app uses`, () => {
      const have = flatten(dict);
      const missing = [...used].filter(([k]) => !have.has(k)).map(([k, file]) => `${k} (${file})`);
      expect(missing).toEqual([]);
    });
  }
});
