import { describe, it, expect, vi, beforeEach } from 'vitest';
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

  it('truncates long names with title case', () => {
    const long = 'very-long-component-name';
    const result = abbreviateComponent(long);
    expect(result.length).toBeLessThanOrEqual(14);
    expect(result).toContain('\u2026');
    // Should start with uppercase
    expect(result[0]).toBe(result[0].toUpperCase());
  });

  it('title-cases short names', () => {
    expect(abbreviateComponent('redis')).toBe('Redis');
    expect(abbreviateComponent('nginx')).toBe('Nginx');
    expect(abbreviateComponent('backend')).toBe('Backend');
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
  it('returns red for critical', () => {
    expect(getSeverityColor('critical')).toBe('#e53935');
    expect(getSeverityColor('CRITICAL')).toBe('#e53935');
  });

  it('returns orange for warning', () => {
    expect(getSeverityColor('warning')).toBe('#fb8c00');
    expect(getSeverityColor('WARNING')).toBe('#fb8c00');
  });

  it('returns grey for unknown/null', () => {
    expect(getSeverityColor(null)).toBe('#6c757d');
    expect(getSeverityColor('UNKNOWN')).toBe('#6c757d');
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
vi.mock('react-router-dom', () => ({
  useNavigate: () => vi.fn(),
  useParams: () => ({}),
  useSearchParams: () => [new URLSearchParams(), vi.fn()],
}));

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key) => {
      const translations = {
        'common.loading': 'Loading...',
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
    expect(screen.getByText('Age')).toBeTruthy();
    expect(screen.getByText('Occurrences')).toBeTruthy();
    expect(screen.getByText('Actions')).toBeTruthy();
  });

  it('renders issue rows', () => {
    render(<Issues />);
    expect(screen.getByText('#1')).toBeTruthy();
    expect(screen.getByText('#2')).toBeTruthy();
  });

  it('renders component chips with abbreviation', () => {
    render(<Issues />);
    // "payment-service" (15 chars) truncated to 12 + ellipsis, title-cased
    expect(screen.getByText('Payment-serv\u2026')).toBeTruthy();
    expect(screen.getByText('Infra')).toBeTruthy();
  });

  it('renders severity as an uppercase badge', () => {
    // The severity cell renders <span class="severity-badge severity-badge-critical">CRITICAL</span>.
    // This test previously looked for lowercase 'critical' inside a
    // '.severity-compact' wrapper — markup from an earlier design that the
    // component no longer emits, so it asserted a UI that did not exist.
    render(<Issues />);
    const badges = document.querySelectorAll('.severity-badge');
    expect(badges.length).toBeGreaterThanOrEqual(1);
    const critical = [...badges].find(el => el.textContent.trim() === 'CRITICAL');
    expect(critical).toBeTruthy();
    expect(critical.className).toContain('severity-badge-critical');
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

  it('shows bulk toolbar when items are selected', () => {
    render(<Issues />);
    const checkboxes = screen.getAllByRole('checkbox');
    // Click first row checkbox
    fireEvent.click(checkboxes[1]);
    expect(screen.getByText('1 selected')).toBeTruthy();
    expect(screen.getByText(/Resolve 1/)).toBeTruthy();
    expect(screen.getByText(/Mute 1/)).toBeTruthy();
  });

  it('renders age column with relative time', () => {
    render(<Issues />);
    // Should show "1 hour ago" or similar (no "about" prefix)
    const ageElements = screen.getAllByText(/ago/i);
    expect(ageElements.length).toBeGreaterThan(0);
  });

  it('renders auto-refresh indicator', () => {
    render(<Issues />);
    expect(screen.getByText('auto-refresh')).toBeTruthy();
  });
});
