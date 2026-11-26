import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { MemoryRouter } from 'react-router-dom';
import IssuePanel from '../issues/IssuePanel';

vi.mock('react-i18next', () => ({
  // Severity names resolve as in en.json; every other key shows as itself.
  useTranslation: () => ({ t: (key, opts) => ({ 'issues.critical': 'Critical', 'issues.warning': 'Warning' }[key] || (opts ? `${key} ${JSON.stringify(opts)}` : key)) }),
}));

const base = {
  id: 7, severity: 'CRITICAL', status: 'OPEN', description: 'payment-worker cannot reach Redis',
  component: 'payment-worker', root_cause: 'Pool shrank to 20 in v2.3.3', recommendation: 'Raise the pool to 50',
};
const noop = () => {};
const panel = (issue, onResolve = noop) => render(
  <MemoryRouter>
    <IssuePanel issue={issue} onClose={noop} onResolve={onResolve} onMute={noop} onReopen={noop}
      onAcknowledge={noop} onAskAI={noop} onCopyLink={noop} />
  </MemoryRouter>,
);

describe('IssuePanel resolve', () => {
  it('resolves with the root cause the person confirmed or corrected', () => {
    const onResolve = vi.fn();
    panel(base, onResolve);
    fireEvent.click(screen.getByRole('button', { name: /issues.panel.resolve$/ }));
    const cause = screen.getByLabelText('issues.panel.resolveRootCause');
    expect(cause.value).toBe('Pool shrank to 20 in v2.3.3');
    fireEvent.change(cause, { target: { value: 'A network policy blocked Redis' } });
    fireEvent.click(screen.getByRole('button', { name: /issues.panel.resolveConfirm/ }));
    expect(onResolve).toHaveBeenCalledWith(base, { root_cause: 'A network policy blocked Redis', fix: 'Raise the pool to 50' });
  });

  it('cancel leaves the issue open', () => {
    const onResolve = vi.fn();
    panel(base, onResolve);
    fireEvent.click(screen.getByRole('button', { name: /issues.panel.resolve$/ }));
    fireEvent.click(screen.getByRole('button', { name: 'common.cancel' }));
    expect(onResolve).not.toHaveBeenCalled();
    expect(screen.queryByLabelText('issues.panel.resolveRootCause')).toBeNull();
  });

  it('shows the corrected root cause, who confirmed it and what the AI said', () => {
    panel({ ...base, status: 'RESOLVED', resolution_root_cause: 'A network policy blocked Redis',
      resolution_fix: 'Restored the policy', resolved_by_name: 'Ada Ops' });
    const text = document.body.textContent;
    expect(text).toContain('issues.panel.confirmedRootCause {"name":"Ada Ops"}');
    expect(text).toContain('A network policy blocked Redis');
    expect(text).toContain('Pool shrank to 20 in v2.3.3');
    expect(text).toContain('Restored the policy');
  });

  // Seen by the owner on #768: the confirmed cause in full, what fixed it
  // right under it, and what the AI had said folded behind its own title.
  it('a confirmed cause comes first, then what fixed it, with the AI\'s cause folded', async () => {
    const AI = 'The pool shrank to 20 in v2.3.3. Each checkout holds a connection for 300 ms. At peak the workers wait.';
    panel({ ...base, status: 'RESOLVED', root_cause: AI, resolution_root_cause: 'A network policy blocked Redis',
      resolution_fix: 'Restored the policy', resolved_by_name: 'Ada Ops' });
    const titles = [...document.querySelectorAll('.issue-panel-section h3')].map((h) => h.textContent);
    expect(titles.slice(0, 4)).toEqual(['issues.panel.confirmedRootCause {"name":"Ada Ops"}', 'issues.panel.whatFixedIt',
      'issues.panel.aiSaidTitle', 'issues.panel.recommendation']);
    expect(screen.getByText('A network policy blocked Redis').tagName).toBe('P');
    const fold = screen.getByRole('button', { name: 'issues.panel.aiSaidTitle' });
    expect(fold.getAttribute('aria-expanded')).toBe('false');
    const said = document.getElementById(fold.getAttribute('aria-controls'));
    expect(said.hidden).toBe(true);
    expect(said.textContent).toBe(AI);
    await userEvent.click(fold);
    expect(said.hidden).toBe(false);
  });

  it('a cause the team confirmed unchanged shows once, with no fold', () => {
    panel({ ...base, status: 'RESOLVED', resolution_root_cause: base.root_cause });
    expect(screen.queryByRole('button', { name: 'issues.panel.aiSaidTitle' })).toBeNull();
    expect(screen.getAllByText(base.root_cause)).toHaveLength(1);
  });
});

