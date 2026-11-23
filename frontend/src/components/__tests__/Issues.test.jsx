import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import {
  formatAge,
  abbreviateComponent,
  getCountHeatLevel,
  getSeverityColor,
  getSeverityRowClass,
} from '../Issues';

// PR-UI2 · every describe block below inherits console-error/warn
// hygiene: any console.error/warn during a test fails it with the
// captured message. Kept centralised at file-scope so we don't
// forget to arm it in each block.
import { armConsoleHygiene } from '../../test/console-hygiene';

// ---- Pure utility tests ----

describe('formatAge', () => {
  armConsoleHygiene();

  it('returns dash for null/undefined', () => {
    expect(formatAge(null)).toBe('\u2014');
    expect(formatAge(undefined)).toBe('\u2014');
    expect(formatAge('')).toBe('\u2014');
  });

  it('returns relative time for valid date', () => {
    const tenMinutesAgo = new Date(Date.now() - 10 * 60 * 1000).toISOString();
    const result = formatAge(tenMinutesAgo);
    expect(result).toContain('ago');
  });

  it('handles invalid date gracefully', () => {
    expect(formatAge('not-a-date')).toBe('\u2014');
  });
});

describe('abbreviateComponent', () => {
  it('returns Infra for empty/null', () => {
    expect(abbreviateComponent(null)).toBe('Infra');
    expect(abbreviateComponent('')).toBe('Infra');
    expect(abbreviateComponent(undefined)).toBe('Infra');
  });

  it('abbreviates INFRASTRUCTURE to Infra', () => {
    expect(abbreviateComponent('INFRASTRUCTURE')).toBe('Infra');
    expect(abbreviateComponent('infrastructure')).toBe('Infra');
  });

  it('abbreviates DATABASE to DB', () => {
    expect(abbreviateComponent('DATABASE')).toBe('DB');
  });

  it('abbreviates AUTHENTICATION to Auth', () => {
    expect(abbreviateComponent('AUTHENTICATION')).toBe('Auth');
  });

  it('keeps service names exactly as named (CSS truncates long ones)', () => {
    expect(abbreviateComponent('backend-api')).toBe('backend-api');
    expect(abbreviateComponent('very-long-component-name')).toBe('very-long-component-name');
  });

  it('title-cases upper-case scope words it does not abbreviate', () => {
    expect(abbreviateComponent('NETWORK')).toBe('Network');
  });
});

describe('getCountHeatLevel', () => {
  it('returns normal for counts <= 5', () => {
    expect(getCountHeatLevel(0)).toBe('normal');
    expect(getCountHeatLevel(1)).toBe('normal');
    expect(getCountHeatLevel(5)).toBe('normal');
  });

  it('returns amber for counts 6-20', () => {
    expect(getCountHeatLevel(6)).toBe('amber');
    expect(getCountHeatLevel(10)).toBe('amber');
    expect(getCountHeatLevel(20)).toBe('amber');
  });

  it('returns red for counts > 20', () => {
    expect(getCountHeatLevel(21)).toBe('red');
    expect(getCountHeatLevel(100)).toBe('red');
  });
});

describe('getSeverityColor', () => {
  it('returns the red tone for critical', () => {
    expect(getSeverityColor('critical')).toBe('var(--tone-red-text)');
    expect(getSeverityColor('CRITICAL')).toBe('var(--tone-red-text)');
  });

  it('returns the amber tone for warning', () => {
    expect(getSeverityColor('warning')).toBe('var(--tone-amber-text)');
    expect(getSeverityColor('WARNING')).toBe('var(--tone-amber-text)');
  });

  it('returns a neutral border for unknown/null', () => {
    expect(getSeverityColor(null)).toBe('var(--border-hover)');
    expect(getSeverityColor('UNKNOWN')).toBe('var(--border-hover)');
  });
});

