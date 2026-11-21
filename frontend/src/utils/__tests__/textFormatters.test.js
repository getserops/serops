/**
 * XSS regression tests for renderFormattedText.
 *
 * The function's output is fed to ``dangerouslySetInnerHTML`` in
 * ChatIssues, so any raw HTML that survives the transformations
 * executes in the user's browser. FE-P0-01 (audit 2026-09-05) found
 * that the base-text path wasn't escaped — only pattern-matched
 * captures were. These tests lock in the fix.
 */

import { describe, it, expect, vi } from 'vitest';

// hljs is loaded lazily by textFormatters. Mock it to a passthrough
// so we test the escape logic without pulling in the highlighter's
// own escaping (which would mask bugs in our layer).
vi.mock('highlight.js', () => ({
    default: {
        highlight: (code) => ({ value: code }),
        getLanguage: () => true,
        listLanguages: () => ['javascript', 'python', 'bash'],
    },
}));

import { renderFormattedText } from '../textFormatters';

describe('renderFormattedText — XSS regression (FE-P0-01)', () => {

    it('escapes raw <script> in plain text', () => {
        const out = renderFormattedText('hello <script>alert(1)</script> world');
        // The literal <script> tag MUST NOT be present — that would
        // execute when written to innerHTML.
        expect(out).not.toContain('<script>');
        // The user's text should still be visible, just escaped.
        expect(out).toContain('&lt;script&gt;');
    });

    it('escapes <img onerror> in plain text', () => {
        const out = renderFormattedText('caption: <img src=x onerror=alert(1)>');
        // The literal ``<img`` tag start MUST NOT be present — that's
        // what would let the browser parse an attribute. The text
        // ``onerror=`` may survive as literal characters (harmless
        // inside escaped angle brackets), which is expected.
        expect(out).not.toContain('<img');
        expect(out).toContain('&lt;img');
    });

    it('escapes <script> inside inline code', () => {
        const out = renderFormattedText('run `<script>alert(1)</script>` careful');
        // The <code> wrapper is ours (safe). The script tag must be
        // rendered as escaped entities inside the code block.
        expect(out).toContain('<code');
        expect(out).not.toContain('<script>');
        expect(out).toContain('&lt;script&gt;');
    });

    it('escapes <script> inside bold', () => {
        const out = renderFormattedText('**<script>alert(1)</script>**');
        expect(out).toContain('<strong>');
        expect(out).not.toContain('<script>');
        expect(out).toContain('&lt;script&gt;');
    });

    it('preserves ampersands as escaped entities, not double-escaped', () => {
        // Regression guard for double-escaping bug introduced during
        // the fix: text like "A & B" must render as "A &amp; B",
        // not "A &amp;amp; B".
        const out = renderFormattedText('A & B');
        expect(out).toContain('A &amp; B');
        expect(out).not.toContain('&amp;amp;');
    });

    it('preserves ampersands inside inline code without double-escaping', () => {
        const out = renderFormattedText('use `foo & bar`');
        expect(out).toContain('&amp; bar');
        expect(out).not.toContain('&amp;amp;');
    });

    it('does not execute javascript: URLs (defence in depth)', () => {
        // Not strictly a renderFormattedText concern — the function
        // doesn't produce anchor tags — but if someone adds a link
        // pattern later this test will catch obvious pitfalls.
        const out = renderFormattedText('click javascript:alert(1)');
        // Whatever escaping we choose, the raw string should not be
        // a live handler.
        expect(out).not.toContain('href="javascript:');
    });
});

describe('renderFormattedText — output preserves benign formatting', () => {

    it('renders bold', () => {
        const out = renderFormattedText('Hello **world**!');
        expect(out).toContain('<strong>world</strong>');
    });

    it('renders inline code', () => {
        const out = renderFormattedText('call `foo()` please');
        expect(out).toContain('<code');
        expect(out).toContain('foo()');
    });

    it('converts newlines to <br />', () => {
        const out = renderFormattedText('line1\nline2');
        expect(out).toContain('<br />');
    });

    it('returns empty string on empty input', () => {
        expect(renderFormattedText('')).toBe('');
        expect(renderFormattedText(null)).toBe('');
        expect(renderFormattedText(undefined)).toBe('');
    });
});

