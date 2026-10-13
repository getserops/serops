/**
 * Enhanced Text Formatter for Chat Messages
 * 
 * Features:
 * - Syntax highlighting for code blocks (Python, JavaScript, etc.)
 * - Collapsible sections for long tracebacks
 * - Visual section headers with icons
 * - Markdown-style formatting
 */

import hljs from 'highlight.js/lib/core';
import python from 'highlight.js/lib/languages/python';
import javascript from 'highlight.js/lib/languages/javascript';
import bash from 'highlight.js/lib/languages/bash';
import json from 'highlight.js/lib/languages/json';
import yaml from 'highlight.js/lib/languages/yaml';

// Register languages
hljs.registerLanguage('python', python);
hljs.registerLanguage('javascript', javascript);
hljs.registerLanguage('bash', bash);
hljs.registerLanguage('json', json);
hljs.registerLanguage('yaml', yaml);

// Section icons for visual hierarchy
const SECTION_ICONS = {
    'Root Cause': '🔍',
    'Recommended Action': '⚡',
    'Solution': '💡',
    'Evidence': '📋',
    'Issue': '⚠️',
    'Summary': '📝',
    'Details': '📄',
    'Traceback': '🔴',
    'Error': '❌',
    'Warning': '⚠️',
    'Analysis': '🔬',
    'Confidence Level': '📊',
};

/**
 * Detect if content is a Python traceback
 */
const isTraceback = (text) => {
    return text.includes('Traceback (most recent call last)') ||
        text.includes('File "') ||
        /^\s+File ".*", line \d+/.test(text);
};

/**
 * Detect language from content
 */
