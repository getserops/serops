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
            <button type="button" class="collapsible-header">
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
 * Markdown tables (GitHub style) rendered as real tables.
 *
 * Runs on text that is ALREADY HTML-escaped and already carries the
 * trusted markup of the earlier passes (code blocks, inline code,
 * bold). It only adds table tags around existing cell text, so it
 * introduces no new path for model text to reach the DOM unescaped.
 *
 * A table is: a header row, a separator row (`|---|:--:|--:|`) with
 * the same number of cells, then zero or more body rows. Rendered
 * code blocks (`<pre>…</pre>`) are skipped, so a table quoted inside
 * a code fence stays as typed.
 */
const TABLE_SEPARATOR_CELL = /^:?-{1,}:?$/;

/** Split one row into cells; pipes inside inline code or `\|` do not split. */
const splitTableRow = (line) => {
    let row = line.trim();
    if (row.startsWith('|')) row = row.slice(1);
    if (row.endsWith('|') && !row.endsWith('\\|')) row = row.slice(0, -1);

    const cells = [];
    let current = '';
    let inCode = false;
    for (let i = 0; i < row.length; i += 1) {
        if (row.startsWith('<code', i)) inCode = true;
        if (row.startsWith('</code>', i)) inCode = false;
        const ch = row[i];
        if (ch === '\\' && row[i + 1] === '|') {
            current += '|';
            i += 1;
        } else if (ch === '|' && !inCode) {
            cells.push(current.trim());
            current = '';
        } else {
            current += ch;
        }
    }
    cells.push(current.trim());
    return cells;
};

const isTableRow = (line) => line.includes('|') && line.trim() !== '';

const parseSeparator = (line) => {
    if (!line || !line.includes('-') || !line.includes('|')) return null;
    const cells = splitTableRow(line);
    if (!cells.every((cell) => TABLE_SEPARATOR_CELL.test(cell))) return null;
    return cells.map((cell) => {
        const left = cell.startsWith(':');
        const right = cell.endsWith(':');
        if (left && right) return 'center';
        if (right) return 'right';
        if (left) return 'left';
        return '';
    });
};

const renderTable = (header, aligns, rows) => {
    const cell = (tag, content, index) => {
        const align = aligns[index] ? ` class="chat-table-align-${aligns[index]}"` : '';
        return `<${tag}${align}>${content}</${tag}>`;
    };
    const head = header.map((content, i) => cell('th', content, i)).join('');
    const body = rows
        .map((row) => {
            // Short rows are padded, extra cells dropped: same as GitHub.
            const cells = aligns.map((_a, i) => cell('td', row[i] ?? '', i));
            return `<tr>${cells.join('')}</tr>`;
        })
        .join('');
    return `<div class="chat-table-wrapper"><table class="chat-table"><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
};

const formatTablesInSegment = (segment) => {
    if (!segment.includes('|')) return segment;
    const lines = segment.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
        const aligns = isTableRow(lines[i]) ? parseSeparator(lines[i + 1]) : null;
        const header = aligns ? splitTableRow(lines[i]) : null;
        if (!aligns || header.length !== aligns.length) {
            out.push(lines[i]);
            i += 1;
            continue;
        }
        const rows = [];
        let j = i + 2;
        while (j < lines.length && isTableRow(lines[j])) {
            rows.push(splitTableRow(lines[j]));
            j += 1;
        }
        // A table is a block: the blank lines around it would only add gaps.
        while (out.length && out[out.length - 1].trim() === '') out.pop();
        while (j < lines.length && lines[j].trim() === '') j += 1;
        out.push(renderTable(header, aligns, rows));
        i = j;
    }
    return out.join('\n');
};

/**
 * Markdown headings (`#` to `####` at the start of a line) rendered as
 * headings. Same contract as the tables: the text is already escaped,
 * only tags are added around it, and rendered code blocks are skipped.
 * `#` needs a space after it, so `#123` or `#channel` stay text.
 *
 * Levels are shifted by two (`#` is level 3): the page already has its
 * own title and card headings above a chat answer.
 */
const HEADING_LINE = /^ {0,3}(#{1,4})[ \t]+(.*?)[ \t]*#*[ \t]*$/;

const formatHeadingsInSegment = (segment) => {
    if (!segment.includes('#')) return segment;
    const lines = segment.split('\n');
    const out = [];
    for (let i = 0; i < lines.length; i += 1) {
        const match = HEADING_LINE.exec(lines[i]);
        if (!match || !match[2]) {
            out.push(lines[i]);
            continue;
        }
        const level = match[1].length;
        // A heading is a block: the blank lines around it would only add gaps.
        while (out.length && out[out.length - 1].trim() === '') out.pop();
        while (i + 1 < lines.length && lines[i + 1].trim() === '') i += 1;
        out.push(`<div class="chat-heading chat-heading-${level}" role="heading" aria-level="${level + 2}">${match[2]}</div>`);
    }
    return out.join('\n');
};

/**
 * Markdown lists rendered as lists: lines that start with `- ` or `* `
 * (bullets) or `1. ` (numbered). Same contract as the tables and the
 * headings: the text is already escaped, only tags are added around it,
 * and rendered code blocks are skipped.
 *
 * - The marker needs a space and some text after it, so `-5`, a lone
 *   `-`, `---` or a hyphen inside a sentence stay text.
 * - Consecutive items form one list; a blank line between two items of
 *   the same kind does not split it. A numbered list starts at the
 *   number its first item carries.
 * - One level of nesting: an item indented by two spaces or more under
 *   an open item becomes a list inside that item.
 */
const LIST_ITEM = /^( {0,7})([-*]|\d{1,3}[.)])[ \t]+(\S.*?)[ \t]*$/;
const LIST_HINT = /^ {0,7}(?:[-*]|\d{1,3}[.)])[ \t]+\S/m;