describe('getSeverityRowClass', () => {
  it('returns correct class for each severity', () => {
    expect(getSeverityRowClass('CRITICAL')).toBe('issue-row-critical');
    expect(getSeverityRowClass('WARNING')).toBe('issue-row-warning');
    expect(getSeverityRowClass('INFO')).toBe('issue-row-info');
  });

  it('returns empty string for unknown severity', () => {
    expect(getSeverityRowClass('OTHER')).toBe('');
    expect(getSeverityRowClass(null)).toBe('');
  });
});

// ---- Component render tests ----

// Mock dependencies for full component tests
// The page of one analysis sets a batchId here.
let routeParams = {};
vi.mock('react-router-dom', () => ({
  // eslint-disable-next-line react/prop-types
  Link: ({ to, children, ...rest }) => <a href={to} {...rest}>{children}</a>,
  useNavigate: () => vi.fn(),
  useParams: () => routeParams,
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));

// The strings of the list itself (issues.list.*) and the severity names
// come from the real translation files, in the language of `mockLang`;
// the other keys show as themselves.
let mockLang = 'en';
const mockLocales = {
  en: JSON.parse(readFileSync(resolve(__dirname, '../../locales/en.json'), 'utf8')),
  fr: JSON.parse(readFileSync(resolve(__dirname, '../../locales/fr.json'), 'utf8')),
};
const mockFromFile = (key, opts = {}) => {
  const node = key.split('.').slice(0, -1).reduce((o, k) => o?.[k], mockLocales[mockLang]);
  const leaf = key.split('.').pop();
  const text = node?.[opts.count === 1 ? `${leaf}_one` : `${leaf}_other`] ?? node?.[leaf];
  return typeof text === 'string' ? text.replace(/\{\{(\w+)\}\}/g, (_, name) => opts[name]) : key;
};

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key, opts) => {
      if (key.startsWith('issues.list.') || /^issues\.(critical|warning|info)$/.test(key)
        || (mockLang === 'fr' && key.startsWith('issues.statusLabel.'))) return mockFromFile(key, opts);
      const translations = {
        'common.loading': 'Loading...',
        'common.actions': 'Actions',
        'issues.systemIssues': 'System Issues',
        'issues.trackAnomalies': 'Track and resolve anomalies',
        'issues.noIssues': 'No issues found',
        'common.all': 'All',
        'issues.critical': 'Critical',
        'issues.warning': 'Warning',
        'issues.viewAll': 'View All',
      };
      return translations[key] || key;
    },
  }),
}));

vi.mock('../../services/investigation.service', () => ({
  default: { options: vi.fn(() => Promise.resolve({ projects: [] })) },
}));

vi.mock('../../services/notification.service', () => ({
  default: { acknowledgeIssue: vi.fn(() => Promise.resolve({})) },
}));