const detectLanguage = (code, hint = '') => {
    if (hint && hljs.getLanguage(hint)) {
        return hint;
    }

    // Auto-detect based on content
    if (isTraceback(code) || /^\s*(def |class |import |from |if __name__)/.test(code)) {
        return 'python';
    }
    if (/^\s*(function|const|let|var|import|export)/.test(code)) {
        return 'javascript';
    }
    if (/^\s*(npm|yarn|docker|git|curl|wget)/.test(code)) {
        return 'bash';
    }
    if (/^\s*[[{]/.test(code.trim())) {
        return 'json';
    }

    return 'plaintext';
};

/**
 * Apply syntax highlighting to code
 */
const highlightCode = (code, language = '') => {
    try {
        const lang = detectLanguage(code, language);
        if (lang !== 'plaintext') {
            const highlighted = hljs.highlight(code, { language: lang });
            return highlighted.value;
        }
    } catch (e) {
        console.warn('Highlighting failed:', e);
    }
    return escapeHtml(code);
};

/**
 * Escape HTML entities
 */
const escapeHtml = (text) => {
    return text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
};

/**
 * Inverse of escapeHtml — used to recover the original text before
 * handing to a library (hljs) that will re-escape it itself.
 *
 * Only handles the entities that ``escapeHtml`` produces. Not a
 * general HTML entity decoder.
 */
const unescapeHtml = (text) => {
    return text
        .replace(/&#039;/g, "'")
        .replace(/&quot;/g, '"')
        .replace(/&gt;/g, '>')
        .replace(/&lt;/g, '<')
        .replace(/&amp;/g, '&');
};

/**
 * Create a collapsible section
 */
const createCollapsible = (title, content, isOpen = false, type = 'default') => {
    const id = `collapsible-${Math.random().toString(36).substr(2, 9)}`;
    const icon = type === 'traceback' ? '🔴' : '📋';
    const openClass = isOpen ? 'open' : '';

    return `
        <div class="collapsible-section ${type} ${openClass}" data-id="${id}">
            <button class="collapsible-header" onclick="this.parentElement.classList.toggle('open')">
                <span class="collapsible-icon">${icon}</span>
                <span class="collapsible-title">${title}</span>
                <span class="collapsible-arrow">▼</span>
            </button>
            <div class="collapsible-content">
                ${content}
            </div>
        </div>
    `;
};

/**
 * Format traceback with better styling
 */
const formatTraceback = (traceback) => {
    // Count lines to determine if we should collapse
    const lines = traceback.split('\n').length;
    const shouldCollapse = lines > 10;

    const highlighted = highlightCode(traceback, 'python');
    const codeBlock = `<pre class="code-block traceback"><code class="hljs language-python">${highlighted}</code></pre>`;

    if (shouldCollapse) {
        return createCollapsible(
            `Traceback (${lines} lines)`,
            codeBlock,
            false,
            'traceback'
        );
    }

    return codeBlock;
};

/**
 * Add section headers with icons
 */
const formatSectionHeaders = (text) => {
    let result = text;

    for (const [section, icon] of Object.entries(SECTION_ICONS)) {
        // Match **Section:** or **Section**
        const regex = new RegExp(`\\*\\*${section}:?\\*\\*`, 'gi');
        result = result.replace(regex, `<div class="section-header"><span class="section-icon">${icon}</span><strong>${section}:</strong></div>`);
    }

    return result;
};

/**
 * Enhanced text formatter with all improvements.
 *
 * XSS hardening (FE-P0-01, audit 2026-09-05):
 * The output is fed into ``dangerouslySetInnerHTML`` in ChatIssues.
 * Prior versions escaped inside per-pattern callbacks (backticks,
 * bold, code fences) but the *base* text — anything outside those
 * patterns — flowed straight through unchanged. Bot output like
 * ``Sorry, that failed: <img src=x onerror=alert(1)>`` (no backticks,
 * no **) executed.
 *
 * Fix strategy: escape the whole input once at the top. Every
 * subsequent transformation matches on delimiter characters
 * (backticks, asterisks, triple-backticks) that ``escapeHtml`` does
 * NOT affect, so the regex passes still work. Where a transformation
 * hands its capture to a library that re-escapes (hljs), we
 * un-escape the capture first so the library sees raw code.
 *
 * The inner escapeHtml() calls in each callback are now redundant
 * (input is already escaped) but harmless — kept for defence-in-depth
 * so a future refactor that changes the top-level escape doesn't
 * silently reintroduce the XSS.
 */
export const renderFormattedText = (text) => {
    if (!text) return "";

    // Escape the whole text FIRST. Every subsequent pattern operates
    // on escaped text and produces trusted HTML by design.
    let formattedText = escapeHtml(text);

    // Handle escaped newlines (literal \\n in string) — the raw
    // backslash-n pair survives escapeHtml unchanged.
    formattedText = formattedText.replace(/\\n/g, "\n");

    // Clean up JSON dict artifacts like {'description': ...}
    formattedText = formattedText.replace(
        /\{['"]description['"]:\s*['"]/g,
        ""
    );
    formattedText = formattedText.replace(
        /['"],\s*['"]confidence_level['"]:\s*['"]\w+['"]\}/g,
        ""
    );
    formattedText = formattedText.replace(
        /['"],\s*['"]evidence['"]:\s*\[.*?\]\}/g,
        ""
    );

    // Clean up standalone ** markers
    formattedText = formattedText.replace(/^\*\*$/gm, "");
    formattedText = formattedText.replace(/\*\*\s*\*\*/g, "");

    // Format code blocks with syntax highlighting.
    //
    // XSS hardening (2026-08-30):
    //  - ``lang`` comes from the model output; escape before inserting
    //    as text and as a class-name suffix.
    //  - ``highlightCode`` already returns HTML-safe output (its
    //    escapeHtml fallback runs when hljs fails), so ``highlighted``
    //    can be inserted as-is.
    //  - The previous "Copy" button referenced ``copyCodeToClipboard``
    //    which was never defined — a dead onclick and an XSS anchor
    //    combined. Removed until we wire a real React click handler.
    formattedText = formattedText.replace(
        /```(\w*)\n?([\s\S]*?)```/g,
        (match, lang, code) => {
            // ``code`` is HTML-escaped (base-text pass). hljs expects
            // raw source and will re-escape on output — un-escape here
            // so ``<script>`` in a code fence renders as ``<script>``
            // (highlighted, but visibly the same) rather than the
            // literal string ``&lt;script&gt;``.
            const trimmedCode = unescapeHtml(code.trim());

            if (isTraceback(trimmedCode)) {
                return formatTraceback(trimmedCode);
            }

            const highlighted = highlightCode(trimmedCode, lang);
            const safeLang = escapeHtml(lang || 'code');
            const langClass = lang ? `language-${escapeHtml(lang)}` : '';

            return `<div class="code-block-wrapper"><div class="code-block-header"><span class="code-lang-label">${safeLang}</span></div><pre class="code-block"><code class="hljs ${langClass}">${highlighted}</code></pre></div>`;
        }
    );

    // Check for inline tracebacks (not in code blocks). formatTraceback
    // routes through highlightCode which re-escapes for display, so
    // un-escape the captured text first.
    // `$` and not `\Z`: JavaScript has no `\Z` anchor — that is Python's, and
    // in a JS regex it matches a literal 'Z'. Two concrete consequences:
    // a traceback whose last line does not start with a capital and has
    // nothing after it (`    boom()` at end of text) satisfied no
    // alternative, so the match failed and it was not formatted at all; and
    // any traceback containing a 'Z' was truncated there. No `m` flag, so
    // `$` is end-of-string.
    const tracebackRegex = /(Traceback \(most recent call last\):[\s\S]*?(?=\n\n|\n[A-Z]|$))/g;
    formattedText = formattedText.replace(tracebackRegex, (match) => {
        return formatTraceback(unescapeHtml(match.trim()));
    });

    // Format inline code. ``content`` is already HTML-safe (base-text
    // pass escaped it) so we insert directly — double-escaping would
    // turn ``&`` in user text into ``&amp;amp;`` on screen.
    formattedText = formattedText.replace(
        /`([^`]+)`/g,
        (_match, content) => `<code class="inline-code">${content}</code>`
    );

    // Add section headers with icons (before bold formatting).
    // formatSectionHeaders iterates SECTION_ICONS keys (trusted
    // constants) so no user content flows through it.
    formattedText = formatSectionHeaders(formattedText);

    // Format markdown-style bold text (remaining). Same "already-escaped"
    // logic as inline code above.
    formattedText = formattedText.replace(
        /\*\*(.*?)\*\*/g,
        (_match, content) => `<strong>${content}</strong>`
    );

    // Convert newlines to HTML line breaks for proper display
    formattedText = formattedText.replace(/\n/g, "<br />");

    // Clean up multiple consecutive <br />
    formattedText = formattedText.replace(/(<br \/>){3,}/g, "<br /><br />");

    return formattedText;
};

export default renderFormattedText;
