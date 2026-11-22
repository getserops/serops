// Sentence splitting for display only (Overview card and rows). The stored
// text is never changed; these helpers decide where a long text may be cut
// so that a cut never lands in the middle of a sentence.
//
// A sentence ends at ".", "!" or "?" followed by white space. It does not end
//   - inside a number, time, version or file name ("19.5", "00:24:45.45",
//     "v0.10.7", "app.py"): no white space follows the dot there;
//   - inside quoted text, backticks or brackets ('OOM. Retry later', "a. b",
//     `kubectl logs. x`, (for example. this)): what is quoted stays whole;
//   - after an abbreviation ("e.g. ", "i.e. ", "vs. ", "approx. ");
//   - after a list number at the start ("1. Restore the limit");
//   - at an ellipsis that the sentence continues after ("wait... then").
// When in doubt it does not split: two sentences shown as one is harmless,
// a sentence cut in two is not.

const ABBREVIATIONS = new Set(['e.g', 'i.e', 'vs', 'approx', 'cf', 'etc', 'incl', 'excl', 'resp', 'ca']);
const CLOSER = { '"': '"', '`': '`', '“': '”', "'": "'", '(': ')', '[': ']', '{': '}' };
const QUOTES = new Set(['"', '`', '”', "'"]);
const TERMINATORS = '.!?';

// An opening single quote stands at the start or after white space, a bracket,
// a colon, an equals sign or a comma, with a character right after it. A
// closing one is not followed by a letter or digit. Anything else
// ("pricing's", "can't", "hosts'") is an apostrophe.
const opensSingle = (text, i) => (i === 0 || /[\s([{:=,]/.test(text[i - 1])) && /\S/.test(text[i + 1] || '');
const closesSingle = (text, i) => !/[\p{L}\p{N}]/u.test(text[i + 1] || '');

// The text with everything inside quotes and brackets replaced by "_", so
// that punctuation in there cannot end a sentence. An opener that never
// closes is taken as an ordinary character.
const maskQuoted = (text) => {
  const chars = text.split('');
  const ignored = new Set();
  for (;;) {
    const stack = [];            // [closer, index of the opener]
    const spans = [];
    for (let i = 0; i < text.length; i++) {
      const c = text[i];
      const top = stack[stack.length - 1];
      if (top && c === top[0] && (c !== "'" || closesSingle(text, i))) {
        stack.pop();
        if (!stack.length) spans.push([top[1], i]);
        continue;
      }
      if (top && QUOTES.has(top[0])) continue;                 // nothing nests inside a quote
      if (ignored.has(i) || !CLOSER[c]) continue;
      if (c === "'" && !opensSingle(text, i)) continue;
      stack.push([CLOSER[c], i]);
    }
    if (!stack.length) {
      for (const [a, b] of spans) for (let i = a + 1; i < b; i++) chars[i] = '_';
      return chars.join('');
    }
    ignored.add(stack[0][1]);
  }
};

export const splitSentences = (value) => {
  const text = typeof value === 'string' ? value.replace(/\s+/g, ' ').trim() : '';
  if (!text) return [];
  const masked = maskQuoted(text);
  const out = [];
  let start = 0;
  for (let i = 0; i < masked.length; i++) {
    if (!TERMINATORS.includes(masked[i])) continue;
    const first = i;
    let end = i;
    while (TERMINATORS.includes(masked[end + 1] || ' ')) end++;
    const after = masked[end + 1];
    i = end;
    if (after !== undefined && after !== ' ') continue;          // "19.5", "app.py", "v0.10.7"
    const body = masked.slice(start, first).trim();
    if (masked[end] === '.' && end === first) {
      const word = (/([\p{L}.]+)$/u.exec(body) || [''])[0].toLowerCase();
      if (ABBREVIATIONS.has(word)) continue;
      if (/^\(?\d{1,2}$/.test(body)) continue;                   // "1." opening a list item
    }
    if (end > first && masked[end] === '.' && /[\p{Ll}]/u.test(masked[end + 2] || '')) continue;   // "wait... then"
    out.push(text.slice(start, end + 1).trim());
    start = end + 1;
  }
  const tail = text.slice(start).trim();
  if (tail) out.push(tail);
  return out;
};

export const firstSentence = (value) => splitSentences(value)[0] || '';

// Headline of an issue: its first sentence, and when that is longer than
// `max` characters, cut at the last word boundary before the limit and ended
// with "…". The cut never lands inside a word; when it would land inside
// brackets, double quotes or backticks, it moves back to before they open, so
// quoted error text is shown whole or not at all. Punctuation left hanging at
// the cut is dropped.
export const HEADLINE_MAX = 120;
const TRAILING = /[\s,;:.\-–—('"`“[{]+$/u;
const PAIRS = { ')': '(', ']': '[', '}': '{', '”': '“' };
// Index of an opener that the text never closes, or -1.
const unclosedAt = (text) => {
  const stack = [];
  const toggles = { '"': -1, '`': -1 };
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (c in toggles) toggles[c] = toggles[c] === -1 ? i : -1;
    else if ('([{“'.includes(c)) stack.push([c, i]);
    else if (PAIRS[c] && stack.length && stack[stack.length - 1][0] === PAIRS[c]) stack.pop();
  }
  const open = [...stack.map(([, i]) => i), toggles['"'], toggles['`']].filter((i) => i >= 0);
  return open.length ? Math.min(...open) : -1;
};
export const headline = (value, max = HEADLINE_MAX) => {
  const sentence = firstSentence(value);
  if (sentence.length <= max) return sentence;
  const head = sentence.slice(0, max + 1);
  const at = head.lastIndexOf(' ');
  if (at <= 0) return sentence;                       // one unbroken word: leave it to the layout
  let cut = head.slice(0, at);
  const open = unclosedAt(cut);
  if (open > 0) cut = cut.slice(0, open);
  cut = cut.replace(TRAILING, '');
  return cut ? `${cut}…` : sentence;
};

// "What to do" as steps: the lines of a list the text already holds, or else
// its sentences. A leading list mark ("1.", "2)", "-", "•") is dropped; the
// list numbers the steps itself.
const MARK = /^\s*(?:\(?\d{1,2}[.)]|[-*•])\s+/;
export const splitSteps = (value) => {
  if (typeof value !== 'string' || !value.trim()) return [];
  const lines = value.split(/\n+/).map((l) => l.trim()).filter(Boolean);
  const listed = lines.length > 1 && lines.filter((l) => MARK.test(l)).length >= 2;
  const units = listed ? lines : splitSentences(value);
  return units.map((u) => u.replace(MARK, '').trim()).filter(Boolean);
};
