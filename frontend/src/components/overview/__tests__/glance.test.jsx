import React from 'react';
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

import en from '../../../locales/en.json';
import fr from '../../../locales/fr.json';

// t as i18next resolves it: plural forms by count, {{x}} filled in.
let locale = en;
const plural = (n) => (locale === fr ? (n <= 1 ? 'one' : 'other') : (n === 1 ? 'one' : 'other'));
const t = (key, opts = {}) => {
  const look = (k) => k.split('.').reduce((o, p) => o?.[p], locale);
  let text = opts.count != null ? look(`${key}_${plural(opts.count)}`) : undefined;
  if (typeof text !== 'string') text = look(key);
  if (typeof text !== 'string') return key;
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => opts[name] ?? '');
};
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t }) }));

import { serviceGroups } from '../serviceGroups';
import StatusCard, { SQUARES_MAX } from '../StatusCard';
import ServicesPanel from '../ServicesPanel';
import CausesBar from '../CausesBar';
import AIAnalysisFeed from '../../AIAnalysisFeed';

const svc = (name, over = {}) => ({ name, critical_issues: 0, warning_issues: 0, open_issues: 0, health_score: 100, status: 'healthy', ...over });
// The demo's shape: 3 with an open critical issue, 7 affected, 9 healthy.
const DEMO = {
  total_services: 19,
  services: [
    svc('pricing', { critical_issues: 1 }), svc('fleet-redis', { critical_issues: 1 }), svc('shippingservice', { critical_issues: 1 }),
    ...['catalog', 'web', 'billing-worker', 'notifier', 'orders-api', 'checkoutservice', 'frontend'].map((n) => svc(n, { affected_by: ['pricing'] })),
    ...['tracking', 'nightly-reindex', 'fleet-db', 'dispatch', 'payments', 'cart', 'email', 'ads', 'search'].map((n) => svc(n)),
  ],
};
const wrap = (ui) => render(<MemoryRouter>{ui}</MemoryRouter>);

describe('service groups', () => {
  it('open issue, affected, healthy; worst first, then by name', () => {
    const g = serviceGroups({ total_services: 4, services: [svc('b'), svc('a', { warning_issues: 1 }), svc('c', { critical_issues: 2 }), svc('d', { affected_by: ['c'] })] });
    expect(g.open.map((s) => s.name)).toEqual(['c', 'a']);
    expect(g.affected.map((s) => s.name)).toEqual(['d']);
    expect(g.healthy.map((s) => s.name)).toEqual(['b']);
    expect(g.critical).toBe(1);
  });

  it('a server before 1.5.6: no affected_by, 12 of 19 listed, the rest counted healthy', () => {
    const g = serviceGroups({ total_services: 19, services: DEMO.services.slice(0, 12).map((s) => ({ ...s, affected_by: undefined })) });
    expect(g.affected).toEqual([]);
    expect(g.unlisted).toBe(7);
    expect(g.healthyCount).toBe(9 + 7);
  });

  it('a service with only an open info issue is not "open"', () => {
    expect(serviceGroups({ total_services: 1, services: [svc('x', { open_issues: 1 })] }).open).toEqual([]);
  });
});

