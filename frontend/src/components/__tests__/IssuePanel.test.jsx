import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import IssuePanel from '../issues/IssuePanel';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({ t: (key, opts) => (opts ? `${key} ${JSON.stringify(opts)}` : key) }),
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
    expect(text).toContain('issues.panel.aiSaid {"text":"Pool shrank to 20 in v2.3.3"}');
    expect(text).toContain('Restored the policy');
  });
});

describe('IssuePanel evidence', () => {
  it('links a correlated commit to the code changes it came from', () => {
    panel({ ...base, batch_id_str: 'shop-1', linked_commits: [{ sha: 'e7d3b201abc', message: 'hotfix' }] });
    const link = screen.getByRole('link', { name: 'e7d3b201' });
    expect(link.getAttribute('href')).toBe('/dash/code-changes/shop-1?sha=e7d3b201abc');
  });
});
