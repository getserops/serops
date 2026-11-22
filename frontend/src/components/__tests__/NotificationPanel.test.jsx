import React from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';

// The real English strings, with {{values}} filled in, so the test reads
// what a person reads.
const translate = (dict) => (key, opts = {}) => {
  const text = key.split('.').reduce((o, k) => o?.[k], dict);
  if (typeof text !== 'string') return opts.defaultValue ?? key;
  return text.replace(/\{\{(\w+)\}\}/g, (_, name) => opts[name] ?? '');
};
vi.mock('react-i18next', () => ({ useTranslation: () => ({ t: translate(en) }) }));
vi.mock('../../services/notification.service', () => ({
  default: {
    getAllNotifications: vi.fn(), getReadNotifications: vi.fn(), getUnreadCount: vi.fn(),
    markAsRead: vi.fn(() => Promise.resolve({})), markAsUnread: vi.fn(() => Promise.resolve({})),
    deleteNotification: vi.fn(() => Promise.resolve({})), deleteAllNotifications: vi.fn(), markAllAsRead: vi.fn(),
  },
}));

import NotificationService from '../../services/notification.service';
import NotificationPanel from '../NotificationPanel';
import { groupEscalations, humanCode, notificationTitle, parseEscalation, parseIssueSubject } from '../../utils/notificationTitle';

const at = (minutesAgo) => new Date(Date.now() - minutesAgo * 60000).toISOString();
const NOTES = [
  { id: 4, subject: 'ESCALATION (Level 2): POD_CRASH in Shopfront', message: 'Issue unacknowledged for 30+ minutes. shippingservice is in CrashLoopBackOff.', is_read: false, created_at: at(5), notification_type: 'escalation', issue: 31, batch_id: 'b-1' },
  { id: 3, subject: 'ESCALATION (Level 1): POD_CRASH in Shopfront', message: 'Issue unacknowledged for 15+ minutes. shippingservice is in CrashLoopBackOff.', is_read: true, created_at: at(20), notification_type: 'escalation', issue: 31, batch_id: 'b-1' },
  { id: 2, subject: 'ESCALATION (Level 1): OOM_KILL in Fleet', message: 'Issue unacknowledged for 15+ minutes.', is_read: true, created_at: at(40), notification_type: 'escalation', issue: 32, batch_id: 'b-2' },
  { id: 1, subject: 'Your investigation of pricing is ready', message: 'Done.', is_read: true, created_at: at(90), notification_type: 'investigation_done', issue: null, batch_id: 'b-3' },
];

const open = async (onClose = vi.fn()) => {
  render(<MemoryRouter><NotificationPanel onClose={onClose} unreadCount={1} /></MemoryRouter>);
  await screen.findByText('Your investigation of pricing is ready');
  return onClose;
};