describe('Status card', () => {
  it('says how many services have an open critical issue, and the rest', () => {
    locale = en;
    wrap(<StatusCard data={DEMO} />);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('3 of 19 services have an open critical issue');
    expect(screen.getByText('7 more are affected by them. 9 are healthy.')).toBeTruthy();
    const legend = document.querySelector('.glance-legend').textContent;
    expect(legend).toBe('3 with an open issue7 affected9 healthy');
  });

  it('in French, with singular forms', () => {
    locale = fr;
    wrap(<StatusCard data={{ total_services: 3, services: [svc('a', { critical_issues: 1 }), svc('b', { affected_by: ['a'] }), svc('c')] }} />);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('1 service sur 3 a un problème critique ouvert');
    expect(screen.getByText('1 autre est affecté. 1 est sain.')).toBeTruthy();
    expect(document.querySelector('.glance-legend').textContent).toBe('1 avec un problème ouvert1 affecté1 sain');
    locale = en;
  });

  it('a warning only: "has an open issue"; none: all healthy, with no detail', () => {
    const { unmount } = wrap(<StatusCard data={{ total_services: 2, services: [svc('a', { warning_issues: 1 }), svc('b')] }} />);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('1 of 2 services has an open issue');
    expect(document.querySelector('.glance-status').className).toContain('glance-tone-warning');
    unmount();
    wrap(<StatusCard data={{ total_services: 2, services: [svc('a'), svc('b')] }} />);
    expect(screen.getByRole('heading', { level: 2 }).textContent).toBe('All 2 services are healthy');
    expect(document.querySelector('.glance-status-detail')).toBeNull();
  });

  it('one square per service, in group order, each named', () => {
    wrap(<StatusCard data={DEMO} />);
    const squares = screen.getAllByRole('img');
    expect(squares).toHaveLength(19);
    expect(squares.slice(0, 3).map((s) => s.getAttribute('aria-label'))).toEqual(['fleet-redis', 'pricing', 'shippingservice']);
    expect(squares[3].getAttribute('title')).toBe('billing-worker');
    expect(squares[3].closest('li').className).toContain('glance-affected');
    expect(squares[18].closest('li').className).toContain('glance-healthy');
  });

  it(`above ${SQUARES_MAX} services, a three-part bar`, () => {
    const many = { total_services: 80, services: Array.from({ length: 80 }, (_, i) => svc(`s${i}`, i < 2 ? { critical_issues: 1 } : {})) };
    wrap(<StatusCard data={many} />);
    expect(screen.queryAllByRole('img')).toHaveLength(0);
    expect([...document.querySelectorAll('.glance-parts > span')].map((s) => s.style.flexGrow)).toEqual(['2', '78']);
  });

  it('nothing when no service is monitored', () => {
    const { container } = wrap(<StatusCard data={{ total_services: 0, services: [] }} />);
    expect(container.innerHTML).toBe('');
  });
});

describe('Services', () => {
  it('every service by name in three groups, the count in each title, no percentage', () => {
    wrap(<ServicesPanel data={DEMO} />);
    const titles = [...document.querySelectorAll('.glance-group h3')].map((h) => h.textContent);
    expect(titles).toEqual(['Open issue (3)', 'Affected by one of them (7)', 'Healthy (9)']);
    expect(document.body.textContent).not.toMatch(/%/);
  });

  it('each name opens the Issues page filtered on that service', () => {
    wrap(<ServicesPanel data={DEMO} />);
    expect(screen.getByRole('link', { name: 'pricing' }).getAttribute('href')).toBe('/dash/issues?component=pricing');
  });

  it('a long healthy group shows five names and "and N more", which opens the rest', () => {
    wrap(<ServicesPanel data={DEMO} />);
    const healthy = document.querySelectorAll('.glance-group')[2];
    expect(within(healthy).getAllByRole('link')).toHaveLength(5);
    const more = within(healthy).getByRole('button', { name: 'and 4 more' });
    expect(more.getAttribute('aria-expanded')).toBe('false');
    fireEvent.click(more);
    expect(within(healthy).getAllByRole('link')).toHaveLength(9);
    expect(document.activeElement.textContent).toBe(within(healthy).getAllByRole('link')[5].textContent);
  });

  it('a name two projects share shows its project, in the tag and in the square', () => {
    const data = { total_services: 3, services: [
      svc('notifier', { project_name: 'Fleet', critical_issues: 1 }),
      svc('notifier', { project_name: 'Shop' }),
      svc('web', { project_name: 'Shop' }),
    ] };
    const { unmount } = wrap(<ServicesPanel data={data} />);
    expect(screen.getByRole('link', { name: 'notifier · Fleet' }).getAttribute('href')).toBe('/dash/issues?component=notifier');
    expect(screen.getByRole('link', { name: 'notifier · Shop' })).toBeTruthy();
    // A name only one project has stays alone.
    expect(screen.getByRole('link', { name: 'web' })).toBeTruthy();
    unmount();
    wrap(<StatusCard data={data} />);
    expect(screen.getAllByRole('img').map((q) => [q.getAttribute('aria-label'), q.getAttribute('title')])).toEqual([
      ['notifier · Fleet', 'notifier · Fleet'], ['notifier · Shop', 'notifier · Shop'], ['web', 'web'],
    ]);
  });

  it('a shared name without the project from the server shows alone', () => {
    wrap(<ServicesPanel data={{ total_services: 2, services: [svc('notifier'), svc('notifier')] }} />);
    expect(screen.getAllByRole('link', { name: 'notifier' })).toHaveLength(2);
  });

  it('services the server did not list are counted, not named', () => {
    wrap(<ServicesPanel data={{ total_services: 15, services: [svc('a', { critical_issues: 1 }), svc('b')] }} />);
    expect(screen.getByText('Healthy (14)')).toBeTruthy();
    expect(screen.getByText('and 13 more').tagName).toBe('LI');
  });
});