const parseListItem = (line) => {
    const match = LIST_ITEM.exec(line);
    if (!match) return null;
    const ordered = /\d/.test(match[2]);
    return {
        indent: match[1].length,
        ordered,
        start: ordered ? parseInt(match[2], 10) : null,
        text: match[3],
    };
};

const openList = (item) => {
    const tag = item.ordered ? 'ol' : 'ul';
    const start = item.ordered && item.start !== 1 ? ` start="${item.start}"` : '';
    return { tag, html: `<${tag} class="chat-list"${start}>` };
};

const formatListsInSegment = (segment) => {
    if (!LIST_HINT.test(segment)) return segment;
    const lines = segment.split('\n');
    const out = [];
    let i = 0;
    while (i < lines.length) {
        const first = parseListItem(lines[i]);
        if (!first) {
            out.push(lines[i]);
            i += 1;
            continue;
        }
        const top = openList(first);
        let html = top.html;
        let nested = null;       // the open list inside the current item, if any
        let itemOpen = false;
        let j = i;
        while (j < lines.length) {
            let item = parseListItem(lines[j]);
            if (!item) {
                // A blank line between two items of the same list keeps the list.
                let k = j;
                while (k < lines.length && lines[k].trim() === '') k += 1;
                const next = k > j && k < lines.length ? parseListItem(lines[k]) : null;
                const sameTop = next && next.indent < 2 && (next.ordered ? 'ol' : 'ul') === top.tag;
                const sameNested = next && next.indent >= 2 && itemOpen;
                if (!sameTop && !sameNested) break;
                j = k;
                item = next;
            }
            if (item.indent >= 2 && itemOpen) {
                const tag = item.ordered ? 'ol' : 'ul';
                if (nested && nested !== tag) {
                    html += `</${nested}>`;
                    nested = null;
                }
                if (!nested) {
                    const inner = openList(item);
                    html += inner.html;
                    nested = inner.tag;
                }
                html += `<li>${item.text}</li>`;
            } else {
                // Another kind of list at the top level starts a new list.
                if ((item.ordered ? 'ol' : 'ul') !== top.tag) break;
                if (nested) {
                    html += `</${nested}>`;
                    nested = null;
                }
                if (itemOpen) html += '</li>';
                html += `<li>${item.text}`;
                itemOpen = true;
            }
            j += 1;
        }
        if (nested) html += `</${nested}>`;
        if (itemOpen) html += '</li>';
        html += `</${top.tag}>`;
        // A list is a block: the blank lines around it would only add gaps.
        while (out.length && out[out.length - 1].trim() === '') out.pop();
        while (j < lines.length && lines[j].trim() === '') j += 1;
        out.push(html);
        i = j;
    }
    return out.join('\n');
};

/** Tables, headings and lists, outside rendered code blocks. */
const formatBlocks = (text) => {
    if (!text.includes('|') && !text.includes('#') && !LIST_HINT.test(text)) return text;
    // Odd indexes are the rendered code blocks: left untouched.
    return text
        .split(/(<pre[\s\S]*?<\/pre>)/g)
        .map((part, index) => (index % 2 ? part : formatListsInSegment(formatTablesInSegment(formatHeadingsInSegment(part)))))
        .join('');
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

    // Markdown tables become real tables, `#` lines headings and `- ` or
    // `1. ` lines lists. After
    // inline code and bold so cells and headings keep that formatting;
    // before the newline pass so rows are still one line each.
    formattedText = formatBlocks(formattedText);

    // Convert newlines to HTML line breaks for proper display
    formattedText = formattedText.replace(/\n/g, "<br />");

    // Clean up multiple consecutive <br />
    formattedText = formattedText.replace(/(<br \/>){3,}/g, "<br /><br />");

    // No line break directly before or after a table, a heading or a list: they are blocks.
    formattedText = formattedText
        .replace(/(?:<br \/>)+(<[uo]l class="chat-list")/g, "$1")
        .replace(/(<\/[uo]l>)(?:<br \/>)+/g, "$1")
        .replace(/(?:<br \/>)+(<div class="chat-(?:table-wrapper|heading)[ "])/g, "$1")
        .replace(/(<\/table><\/div>)(?:<br \/>)+/g, "$1")
        .replace(/(<div class="chat-heading[^>]*>[^\n]*?<\/div>)(?:<br \/>)+/g, "$1");

    return formattedText;
};

export default renderFormattedText;

/**
 * Collapsible sections rendered by createCollapsible open and close on
 * click. One delegated listener instead of an inline onclick: the
 * Content-Security-Policy allows no inline script.
 */
export const installCollapsibleToggle = (root = document) => {
    const onClick = (event) => {
        const header = event.target.closest?.('.collapsible-header');
        const section = header?.parentElement;
        if (section?.classList.contains('collapsible-section')) section.classList.toggle('open');
    };
    root.addEventListener('click', onClick);
    return () => root.removeEventListener('click', onClick);
};
