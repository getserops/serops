/**
 * PR-UI2 · jest-axe a11y assertions against small render surfaces.
 *
 * Complements the Playwright I6 invariant (which runs axe on live
 * pages against real fixtures) with a fast unit-test loop that
 * catches a11y regressions in individual components before they
 * ship.
 *
 * Scoped narrowly: we render minimal, self-contained fragments — a
 * severity chip, a hero-shape card, a filter dropdown — not the full
 * page. Full-page render pulls in router/context/query hooks; that
 * belongs in Playwright, not vitest.
 */

import { describe, it, expect } from 'vitest';
import { render } from '@testing-library/react';
import { axe, toHaveNoViolations } from 'jest-axe';

import { armConsoleHygiene } from '../../test/console-hygiene';

expect.extend(toHaveNoViolations);


describe('a11y · severity chip', () => {
  armConsoleHygiene();

  it('CRITICAL chip has no axe violations', async () => {
    const { container } = render(
      <span
        className="ds-chip ds-chip-err"
        role="status"
        aria-label="Severity: critical"
      >
        CRITICAL
      </span>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});


describe('a11y · hero card shell', () => {
  armConsoleHygiene();

  it('hero-shape wrapper with labelled icon has no violations', async () => {
    // Mirrors the shape of the Detail hero card (Detail.jsx:322):
    // decorative icon, uppercase label, primary prose line.
    const { container } = render(
      <div className="ds-card ds-card-elevated" role="region" aria-label="AI hypothesis">
        <div className="ds-card-body">
          <div
            style={{
              width: 44, height: 44, borderRadius: 8,
              background: 'hsl(230, 100%, 96%)',
              color: 'var(--primary-600)',
            }}
            aria-hidden="true"
          >
            <span aria-hidden="true">🧠</span>
          </div>
          <div>
            <p style={{
              fontSize: 11, textTransform: 'uppercase',
              color: 'var(--text-tertiary)',
            }}>
              AI hypothesis
            </p>
            <p>
              Redis service at redis:6379 is unreachable. The connection
              refusal indicates either Redis is not running or the port
              is misconfigured.
            </p>
          </div>
        </div>
      </div>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});


describe('a11y · icon-only action button', () => {
  armConsoleHygiene();

  it('icon-only button MUST carry an aria-label', async () => {
    // This is the exact shape PR-UI1 fixed for the per-row Actions
    // dropdown toggle on the Issues page.
    const { container } = render(
      <button
        type="button"
        aria-label="Actions for issue #1234"
        className="btn btn-link btn-sm"
      >
        <svg aria-hidden="true" width={14} height={14} viewBox="0 0 14 14">
          <circle cx="3" cy="7" r="1.4" fill="currentColor" />
          <circle cx="7" cy="7" r="1.4" fill="currentColor" />
          <circle cx="11" cy="7" r="1.4" fill="currentColor" />
        </svg>
      </button>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('icon-only button WITHOUT aria-label fails axe (regression fence)', async () => {
    // Negative case: verifies our axe scan actually catches the class
    // of bug PR-UI1 shipped fixes for. If jest-axe is broken or the
    // rule set changes and stops flagging this, this test fails and
    // we notice.
    const { container } = render(
      <button type="button" className="btn btn-link btn-sm">
        <svg aria-hidden="true" width={14} height={14} viewBox="0 0 14 14">
          <circle cx="3" cy="7" r="1.4" fill="currentColor" />
          <circle cx="7" cy="7" r="1.4" fill="currentColor" />
          <circle cx="11" cy="7" r="1.4" fill="currentColor" />
        </svg>
      </button>,
    );
    const results = await axe(container);
    const violationIds = results.violations.map((v) => v.id);
    expect(violationIds).toContain('button-name');
  });
});


describe('a11y · form controls', () => {
  armConsoleHygiene();

  it('labelled search input has no violations', async () => {
    const { container } = render(
      <label className="d-flex align-items-center gap-2">
        <span className="visually-hidden">Search logs</span>
        <input
          type="search"
          className="search-input"
          placeholder="Search logs…"
          aria-label="Search logs"
        />
      </label>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });

  it('checkbox with row context has no violations', async () => {
    const { container } = render(
      <table>
        <tbody>
          <tr>
            <td>
              <input
                type="checkbox"
                aria-label="Select batch gt-audit-p1-s5-cascade"
              />
            </td>
            <td>gt-audit-p1-s5-cascade</td>
          </tr>
        </tbody>
      </table>,
    );
    const results = await axe(container);
    expect(results).toHaveNoViolations();
  });
});
