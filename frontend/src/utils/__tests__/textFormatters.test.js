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