describe('What caused them', () => {
  it('one stacked bar, most first, with the counts in the legend', () => {
    wrap(<CausesBar data={{ total_issues: 10, period_days: 30, breakdown: [
      { category: 'Code', count: 1 }, { category: 'Infrastructure', count: 8 }, { category: 'Dependency', count: 1 }, { category: 'Configuration', count: 0 },
    ] }} />);
    expect(document.querySelector('.glance-legend').textContent).toBe('8 Infrastructure1 Code1 Dependency');
    expect([...document.querySelectorAll('.glance-stack > span')].map((s) => s.style.flexGrow)).toEqual(['8', '1', '1']);
    expect(screen.getByRole('heading', { name: 'What caused them' })).toBeTruthy();
  });

  it('says so when there is nothing', () => {
    wrap(<CausesBar data={{ total_issues: 0, breakdown: [] }} />);
    expect(document.querySelector('.glance-stack')).toBeNull();
  });
});

describe('Recent analyses', () => {
  const feed = {
    total_analyses: 12,
    feed: [
      { batch_id: 'a', analyzed_at: '2026-11-24T03:23:00Z', summary: 'Commit 6e4e0512 rolled paymentservice.', critical_count: 0, warning_count: 1, environment: 'production', model_name: 'some-model' },
      { batch_id: 'b', analyzed_at: '2026-11-24T01:59:00Z', summary: 'The nightly-reindex job is running.', critical_count: 2, warning_count: 1, environment: 'production', model_name: 'some-model' },
      { batch_id: 'c', analyzed_at: '2026-11-24T01:00:00Z', summary: 'Nothing found.', critical_count: 0, warning_count: 0 },
    ],
  };
  it('when, the sentence on two lines, the severity; no model, no environment', () => {
    wrap(<AIAnalysisFeed data={feed} />);
    const items = [...document.querySelectorAll('.feed-item')];
    expect(items[0].querySelector('.feed-summary').className).toContain('glance-clamp-2');
    expect(items[0].querySelector('.feed-severity').textContent).toBe('WARNING');
    expect(items[1].querySelector('.feed-severity').textContent).toBe('CRITICAL');
    expect(items[2].querySelector('.feed-severity').textContent).toBe('');
    expect(items[0].querySelector('.feed-when').children).toHaveLength(2);
    expect(document.body.textContent).not.toContain('some-model');
    expect(document.body.textContent).not.toContain('production');
    expect(screen.getByRole('heading', { name: 'Recent analyses' })).toBeTruthy();
    expect(screen.getByText(/View all 12 analyses/)).toBeTruthy();
  });
});
