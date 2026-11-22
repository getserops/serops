import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

// Review item 4: dates are formatted in utils/dates.js only, so they follow
// the user's time zone and language. A direct toLocale*String call on a date
// ignores both.
const SRC = resolve(__dirname, '../..');
const files = (dir) => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  if (statSync(path).isDirectory()) return name === '__tests__' || name === 'test' ? [] : files(path);
  return /\.(jsx?|tsx?)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
});
// Numbers may still use toLocaleString(): these are the lines that do.
const NUMBERS = /(token_count|tokensTotal|logs_analyzed|total_records|\.kept|\.total)\??\.toLocaleString\(\)/g;

describe('dates go through utils/dates.js', () => {
  it('no file formats a date with toLocaleString, toLocaleDateString or toLocaleTimeString', () => {
    const found = [];
    for (const file of files(SRC)) {
      const name = relative(SRC, file);
      if (name === join('utils', 'dates.js')) continue;
      readFileSync(file, 'utf8').split('\n').forEach((line, index) => {
        const rest = line.replace(NUMBERS, '');
        if (/\.toLocale(Date|Time)?String\(/.test(rest)) found.push(`${name}:${index + 1}`);
      });
    }
    expect(found).toEqual([]);
  });
});
