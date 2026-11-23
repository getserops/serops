import { describe, it, expect } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

// 1.5.3: about 900 sentences written in the code moved to the translation
// files. This keeps new ones out: a message, an accessible name or a title
// written in English in a component stays English in the French interface.
// Example values in placeholders, product names and code are not checked.
const SRC = path.resolve(__dirname, '../..');
const files = [];
const walk = (dir) => {
  for (const name of fs.readdirSync(dir)) {
    const full = path.join(dir, name);
    if (fs.statSync(full).isDirectory()) {
      if (!['__tests__', 'locales', 'test'].includes(name)) walk(full);
    } else if (name.endsWith('.jsx')) files.push(full);
  }
};
walk(SRC);

// Names a person reads as they are, in any language.
const NAMES = /^(SerOps|Esc|Ctrl K)$/;

describe('no hard-coded English in components', () => {
  it('has no toast, alert or confirm with a written sentence', () => {
    const found = [];
    for (const file of files) {
      const lines = fs.readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        if (/\b(toast\.\w+|alert|window\.confirm|confirm)\(\s*["'`][^"'`]*[A-Za-z]{3}/.test(line)) found.push(`${path.relative(SRC, file)}:${i + 1}`);
      });
    }
    expect(found).toEqual([]);
  });

  it('has no aria-label or title written in English', () => {
    const found = [];
    for (const file of files) {
      const lines = fs.readFileSync(file, 'utf8').split('\n');
      lines.forEach((line, i) => {
        for (const m of line.matchAll(/\b(aria-label|title)="([^"{}]*)"/g)) {
          if (/[A-Za-z]{3}/.test(m[2]) && !NAMES.test(m[2])) found.push(`${path.relative(SRC, file)}:${i + 1} ${m[1]}="${m[2]}"`);
        }
      });
    }
    expect(found).toEqual([]);
  });
});