describe('IssuePanel evidence', () => {
  it('links a correlated commit to the code changes it came from', () => {
    panel({ ...base, batch_id_str: 'shop-1', linked_commits: [{ sha: 'e7d3b201abc', message: 'hotfix' }] });
    const link = screen.getByRole('link', { name: 'e7d3b201' });
    expect(link.getAttribute('href')).toBe('/dash/code-changes/shop-1?sha=e7d3b201abc');
  });

  it('shows a commit the analysis has no code change for as plain text', () => {
    panel({ ...base, batch_id_str: 'shop-1', linked_commits: [{ sha: 'e7d3b201abc', message: 'hotfix', in_batch: false }] });
    expect(screen.getByText('e7d3b201')).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'e7d3b201' })).toBeNull();
    expect(document.querySelector('a[href*="code-changes"]')).toBeNull();
  });
});

describe('IssuePanel title', () => {
  const LONG = "Since the pricing rollout at 00:24:45, every /price call for SKU-1001 fails with decimal.InvalidOperation ('quantize result has too many digits for current context') in the rounding step. pricing returns HTTP 500 to catalog.";

  it('shows a headline cut at a word boundary, the whole text in the title attribute and once below', () => {
    panel({ ...base, description: LONG });
    const title = screen.getByRole('heading', { level: 2 });
    expect(title.textContent).toBe('Since the pricing rollout at 00:24:45, every /price call for SKU-1001 fails with decimal.InvalidOperation…');
    expect(title.textContent.length).toBeLessThanOrEqual(121);
    expect(title.getAttribute('title')).toBe(LONG);
    expect(screen.getAllByText(LONG)).toHaveLength(1);
  });

  it('does not repeat a short description', () => {
    panel(base);
    expect(screen.getAllByText('payment-worker cannot reach Redis')).toHaveLength(1);
  });

  // Colour rules: red means "needs action now".
  it('a resolved critical issue renders without the red treatment', () => {
    panel({ ...base, status: 'RESOLVED' });
    const severity = screen.getByText('CRITICAL');
    expect(severity.className).toBe('ds-chip ds-chip-outline');
    expect(document.querySelector('.ds-chip-err')).toBeNull();
    expect(screen.getByText(/issues.statusLabel.resolved/).className).toContain('ds-chip-ok');
  });

  it('an open critical issue is red, and its "Open" status is the brand tone, not amber', () => {
    panel(base);
    expect(screen.getByText('CRITICAL').className).toBe('ds-chip ds-chip-err');
    const status = screen.getByText(/issues.statusLabel.open/);
    expect(status.className).toContain('ds-chip-brand');
    expect(status.className).not.toContain('ds-chip-warn');
  });
});