describe('notification titles and grouping', () => {
  it('turns a code into words and keeps known short names in capitals', () => {
    expect(humanCode('POD_CRASH')).toBe('Pod crash');
    expect(humanCode('OOM_KILL')).toBe('OOM kill');
    expect(humanCode('HIGH_CPU_USAGE')).toBe('High CPU usage');
    expect(humanCode('')).toBe('');
  });

  it('reads an escalation subject and leaves any other subject alone', () => {
    expect(parseEscalation('ESCALATION (Level 2): POD_CRASH in Shopfront')).toEqual({ level: 2, type: 'POD_CRASH', project: 'Shopfront' });
    expect(parseEscalation('SerOps Digest: 2 critical, 1 warning issues')).toBeNull();
    expect(notificationTitle(NOTES[0], translate(en))).toBe('Escalation level 2: Pod crash in Shopfront');
    expect(notificationTitle(NOTES[0], translate(fr))).toBe('Escalade niveau 2 : Pod crash dans Shopfront');
    expect(notificationTitle(NOTES[3], translate(en))).toBe('Your investigation of pricing is ready');
  });

  it('reads a new-issue subject in both forms the server writes', () => {
    expect(parseIssueSubject('[CRITICAL] POD_CRASH on shippingservice')).toEqual({ severity: 'CRITICAL', type: 'POD_CRASH', where: 'on', target: 'shippingservice' });
    const t = translate(en);
    expect(notificationTitle({ subject: '[CRITICAL] POD_CRASH on shippingservice' }, t)).toBe('Critical: Pod crash on shippingservice');
    expect(notificationTitle({ subject: 'WARNING: HIGH_CPU_USAGE in Fleet' }, t)).toBe('Warning: High CPU usage in Fleet');
    expect(notificationTitle({ subject: 'CRITICAL: OOM_KILL' }, t)).toBe('Critical: OOM kill');
    expect(notificationTitle({ subject: '[CRITICAL] SERVICE_UNAVAILABLE on fleet-redis' }, translate(fr))).toBe('Critique : Service unavailable sur fleet-redis');
    // Not a severity, not a code: left as written.
    expect(notificationTitle({ subject: 'Digest: 7 issues resolved, 3 open' }, t)).toBe('Digest: 7 issues resolved, 3 open');
    expect(notificationTitle({ subject: 'Investigation finished: Shopfront' }, t)).toBe('Investigation finished: Shopfront');
    expect(notificationTitle({ subject: 'NOTE: read this' }, t)).toBe('NOTE: read this');
  });

  it('shows one entry per issue at its highest level, unread while any level is unread', () => {
    const grouped = groupEscalations(NOTES);
    expect(grouped.map((n) => n.id)).toEqual([4, 2, 1]);
    expect(grouped[0].ids).toEqual([4, 3]);
    expect(grouped[0].is_read).toBe(false);
    // The order in which the levels arrive does not matter.
    const reversed = groupEscalations([NOTES[1], NOTES[0]]);
    expect(reversed).toHaveLength(1);
    expect(reversed[0].id).toBe(4);
    // Without an issue there is nothing to group on.
    expect(groupEscalations([{ ...NOTES[0], issue: null }, { ...NOTES[1], issue: null }])).toHaveLength(2);
  });
});

describe('NotificationPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    NotificationService.getAllNotifications.mockResolvedValue({ data: NOTES });
    NotificationService.getUnreadCount.mockResolvedValue({ data: { unread_count: 1 } });
  });

  it('is a named dialog, lists escalations in words and one per issue', async () => {
    await open();
    expect(screen.getByRole('dialog', { name: 'Notifications' })).toBeInTheDocument();
    expect(screen.getByText('Escalation level 2: Pod crash in Shopfront')).toBeInTheDocument();
    expect(screen.getByText('Escalation level 1: OOM kill in Fleet')).toBeInTheDocument();
    expect(screen.queryByText(/ESCALATION \(Level/)).toBeNull();
    expect(screen.queryByText(/level 1: Pod crash/)).toBeNull();
    expect(screen.getAllByRole('listitem')).toHaveLength(3);
  });

  it('closes on Escape and on a click outside, not on a click inside or on the bell', async () => {
    const onClose = await open();
    fireEvent.mouseDown(screen.getByText('Escalation level 2: Pod crash in Shopfront'));
    expect(onClose).not.toHaveBeenCalled();
    const bell = document.createElement('button');
    bell.setAttribute('data-notification-bell', '');
    document.body.appendChild(bell);
    fireEvent.mouseDown(bell);
    expect(onClose).not.toHaveBeenCalled();
    fireEvent.mouseDown(document.body);
    expect(onClose).toHaveBeenLastCalledWith('outside');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenLastCalledWith('escape');
    fireEvent.click(screen.getByRole('button', { name: 'Close' }));
    expect(onClose).toHaveBeenLastCalledWith('button');
    bell.remove();
  });

  it('deleting a grouped entry deletes every level of that issue', async () => {
    await open();
    fireEvent.click(screen.getAllByRole('button', { name: 'Delete notification' })[0]);
    await waitFor(() => expect(NotificationService.deleteNotification).toHaveBeenCalledTimes(2));
    expect(NotificationService.deleteNotification.mock.calls.map((c) => c[0])).toEqual([4, 3]);
    await waitFor(() => expect(screen.queryByText('Escalation level 2: Pod crash in Shopfront')).toBeNull());
    expect(screen.queryByText(/Pod crash/)).toBeNull();
  });

  it('the page variant is not a dialog and ignores Escape', async () => {
    const onClose = vi.fn();
    render(<MemoryRouter><NotificationPanel onClose={onClose} variant="page" /></MemoryRouter>);
    await screen.findByText('Your investigation of pricing is ready');
    expect(screen.queryByRole('dialog')).toBeNull();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).not.toHaveBeenCalled();
  });
});
