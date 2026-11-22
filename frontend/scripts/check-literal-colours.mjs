#!/usr/bin/env node
// Guard rail (design review, item 27): no NEW literal colour outside the
// token file. Colours come from the tokens of src/styles/design.css
// (var(--text-primary), var(--tone-red-soft), ...), see frontend/DESIGN.md.
//
//   node scripts/check-literal-colours.mjs            check against the baseline
//   node scripts/check-literal-colours.mjs --update   rewrite the baseline
//
// The baseline (literal-colours-baseline.json) holds, per file, how many
// literal colours it had when the rule was added. A file may go down, never
// up; a file that is not in the baseline must have none. After removing
// literals, run --update so the lower number becomes the new limit.
import { readdirSync, readFileSync, statSync, writeFileSync } from 'node:fs';
import { dirname, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
export const SRC = resolve(HERE, '../src');
export const BASELINE = join(HERE, 'literal-colours-baseline.json');
// The only file that may define colours.
const TOKEN_FILE = 'styles/design.css';

// #rgb, #rgba, #rrggbb, #rrggbbaa, and rgb()/rgba()/hsl()/hsla().
const COLOUR = /#(?:[0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9a-zA-Z_-])|\b(?:rgba?|hsla?)\(/g;

/** How many literal colours a source text holds (comments included: keep them out of comments too). */
export const countColours = (text) => (text.match(COLOUR) || []).length;

const walk = (dir) => readdirSync(dir).flatMap((name) => {
  const path = join(dir, name);
  if (statSync(path).isDirectory()) return ['__tests__', 'test', 'node_modules'].includes(name) ? [] : walk(path);
  return /\.(css|jsx?|tsx?)$/.test(name) && !/\.test\./.test(name) ? [path] : [];
});

/** { "components/Foo.css": 3, ... } for every file with at least one literal colour. */
export const scan = (root = SRC) => {
  const counts = {};
  for (const file of walk(root)) {
    const name = relative(root, file).split(sep).join('/');
    if (name === TOKEN_FILE) continue;
    const count = countColours(readFileSync(file, 'utf8'));
    if (count > 0) counts[name] = count;
  }
  return counts;
};

/** Files that have more literal colours than the baseline allows. */
export const compare = (counts, baseline) => {
  const over = Object.keys(counts).sort()
    .filter((name) => counts[name] > (baseline[name] || 0))
    .map((name) => ({ file: name, allowed: baseline[name] || 0, found: counts[name] }));
  const under = Object.keys(baseline).sort()
    .filter((name) => (counts[name] || 0) < baseline[name])
    .map((name) => ({ file: name, allowed: baseline[name], found: counts[name] || 0 }));
  return { over, under };
};

const main = () => {
  const counts = scan();
  const total = Object.values(counts).reduce((a, b) => a + b, 0);
  if (process.argv.includes('--update')) {
    const sorted = Object.fromEntries(Object.keys(counts).sort().map((name) => [name, counts[name]]));
    writeFileSync(BASELINE, `${JSON.stringify(sorted, null, 2)}\n`);
    console.log(`Baseline written: ${total} literal colours in ${Object.keys(counts).length} files.`);
    return 0;
  }
  const baseline = JSON.parse(readFileSync(BASELINE, 'utf8'));
  const { over, under } = compare(counts, baseline);
  if (under.length) {
    console.log(`${under.length} file(s) now hold fewer literal colours than the baseline. Run "npm run lint:colours -- --update" to lock that in.`);
  }
  if (over.length) {
    console.error('New literal colours. Use a token from src/styles/design.css instead (see DESIGN.md):');
    for (const { file, allowed, found } of over) console.error(`  src/${file}: ${found} literal colours, ${allowed} allowed`);
    return 1;
  }
  console.log(`Literal colours: ${total} in ${Object.keys(counts).length} files, none new.`);
  return 0;
};

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) process.exit(main());