describe('renderFormattedText — traceback terminator (\\Z is not a JS anchor)', () => {

    // The terminating lookahead was `(?=\n\n|\n[A-Z]|\Z)`. `\Z` is Python's
    // end-of-string anchor; JavaScript has no such escape and reads it as a
    // literal 'Z'. Two things broke as a result.

    it('formats a traceback whose last line is indented and ends the text', () => {
        // No blank line, no following capital, no 'Z' anywhere: the lazy
        // quantifier could not satisfy any alternative, the match failed
        // outright, and the traceback was rendered as plain prose.
        const out = renderFormattedText(
            'Worker died.\n\nTraceback (most recent call last):\n  File "/app/w.py", line 42, in run\n    cache.set(key, payload)'
        );
        expect(out).toContain('code-block traceback');
        // The highlighter wraps tokens in spans, so assert on a bare one.
        expect(out).toContain('payload');
    });

    it('does not truncate a traceback at a literal Z', () => {
        const out = renderFormattedText(
            'Traceback (most recent call last):\n  File "/app/zone.py", line 7\n    Zap(payload)'
        );
        expect(out).toContain('code-block traceback');
        expect(out).toContain('Zap');
    });

    it('still stops at a blank line when more text follows', () => {
        const out = renderFormattedText(
            'Traceback (most recent call last):\n  File "/app/w.py", line 42\n    boom()\n\nRestarting worker.'
        );
        expect(out).toContain('code-block traceback');
        // The trailing prose must stay outside the code block.
        expect(out).toMatch(/<\/pre>[\s\S]*Restarting worker/);
    });
});

describe('renderFormattedText — markdown tables', () => {
    const TABLE = [
        'Before the table.',
        '',
        '| Check | Command or signal | Good result |',
        '|---|---|---|',
        '| Config applied | `redis-cli CONFIG GET maxmemory` | The **new** value |',
        '| Writes accepted | `redis-cli SET probe:test 1 EX 60` | `OK` |',
        '',
        'After the table.',
    ].join('\n');

    const parse = (text) => {
        const host = document.createElement('div');
        host.innerHTML = renderFormattedText(text);
        return host;
    };

    it('renders a header, a body and one cell per column', () => {
        const host = parse(TABLE);
        const table = host.querySelector('.chat-table-wrapper > table.chat-table');
        expect(table).not.toBeNull();
        const head = [...table.querySelectorAll('thead th')].map((th) => th.textContent);
        expect(head).toEqual(['Check', 'Command or signal', 'Good result']);
        const rows = table.querySelectorAll('tbody tr');
        expect(rows).toHaveLength(2);
        expect(rows[0].querySelectorAll('td')).toHaveLength(3);
        expect(rows[1].querySelector('td').textContent).toBe('Writes accepted');
    });

    it('keeps inline code and bold inside cells', () => {
        const host = parse(TABLE);
        expect(host.querySelector('td code.inline-code').textContent).toBe('redis-cli CONFIG GET maxmemory');
        expect(host.querySelector('td strong').textContent).toBe('new');
    });

    it('leaves no pipe row, no separator row and no line break around the table', () => {
        const html = renderFormattedText(TABLE);
        expect(html).not.toContain('|---');
        expect(html).not.toContain('| Check');
        expect(html).toContain('Before the table.<div class="chat-table-wrapper">');
        expect(html).toContain('</table></div>After the table.');
    });

    it('reads the alignment colons', () => {
        const host = parse('| a | b | c |\n|:--|:-:|--:|\n| 1 | 2 | 3 |');
        const cells = [...host.querySelectorAll('tbody td')].map((td) => td.className);
        expect(cells).toEqual(['chat-table-align-left', 'chat-table-align-center', 'chat-table-align-right']);
    });

    it('accepts rows without outer pipes and ends the table at the first line without a pipe', () => {
        const host = parse('a | b\n--- | ---\n1 | 2\nplain line');
        expect([...host.querySelectorAll('thead th')].map((th) => th.textContent)).toEqual(['a', 'b']);
        expect(host.querySelectorAll('tbody tr')).toHaveLength(1);
        expect(host.querySelector('table').textContent).toBe('ab12');
        expect(host.textContent).toContain('plain line');
    });

    it('pads a short row and drops extra cells', () => {
        const host = parse('| a | b |\n|---|---|\n| 1 |\n| 1 | 2 | 3 |');
        const rows = host.querySelectorAll('tbody tr');
        expect(rows).toHaveLength(2);
        expect([...rows[0].querySelectorAll('td')].map((td) => td.textContent)).toEqual(['1', '']);
        expect([...rows[1].querySelectorAll('td')].map((td) => td.textContent)).toEqual(['1', '2']);
    });

    it('does not split a cell on a pipe inside inline code or on an escaped pipe', () => {
        const host = parse('| cmd | note |\n|---|---|\n| `ps aux | grep redis` | a \\| b |');
        const cells = [...host.querySelectorAll('tbody td')].map((td) => td.textContent);
        expect(cells).toEqual(['ps aux | grep redis', 'a | b']);
    });

    it('escapes HTML in cells', () => {
        const html = renderFormattedText('| a | b |\n|---|---|\n| <img src=x onerror=alert(1)> | <script>alert(1)</script> |');
        expect(html).not.toContain('<img');
        expect(html).not.toContain('<script');
        const host = parse('| a | b |\n|---|---|\n| <img src=x onerror=alert(1)> | ok |');
        expect(host.querySelector('img')).toBeNull();
        expect(host.querySelector('tbody td').textContent).toBe('<img src=x onerror=alert(1)>');
    });

    it('leaves a table inside a code fence as typed', () => {
        const html = renderFormattedText('```\n| a | b |\n|---|---|\n| 1 | 2 |\n```');
        expect(html).not.toContain('<table');
        expect(html).toContain('|---|---|');
    });

    it('leaves text with pipes but no separator row alone', () => {
        const html = renderFormattedText('exit code 1 | retry 3\nnext line | more');
        expect(html).not.toContain('<table');
        expect(html).toContain('exit code 1 | retry 3');
    });

    it('does not treat a row whose separator has a different cell count as a table', () => {
        const html = renderFormattedText('| a | b | c |\n|---|---|\n| 1 | 2 | 3 |');
        expect(html).not.toContain('<table');
    });
});