vi.mock('react-toastify', () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

vi.mock('../../services/data.service', () => ({
  default: {
    getIssues: vi.fn(),
    getIssuesByBatch: vi.fn(),
    resolveIssue: vi.fn(),
    muteIssue: vi.fn(),
    reopenIssue: vi.fn(),
    bulkAction: vi.fn(),
  },
}));

vi.mock('@tanstack/react-query', () => ({
  useQuery: () => ({
    data: {
      results: [
        {
          id: 1,
          severity: 'CRITICAL',
          description: 'Test critical issue description',
          issue_type: 'MEMORY_HIGH',
          component: 'payment-service',
          status: 'OPEN',
          root_cause: 'Connection pool exhausted after the 2.3.4 deploy.',
          recommendation: 'Raise the pool size.',
          reasoning: '1. Saw pool timeouts\n2. Traced them to the 2.3.4 deploy',
          affected_services: ['cart-api', 'web'],
          batch_id_str: 'shop-batch-1',
          project: 7,
          environment: 'production',
          occurrence_count: 15,
          created_at: new Date(Date.now() - 3600000).toISOString(),
          linked_commits: [],
          has_commit_correlation: false,
          has_metric_correlation: false,
          correlation_summary: [],
        },
        {
          id: 2,
          severity: 'WARNING',
          description: 'Test warning issue description that is quite long and should be clamped',
          issue_type: 'CONNECTION_TIMEOUT',
          component: 'INFRASTRUCTURE',
          status: 'MUTED',
          occurrence_count: 3,
          created_at: new Date(Date.now() - 86400000).toISOString(),
          linked_commits: [],
          has_commit_correlation: false,
          has_metric_correlation: false,
          correlation_summary: [],
        },
      ],
      pagination: { page: 1, total_pages: 1, total_issues: 2, next_page: null, previous_page: null },
      summary: {
        severity_distribution: { CRITICAL: 1, WARNING: 1 },
        status_distribution: { OPEN: 1, MUTED: 1, RESOLVED: 0 },
      },
    },
    isLoading: false,
    error: null,
    isPlaceholderData: false,
  }),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

// Must import after mocks are set up
const { default: Issues } = await import('../Issues');

describe('Issues component', () => {
  it('renders the table with headers', () => {
    render(<Issues />);
    expect(screen.getByText('System Issues')).toBeTruthy();
    expect(screen.getByText('Description')).toBeTruthy();
    expect(screen.getByText('Last seen')).toBeTruthy();
    expect(screen.getByText('Occurrences')).toBeTruthy();
    expect(screen.getByText('Actions')).toBeTruthy();
  });

  it('renders issue rows with the headline only: the root cause is in the drawer, not the row', () => {
    render(<Issues />);
    expect(screen.getByText('Test critical issue description')).toBeTruthy();
    expect(screen.queryByText('Connection pool exhausted after the 2.3.4 deploy.')).toBeNull();
    // Two lines for the headline, so the row keeps its height.
    const css = readFileSync(resolve(__dirname, '../Issues.css'), 'utf8');
    const rule = css.match(/\n\.issue-description-clamp \{[^}]*\}/)[0];
    expect(rule).toMatch(/-webkit-line-clamp: 2;/);
    // The ID column is off by default (it is in the panel instead).
    expect(screen.queryByText('#1')).toBeNull();
  });

  it('shows service names as named', () => {
    render(<Issues />);
    expect(screen.getByText('payment-service')).toBeTruthy();
    expect(screen.getByText('Infra')).toBeTruthy();
  });

  it('shows status as a label, not a bare dot', () => {
    render(<Issues />);
    // In the row, not the choice of the same name in the status filter.
    expect(screen.getByText('issues.statusLabel.open', { selector: 'td span' })).toBeTruthy();
    expect(screen.getByText('issues.statusLabel.muted', { selector: 'td span' })).toBeTruthy();
  });

  it('opens the issue panel when a row is clicked', () => {
    render(<Issues />);
    fireEvent.click(screen.getByText('Test critical issue description'));
    const panel = screen.getByRole('dialog');
    expect(panel.textContent).toContain('Raise the pool size.');
    expect(screen.getByRole('link', { name: /issues.panel.openAnalysis/ }).getAttribute('href')).toBe('/dash/data/details/shop-batch-1');
    expect(screen.getByRole('button', { name: /issues.panel.resolve/ })).toBeTruthy();
  });

  it('lists the AI reasoning one step per line', () => {
    render(<Issues />);
    fireEvent.click(screen.getByText('Test critical issue description'));
    const steps = [...screen.getByRole('dialog').querySelectorAll('ol li')].map((li) => li.textContent);
    expect(steps).toEqual(['Saw pool timeouts', 'Traced them to the 2.3.4 deploy']);
  });

  it('shows the other services a cause affects', () => {
    render(<Issues />);
    expect(screen.getByText('+2').getAttribute('title')).toBe('issues.panel.alsoAffects');
    fireEvent.click(screen.getByText('Test critical issue description'));
    expect(screen.getByRole('dialog').textContent).toContain('issues.panel.alsoAffects');
  });

  it('count tiles toggle a filter', () => {
    render(<Issues />);
    const tile = screen.getByRole('button', { name: /issues.tiles.critical/ });
    expect(tile.getAttribute('aria-pressed')).toBe('false');
    fireEvent.click(tile);
    expect(screen.getByRole('button', { name: /issues.tiles.critical/ }).getAttribute('aria-pressed')).toBe('true');
  });

  it('an open critical issue shows its severity in red: chip and left accent', () => {
    render(<Issues />);
    const row = screen.getByText('Test critical issue description').closest('tr');
    const chip = [...row.querySelectorAll('.ds-chip')].find((el) => el.textContent.trim() === 'CRITICAL');
    expect(chip.className).toContain('ds-chip-err');
    expect(row.style.getPropertyValue('--severity-color')).toBe('var(--tone-red-text)');
  });

  it('a muted issue keeps its severity as an outlined neutral chip, with no coloured accent', () => {
    render(<Issues />);
    const row = screen.getByText(/Test warning issue description/).closest('tr');
    const chip = [...row.querySelectorAll('.ds-chip')].find((el) => el.textContent.trim() === 'WARNING');
    expect(chip.className).toContain('ds-chip-outline');
    expect(chip.className).not.toMatch(/ds-chip-(warn|err)/);
    expect(row.style.getPropertyValue('--severity-color')).toBe('var(--border-hover)');
  });

  it('colours by status too: a resolved critical issue is not red', () => {
    expect(getSeverityColor('CRITICAL', 'RESOLVED')).toBe('var(--border-hover)');
    expect(getSeverityColor('CRITICAL', 'ACKNOWLEDGED')).toBe('var(--tone-red-text)');
  });

  it('renders count heat indicators', () => {
    render(<Issues />);
    // Issue with count 15 should have amber heat (15× rendered)
    const countElements = screen.getAllByText(/15/);
    const amberCount = countElements.find(el => el.className?.includes('count-heat-amber'));
    expect(amberCount).toBeTruthy();
  });

  it('renders summary bar with separated severity and status sections', () => {
    render(<Issues />);
    // Use class-based query since text appears in multiple places
    const summaryLabels = screen.getAllByText('Severity');
    expect(summaryLabels.length).toBeGreaterThanOrEqual(1);
    const statusLabels = screen.getAllByText('Status');
    expect(statusLabels.length).toBeGreaterThanOrEqual(1);
  });

  it('shows checkboxes for bulk selection', () => {
    render(<Issues />);
    const checkboxes = screen.getAllByRole('checkbox');
    // 1 select-all + 2 row checkboxes
    expect(checkboxes.length).toBe(3);
  });

  it('bulk toolbar offers only the actions that apply', () => {
    render(<Issues />);
    const checkboxes = screen.getAllByRole('checkbox');
    fireEvent.click(checkboxes[1]); // an OPEN issue
    expect(screen.getByText('1 selected')).toBeTruthy();
    expect(screen.getByText(/Resolve 1/)).toBeTruthy();
    expect(screen.getByText(/Mute 1/)).toBeTruthy();
    expect(screen.queryByText(/Reopen 1/)).toBeNull();
    fireEvent.click(checkboxes[1]);
    fireEvent.click(checkboxes[2]); // a MUTED issue
    expect(screen.getByText(/Reopen 1/)).toBeTruthy();
    expect(screen.queryByText(/Resolve 1/)).toBeNull();
  });

  it('hides the Age column by default and keeps it under Columns', () => {
    const { container } = render(<Issues />);
    const headings = Array.from(container.querySelectorAll('thead th')).map((th) => th.textContent.trim());
    expect(headings.some((h) => h.startsWith('Age'))).toBe(false);
    expect(headings.some((h) => h.startsWith('Last seen'))).toBe(true);
  });

  it('shows the Age column to someone who chose it', () => {
    window.localStorage.getItem.mockImplementation((k) => (k === 'issueColumnVisibility' ? JSON.stringify({ age: true }) : null));
    const { container } = render(<Issues />);
    const headings = Array.from(container.querySelectorAll('thead th')).map((th) => th.textContent.trim());
    expect(headings.some((h) => h.startsWith('Age'))).toBe(true);
    window.localStorage.getItem.mockReset();
  });

  it('renders the last-seen column with relative time', () => {
    render(<Issues />);
    // Should show "1 hour ago" or similar (no "about" prefix)
    const ageElements = screen.getAllByText(/ago/i);
    expect(ageElements.length).toBeGreaterThan(0);
  });

  it('renders the auto-refresh indicator until the first fetch time is known', () => {
    render(<Issues />);
    expect(screen.getByText('issues.autoRefresh')).toBeTruthy();
  });

  it('offers a time-range filter', () => {
    render(<Issues />);
    const select = screen.getByLabelText('issues.filters.timeRange');
    expect([...select.options].map((o) => o.value)).toEqual(['', '24', '168', '720']);
  });
});

describe('investigateLink', () => {
  it('covers 30 minutes before first seen to 15 after last seen, scoped to the issue', async () => {
    const { investigateLink } = await import('../issues/IssuePanel');
    const url = new URL('http://x' + investigateLink({
      created_at: '2026-10-10T10:00:00Z', last_seen_at: '2026-10-10T11:00:00Z',
      project: 7, environment: 'production', component: 'checkout', description: 'boom',
    }));
    expect(url.pathname).toBe('/dash/investigate');
    expect(url.searchParams.get('start')).toBe('2026-10-10T09:30:00.000Z');
    expect(url.searchParams.get('end')).toBe('2026-10-10T11:15:00.000Z');
    expect(url.searchParams.get('project_id')).toBe('7');
    expect(url.searchParams.get('services')).toBe('checkout');
    expect(url.searchParams.get('hint')).toBe('boom');
  });
});


// Review item 2: on the read-only demo the row menu and the bulk bar offer
// nothing that would write.
describe('Issues on the read-only demo', () => {
  beforeEach(() => window.localStorage.getItem.mockImplementation((k) => (k === 'user' ? JSON.stringify({ username: 'demo', is_demo: true }) : null)));
  afterEach(() => window.localStorage.getItem.mockReset());

  it('row menu: Resolve, Mute and Reopen are off, reading entries stay on', () => {
    render(<Issues />);
    fireEvent.click(screen.getByLabelText('Actions for issue 1'));
    const resolve = screen.getByText('issues.panel.resolve').closest('.dropdown-item');
    const mute = screen.getByText('issues.panel.mute').closest('.dropdown-item');
    [resolve, mute].forEach((el) => {
      expect(el.className).toContain('disabled');
      expect(el.getAttribute('title')).toBe('demo.readOnlyNotice');
    });
    expect(screen.getByText('issues.panel.copyLink').closest('.dropdown-item').className).not.toContain('disabled');
    fireEvent.click(screen.getByLabelText('Actions for issue 2'));
    expect(screen.getByText('issues.panel.reopen').closest('.dropdown-item').className).toContain('disabled');
  });

  it('bulk bar: Resolve, Mute and Reopen are off', () => {
    render(<Issues />);
    screen.getAllByRole('checkbox').forEach((box) => { if (!box.checked) fireEvent.click(box); });
    const bar = document.querySelector('.bulk-toolbar');
    expect(bar).toBeTruthy();
    const writes = Array.from(bar.querySelectorAll('button')).filter((b) => /^(Resolve|Mute|Reopen)/.test(b.textContent));
    expect(writes.length).toBeGreaterThan(0);
    writes.forEach((b) => {
      expect(b.disabled).toBe(true);
      expect(b.getAttribute('title')).toBe('demo.readOnlyNotice');
    });
  });
});

// Final pass: the heading of an analysis's issues was "1 Issues Detected",
// in English whatever the language. It is the page name, as in the menu.
describe('Issues of one analysis', () => {
  it('keeps the page name as its heading', () => {
    routeParams = { batchId: 'acme-studio-l10-r1' };
    try {
      render(<Issues />);
      expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('System Issues');
      expect(screen.queryByText(/Issues Detected/)).toBeNull();
    } finally {
      routeParams = {};
    }
  });
});

// Review item 8: the Component column cut service names ("check…", "shippi…").
describe('Issues table: Component column', () => {
  it('has its own width class and shows the whole name, also in the title', () => {
    render(<Issues />);
    const header = screen.getByText('Component').closest('th');
    expect(header.className).toContain('issue-col-component');
    expect(header.style.width).toBe('');
    const chip = screen.getByText('payment-service');
    expect(chip.getAttribute('title')).toBe('payment-service');
    const cell = chip.closest('td');
    expect(cell.className).toContain('issue-cell-component');
    expect(cell.style.maxWidth).toBe('');
  });
});

// The list had about 70 sentences written in the code, shown in English
// whatever the language. They are in the translation files now.
describe('Issues list in French', () => {
  beforeEach(() => { mockLang = 'fr'; });
  afterEach(() => { mockLang = 'en'; });

  it('shows filters, column names, severity and the row controls in French', () => {
    render(<Issues />);
    ['Composant', 'Vu en dernier', 'Sévérité', 'Statut', 'Colonnes'].forEach((text) => expect(screen.getByText(new RegExp(`^\\s*${text}$`))).toBeTruthy());
    expect(screen.getByLabelText('Filtrer par sévérité').options[0].textContent).toBe('Toutes les sévérités');
    expect([...screen.getByLabelText('Filtrer par statut').options].map((o) => o.textContent))
      .toEqual(['Tous les statuts', 'Ouvert', 'En sourdine', 'Résolu']);
    expect(screen.getByText('CRITIQUE').className).toBe('ds-chip ds-chip-err');
    expect(screen.getByText('AVERTISSEMENT')).toBeTruthy();
    expect(screen.getByLabelText('Actions pour le problème 1')).toBeTruthy();
    expect(screen.getByLabelText('Sélectionner tous les problèmes')).toBeTruthy();
    expect(screen.queryByText(/^(Component|Severity|Status|Columns|CRITICAL|WARNING)$/)).toBeNull();
  });

  it('counts the selection in French, singular and plural', () => {
    render(<Issues />);
    const boxes = screen.getAllByRole('checkbox');
    fireEvent.click(boxes[1]);
    expect(screen.getByText('1 sélectionné')).toBeTruthy();
    fireEvent.click(boxes[2]);
    expect(screen.getByText('2 sélectionnés')).toBeTruthy();
    expect(screen.getByText('Tout désélectionner')).toBeTruthy();
  });
});

describe('Issues list: no sentence left in the code', () => {
  const source = readFileSync(resolve(__dirname, '../Issues.jsx'), 'utf8');
  const jsx = source.slice(source.indexOf('const Issues = () =>'));

  it('has no English text node, label or message outside t()', () => {
    // Text between tags: a capital then letters, not inside {…}.
    expect(jsx.match(/>\s*[A-Z][a-z]+[^<>{}=;()]*</g) || []).toEqual([]);
    expect(jsx.match(/(aria-label|title|placeholder)="[^"]*"/g) || []).toEqual([]);
    expect(jsx.match(/toast\.\w+\(\s*["`]/g) || []).toEqual([]);
  });

  it('has every list string in English and in French, with the same variables', () => {
    const flat = (o, p = '') => Object.entries(o).flatMap(([k, v]) => (typeof v === 'string' ? [[p + k, v]] : flat(v, `${p}${k}.`)));
    const en = Object.fromEntries(flat(mockLocales.en.issues.list));
    const fr = Object.fromEntries(flat(mockLocales.fr.issues.list));
    expect(Object.keys(fr).sort()).toEqual(Object.keys(en).sort());
    const vars = (text) => (text.match(/\{\{\w+\}\}/g) || []).sort();
    Object.keys(en).forEach((key) => expect([key, vars(fr[key])]).toEqual([key, vars(en[key])]));
    const used = [...source.matchAll(/t\('issues\.list\.([\w.]+)'/g)].map((m) => m[1]);
    used.forEach((key) => expect(Object.keys(en).some((k) => k === key || k.startsWith(`${key}_`))).toBe(true));
    expect(used.length).toBeGreaterThan(60);
  });
});

// A1: the layout follows the width of the list's card.
describe('Issues list layout by card width', () => {
  const widthOf = (px) => vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function rect() {
    const w = this.classList?.contains('issues-page-card') ? px : 0;
    return { width: w, height: 0, top: 0, left: 0, right: w, bottom: 0, x: 0, y: 0, toJSON() {} };
  });
  afterEach(() => vi.restoreAllMocks());

  it('is the full table before the card is measured', () => {
    render(<Issues />);
    expect(document.querySelector('.issues-table-wrap').className).toContain('issues-tier-full');
    expect(document.querySelector('.issue-row-meta')).toBeNull();
  });

  it('puts Last seen and Occurrences under the description in a 728 px card', () => {
    widthOf(728);
    render(<Issues />);
    expect(document.querySelector('.issues-table-wrap').className).toContain('issues-tier-compact');
    const meta = document.querySelectorAll('.issue-row-meta');
    expect(meta.length).toBe(2);
    expect(meta[0].textContent).toMatch(/^Last seen .+Occurrences 15×$/);
  });

  it('is one card per issue in a 343 px card', () => {
    widthOf(343);
    render(<Issues />);
    expect(document.querySelector('.issues-table-wrap').className).toContain('issues-tier-cards');
  });
});

// A8: on a phone the cards showed "1 day ago" and "1×" with no label.
describe('Issues cards: labelled values', () => {
  it('names Last seen and Occurrences on each row, for the card layout', () => {
    render(<Issues />);
    const row = screen.getByText('Test critical issue description').closest('tr');
    expect(row.querySelector('.issue-cell-seen').getAttribute('data-label')).toBe('Last seen');
    expect(row.querySelector('.issue-cell-count').getAttribute('data-label')).toBe('Occurrences');
  });

  it('shows the label in the card layout only', () => {
    const css = readFileSync(resolve(__dirname, '../Issues.css'), 'utf8');
    expect(css).toMatch(/\.issues-tier-cards tbody tr\.issue-row > td\.issue-cell-meta\[data-label\]::before \{\s*content: attr\(data-label\);/);
    expect(css.match(/\[data-label\]::before/g).length).toBe(1);
  });
});

// Owner's decision of 23 Nov: at 1,024 px, where Last seen and Occurrences
// sit under the description, the list can still be sorted by them.
describe('Issues list at 1,024 px: sorting by the two moved columns', () => {
  afterEach(() => vi.restoreAllMocks());

  it('has their sort controls in the Description header, with the column names', () => {
    vi.spyOn(HTMLElement.prototype, 'getBoundingClientRect').mockImplementation(function rect() {
      const w = this.classList?.contains('issues-page-card') ? 728 : 0;
      return { width: w, height: 0, top: 0, left: 0, right: w, bottom: 0, x: 0, y: 0, toJSON() {} };
    });
    render(<Issues />);
    const header = screen.getByText('Description').closest('th');
    const buttons = [...header.querySelectorAll('button.issue-th-sort')];
    expect(buttons.map((b) => b.textContent)).toEqual(['Last seen', 'Occurrences']);
    fireEvent.click(buttons[0]);
    // The chosen column shows the "sorted" arrow.
    expect(buttons[0].querySelector('.text-primary')).toBeTruthy();
    expect(buttons[1].querySelector('.text-primary')).toBeNull();
  });

  it('has no such control where the columns have their own header', () => {
    render(<Issues />);
    expect(document.querySelector('.issue-th-sort')).toBeNull();
  });
});