// 1.5.6: the answer first. The panel shows the cause and the steps, folds
// the rest, and keeps every word the AI wrote in the page.
describe('IssuePanel layout', () => {
  const CAUSE = 'The pool shrank to 20 in v2.3.3. Each checkout holds a connection for 300 ms. At peak the workers wait for a free connection. Redis itself is healthy.';
  const ACTION = 'Raise the pool to 50. Restart payment-worker. Watch the wait time on the dashboard.';
  const full = {
    ...base,
    description: 'payment-worker cannot reach Redis. Checkouts fail after 5 s. The error rate is 12%.',
    root_cause: CAUSE, recommendation: ACTION, confidence: 'medium',
    reasoning: '1. The errors start with the v2.3.3 rollout.\n2. The pool size changed in that release.',
    metric_anomaly_type: 'error_rate_spike',
    created_at: '2026-11-20T10:00:00Z', last_seen_at: '2026-11-20T10:00:00Z', occurrence_count: 1,
  };
  const headings = () => [...document.querySelectorAll('.issue-panel-section h3')].map((h) => h.textContent);

  it('shows the summary, the cause, the action, then the reasons, the correlations and the facts', () => {
    panel({ ...full, status: 'RESOLVED', resolution_fix: 'Raised the pool' });
    expect(headings()).toEqual([
      'issues.panel.rootCause', 'issues.panel.whatFixedIt', 'issues.panel.recommendation',
      expect.stringContaining('issues.panel.reasoning'), 'issues.panel.correlations',
    ]);
    const body = document.querySelector('.offcanvas-body');
    const order = ['.issue-panel-summary', '.issue-panel-reasons', '.issue-panel-facts', '.issue-panel-links']
      .map((sel) => [...body.querySelectorAll('*')].indexOf(body.querySelector(sel)));
    expect(order).toEqual([...order].sort((a, b) => a - b));
    expect(order[0]).toBeGreaterThanOrEqual(0);
  });

  it('the summary is the text after the headline, held to three lines', () => {
    panel(full);
    const summary = document.querySelector('.issue-panel-summary p');
    expect(summary.textContent).toBe('Checkouts fail after 5 s. The error rate is 12%.');
    expect(summary.className).toBe('attention-clamp-3');
    expect(screen.getAllByText(/payment-worker cannot reach Redis/)).toHaveLength(1);
  });

  it('the root cause shows two sentences and folds the rest, which stays in the page', async () => {
    panel(full);
    const more = screen.getByRole('button', { name: 'dashboard.attention.showMore' });
    const rest = document.getElementById(more.getAttribute('aria-controls'));
    expect(rest.hidden).toBe(true);
    expect(rest.textContent.trim()).toBe('At peak the workers wait for a free connection. Redis itself is healthy.');
    expect(rest.closest('p').textContent).toBe(CAUSE);
    expect(more.getAttribute('aria-expanded')).toBe('false');
    more.focus();
    await userEvent.keyboard('{Enter}');
    expect(rest.hidden).toBe(false);
    expect(more.getAttribute('aria-expanded')).toBe('true');
    expect(more.textContent).toBe('dashboard.attention.showLess');
  });

  it('a short root cause has no fold', () => {
    panel({ ...full, root_cause: 'The pool shrank to 20. Redis is healthy.' });
    expect(screen.queryByRole('button', { name: 'dashboard.attention.showMore' })).toBeNull();
  });

  it('the action is numbered steps, all of them shown', () => {
    panel({ ...full, recommendation: `${ACTION} Roll back if the wait stays above 50 ms. Open an incident review.` });
    const steps = [...document.querySelectorAll('ol.attention-steps li')].map((li) => li.textContent);
    expect(steps).toEqual(['Raise the pool to 50.', 'Restart payment-worker.', 'Watch the wait time on the dashboard.',
      'Roll back if the wait stays above 50 ms.', 'Open an incident review.']);
  });

  it('an action written as a numbered list keeps its steps', () => {
    panel({ ...full, recommendation: '1. Raise the pool to 50\n2. Restart payment-worker' });
    expect([...document.querySelectorAll('ol.attention-steps li')].map((li) => li.textContent))
      .toEqual(['Raise the pool to 50', 'Restart payment-worker']);
  });

  it('a one-sentence action stays a paragraph', () => {
    panel({ ...full, recommendation: 'Raise the pool to 50.' });
    expect(document.querySelector('ol.attention-steps')).toBeNull();
    expect(screen.getByText('Raise the pool to 50.').tagName).toBe('P');
  });

  it('"Why the AI thinks so" is folded, with the confidence on its title line', async () => {
    panel(full);
    const fold = screen.getByRole('button', { name: /issues.panel.reasoning/ });
    expect(fold.getAttribute('aria-expanded')).toBe('false');
    expect(fold.textContent).toContain('confidenceLevel.medium');
    const list = document.getElementById(fold.getAttribute('aria-controls'));
    expect(list.hidden).toBe(true);
    expect(list.textContent).toContain('The pool size changed in that release.');
    fold.focus();
    await userEvent.keyboard(' ');
    expect(fold.getAttribute('aria-expanded')).toBe('true');
    expect(list.hidden).toBe(false);
    expect(document.querySelector('.issue-panel-facts').textContent).not.toContain('issues.panel.confidence');
  });

  it('facts: last seen only when it differs, occurrences only above 1', () => {
    const { unmount } = panel(full);
    const facts = () => document.querySelector('.issue-panel-facts').textContent;
    expect(facts()).toContain('issues.panel.firstSeen');
    expect(facts()).not.toContain('issues.panel.lastSeen');
    expect(facts()).not.toContain('issues.panel.occurrences');
    unmount();
    panel({ ...full, last_seen_at: '2026-11-20T11:30:00Z', occurrence_count: 3 });
    expect(facts()).toContain('issues.panel.lastSeen');
    expect(facts()).toContain('3×');
  });

  it('an issue with no root cause and no action', () => {
    panel({ ...full, root_cause: '', recommendation: '' });
    expect(screen.getByText('issues.panel.noRootCause')).toBeInTheDocument();
    expect(headings()).not.toContain('issues.panel.recommendation');
  });

  it('a muted issue shows the same body, with Reopen', () => {
    panel({ ...full, status: 'MUTED' });
    expect(headings()[0]).toBe('issues.panel.rootCause');
    expect(screen.getByRole('button', { name: /issues.panel.reopen/ })).toBeInTheDocument();
  });

  // Session A is making the AI's text shorter: two or three sentences and
  // the action as a numbered list read with no fold at all.
  it('a short text reads whole, with no fold but the reasons', () => {
    panel({ ...full, description: 'payment-worker cannot reach Redis. Checkouts fail.',
      root_cause: 'The pool shrank to 20 in v2.3.3. At peak the workers wait for a connection.',
      recommendation: '1. Raise the pool to 50.\n2. Restart payment-worker.\n3. Watch the wait time.' });
    expect(document.querySelector('.issue-panel-summary p').textContent).toBe('Checkouts fail.');
    expect(screen.queryByRole('button', { name: 'dashboard.attention.showMore' })).toBeNull();
    expect(document.querySelectorAll('ol.attention-steps li')).toHaveLength(3);
    expect([...document.querySelectorAll('button[aria-expanded]')].map((b) => b.textContent))
      .toEqual([expect.stringContaining('issues.panel.reasoning')]);
  });

  it('the resolve form still starts from the whole root cause and action', () => {
    const onResolve = vi.fn();
    panel(full, onResolve);
    fireEvent.click(screen.getByRole('button', { name: /issues.panel.resolve$/ }));
    expect(screen.getByLabelText('issues.panel.resolveRootCause').value).toBe(CAUSE);
    expect(screen.getByLabelText('issues.panel.resolveFix').value).toBe(ACTION);
  });
});