describe('renderFormattedText — markdown headings', () => {
    it('renders # to #### as headings, two levels down', () => {
        const html = renderFormattedText('# One\n## Two\n### Three\n#### Four');
        expect(html).toContain('<div class="chat-heading chat-heading-1" role="heading" aria-level="3">One</div>');
        expect(html).toContain('<div class="chat-heading chat-heading-2" role="heading" aria-level="4">Two</div>');
        expect(html).toContain('<div class="chat-heading chat-heading-3" role="heading" aria-level="5">Three</div>');
        expect(html).toContain('<div class="chat-heading chat-heading-4" role="heading" aria-level="6">Four</div>');
        expect(html).not.toContain('#');
    });

    it('leaves no line break around a heading', () => {
        const html = renderFormattedText('Before.\n\n## What to do now\n\nAfter.');
        expect(html).toBe('Before.<div class="chat-heading chat-heading-2" role="heading" aria-level="4">What to do now</div>After.');
    });

    it('keeps bold and inline code in a heading and drops closing hashes', () => {
        const html = renderFormattedText('### 1. `fleet-redis` (**first**) ##');
        expect(html).toContain('aria-level="5">1. <code class="inline-code">fleet-redis</code> (<strong>first</strong>)</div>');
    });

    it('needs a space after the hashes and at most four of them', () => {
        expect(renderFormattedText('#123 is the ticket')).toBe('#123 is the ticket');
        expect(renderFormattedText('##### Five')).toBe('##### Five');
        expect(renderFormattedText('a # in the middle')).toBe('a # in the middle');
    });

    it('escapes HTML in a heading', () => {
        const html = renderFormattedText('## <img src=x onerror=alert(1)>');
        expect(html).not.toContain('<img');
        expect(html).toContain('&lt;img src=x onerror=alert(1)&gt;</div>');
    });

    it('leaves a # line inside a code fence as typed', () => {
        const html = renderFormattedText('```bash\n# restart it\nkubectl rollout restart deploy/x\n```');
        expect(html).not.toContain('chat-heading');
    });

    it('renders a heading directly above a table with no gap', () => {
        const html = renderFormattedText('## Checks\n\n| A | B |\n|---|---|\n| 1 | 2 |');
        expect(html).toContain('Checks</div><div class="chat-table-wrapper">');
    });
});

