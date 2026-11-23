/**
 * Measurements for the phone and tablet checks, run inside the page.
 * Each function returns a list of findings; an empty list passes.
 */

export type Findings = { sideways: string[]; clipped: string[]; fields: string[]; targets: string[]; primary: string[] };

export const measure = (): Findings => {
  const label = (el: Element) => {
    const text = (el.getAttribute('aria-label') || (el as HTMLElement).innerText || (el as HTMLInputElement).placeholder || (el as HTMLInputElement).value || '').trim().replace(/\s+/g, ' ').slice(0, 28);
    const cls = typeof el.className === 'string' && el.className ? `.${el.className.trim().split(/\s+/).slice(0, 2).join('.')}` : '';
    return `${el.tagName.toLowerCase()}${cls}${text ? ` "${text}"` : ''}`;
  };
  const vw = window.innerWidth;
  const shown = (el: Element) => {
    const r = el.getBoundingClientRect();
    if (r.width < 1 || r.height < 1 || r.right <= 0 || r.left >= Math.max(vw, document.documentElement.scrollWidth)) return false;
    for (let n: Element | null = el; n; n = n.parentElement) {
      const s = getComputedStyle(n);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
      // Text kept for screen readers only.
      if (s.position === 'absolute' && (s.clip === 'rect(0px, 0px, 0px, 0px)' || s.clipPath === 'inset(50%)' || (parseFloat(s.width) <= 1 && parseFloat(s.height) <= 1))) return false;
    }
    return true;
  };

  // 1. The page does not scroll sideways.
  const sideways: string[] = [];
  const docWidth = document.documentElement.scrollWidth;
  if (docWidth > vw) sideways.push(`page is ${docWidth}px wide in a ${vw}px window`);

  // 2. No table, and nothing a person reads or presses inside a table or a
  // card, is cut by a parent with hidden overflow. A parent that scrolls is
  // not a cut; text shortened on purpose with an ellipsis is not either.
  const clipped: string[] = [];
  const CARD = '.ds-card, .card, .chart-card, .issues-page-card, .settings-section, .data-page-container, .metric-card';
  const cutBy = (el: Element): Element | null => {
    const r = el.getBoundingClientRect();
    for (let p = el.parentElement; p && p !== document.documentElement; p = p.parentElement) {
      const s = getComputedStyle(p);
      if (/auto|scroll/.test(s.overflowX)) return null;
      if (/hidden|clip/.test(s.overflowX)) {
        if (s.textOverflow === 'ellipsis' || s.webkitLineClamp !== 'none') return null;
        const b = p.getBoundingClientRect();
        if (r.right > b.right + 1 || r.left < b.left - 1) return p;
      }
    }
    return null;
  };
  const inside = Array.from(document.querySelectorAll(`table, table :is(th, td), :is(${CARD}) :is(a, button, input, select, textarea, .ds-chip, .badge)`));
  for (const el of inside.filter(shown)) {
    const by = cutBy(el);
    if (by) clipped.push(`${label(el)} is cut by ${label(by).split(' "')[0]}`);
  }

  // 3. A field with text under 16 px makes an iPhone zoom in on focus.
  const FIELD = 'input:not([type=checkbox]):not([type=radio]):not([type=hidden]):not([type=range]):not([type=file]):not([type=color]):not([type=button]):not([type=submit]), select, textarea';
  const fields = Array.from(document.querySelectorAll(FIELD)).filter(shown)
    .filter((el) => parseFloat(getComputedStyle(el).fontSize) < 16)
    .map((el) => `${label(el)}: ${parseFloat(getComputedStyle(el).fontSize)}px`);

  // 4. Everything a finger presses is at least 24 by 24 px; a primary
  // action is at least 44 px high. A link inside a sentence is exempt
  // (WCAG 2.5.8); a checkbox or radio counts with its label.
  const targets: string[] = [];
  const primary: string[] = [];
  const PRESS = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button], [role=tab], [role=menuitem], [role=switch], [tabindex="0"]:not(main):not(tr)';
  const inSentence = (el: Element) => {
    if (el.tagName !== 'A' || getComputedStyle(el).display !== 'inline') return false;
    const parent = el.parentElement;
    return !!parent && Array.from(parent.childNodes).some((n) => n.nodeType === 3 && (n.textContent || '').trim().length > 1);
  };
  for (const el of Array.from(document.querySelectorAll(PRESS)).filter(shown)) {
    if ((el as HTMLButtonElement).disabled || inSentence(el)) continue;
    let box = el.getBoundingClientRect();
    if (el instanceof HTMLInputElement && /checkbox|radio/.test(el.type)) {
      const wrap = el.closest('label') || (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`));
      if (wrap) { const w = wrap.getBoundingClientRect(); if (w.width * w.height > box.width * box.height) box = w; }
    }
    if (box.width < 23.5 || box.height < 23.5) targets.push(`${label(el)}: ${Math.round(box.width)}x${Math.round(box.height)}`);
    if (el.matches('.ds-btn-primary, .btn-primary') && box.height < 43.5) primary.push(`${label(el)}: ${Math.round(box.height)}px high`);
  }

  const uniq = (list: string[]) => Array.from(new Set(list));
  return { sideways, clipped: uniq(clipped), fields: uniq(fields), targets: uniq(targets), primary: uniq(primary) };
};