describe('renderFormattedText: markdown lists', () => {
    it('renders consecutive "- " lines as one list', () => {
        const html = renderFormattedText('What changed:\n- first\n- second\n- third\nAfter.');
        expect(html).toContain('What changed:<ul class="chat-list"><li>first</li><li>second</li><li>third</li></ul>After.');
        expect(html).not.toMatch(/(^|<br \/>)- /);
    });

    it('renders "* " lines as a list too', () => {
        expect(renderFormattedText('* one\n* two')).toBe('<ul class="chat-list"><li>one</li><li>two</li></ul>');
    });

    it('renders numbered lines as an ordered list', () => {
        expect(renderFormattedText('1. Fix it\n2. Check it')).toBe('<ol class="chat-list"><li>Fix it</li><li>Check it</li></ol>');
    });

    it('starts an ordered list at the number of its first item', () => {
        expect(renderFormattedText('3. third\n4. fourth')).toContain('<ol class="chat-list" start="3"><li>third</li>');
    });

    it('keeps one list when blank lines separate its items', () => {
        const html = renderFormattedText('1. one\n\n2. two\n\n3. three');
        expect(html).toBe('<ol class="chat-list"><li>one</li><li>two</li><li>three</li></ol>');
    });

    it('starts a new list when the kind changes', () => {
        const html = renderFormattedText('- a\n- b\n1. c\n2. d');
        expect(html).toBe('<ul class="chat-list"><li>a</li><li>b</li></ul><ol class="chat-list"><li>c</li><li>d</li></ol>');
    });

    it('nests an indented item inside the item above it', () => {
        const html = renderFormattedText('- parent\n  - child one\n  - child two\n- next');
        expect(html).toBe('<ul class="chat-list"><li>parent<ul class="chat-list"><li>child one</li><li>child two</li></ul></li><li>next</li></ul>');
    });

    it('keeps inline code and bold inside an item', () => {
        const html = renderFormattedText('- `--maxmemory` went from **128mb** to `1mb`.');
        expect(html).toBe('<ul class="chat-list"><li><code class="inline-code">--maxmemory</code> went from <strong>128mb</strong> to <code class="inline-code">1mb</code>.</li></ul>');
    });

    it('puts a list directly under a heading or a bold line with no gap', () => {
        expect(renderFormattedText('## Evidence\n\n- one\n- two')).toContain('Evidence</div><ul class="chat-list">');
        expect(renderFormattedText('**Timeline**\n- one')).toBe('<strong>Timeline</strong><ul class="chat-list"><li>one</li></ul>');
    });

    it('leaves a numbered heading to the heading pass', () => {
        const html = renderFormattedText('### 1. checkoutservice (root cause)\n- OOMKilled');
        expect(html).toContain('role="heading"');
        expect(html).toContain('>1. checkoutservice (root cause)</div><ul class="chat-list"><li>OOMKilled</li></ul>');
        expect(html).not.toContain('<ol');
    });

    it('leaves a bold numbered line as text', () => {
        const html = renderFormattedText('**1. Stop the errors**\nRun this.');
        expect(html).not.toContain('chat-list');
        expect(html).toContain('<strong>1. Stop the errors</strong>');
    });

    it('leaves hyphens that are not list markers alone', () => {
        for (const text of ['a - b - c', '-5 degrees', '-', '---', 'well-known', 'see 12.5 percent', '2026. A year.']) {
            expect(renderFormattedText(text)).not.toContain('chat-list');
        }
    });

    it('leaves list-looking lines inside a code fence as typed', () => {
        const html = renderFormattedText('```yaml\nargs:\n- --maxmemory\n- 1mb\n```');
        expect(html).not.toContain('chat-list');
        expect(html).not.toContain('<li>');
        expect(html).toContain('--maxmemory');
    });

    it('still escapes HTML inside an item', () => {
        const html = renderFormattedText('- <img src=x onerror=alert(1)>\n1. <script>alert(1)</script>');
        expect(html).not.toContain('<img');
        expect(html).not.toContain('<script');
        expect(html).toContain('<li>&lt;img src=x onerror=alert(1)&gt;</li>');
    });

    it('keeps text after a list on its own line', () => {
        const html = renderFormattedText('- one\n- two\n\nThen the rest.');
        expect(html).toBe('<ul class="chat-list"><li>one</li><li>two</li></ul>Then the rest.');
    });

    it('renders a table after a list', () => {
        const html = renderFormattedText('- one\n\n| A | B |\n|---|---|\n| 1 | 2 |');
        expect(html).toContain('</ul><div class="chat-table-wrapper">');
    });
});
