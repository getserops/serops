import { describe, it, expect, beforeEach } from 'vitest';
import {
  userTimeZone, userLocale, toDate, formatAbsolute, formatDate, formatDayMonth, formatMonthYear, formatTime,
  zoneLabel, formatRelative,
} from '../dates';

// The user menu stores the zone in "seropsSettings" and the language in
// "seropsLanguage" (Navbar.jsx).
const prefs = ({ timezone, language } = {}) => {
  window.localStorage.getItem.mockImplementation((key) => {
    if (key === 'seropsSettings') return JSON.stringify(timezone ? { timezone } : {});
    if (key === 'seropsLanguage') return language || null;
    return null;
  });
};
const T = '2026-11-21T00:57:21Z';

describe('dates: the user settings', () => {
  beforeEach(() => prefs());

  it('uses the time zone of the user menu', () => {
    prefs({ timezone: 'Asia/Tokyo' });
    expect(userTimeZone()).toBe('Asia/Tokyo');
    expect(formatAbsolute(T)).toBe('21 Nov 2026, 09:57:21 GMT+9');
  });

  it('falls back to the browser zone when none or an unknown one is saved', () => {
    const browser = Intl.DateTimeFormat().resolvedOptions().timeZone;
    expect(userTimeZone()).toBe(browser);
    prefs({ timezone: 'Mars/Olympus' });
    expect(userTimeZone()).toBe(browser);
  });

  it('uses the language of the user menu', () => {
    expect(userLocale()).toBe('en-GB');
    prefs({ timezone: 'UTC', language: 'fr' });
    expect(userLocale()).toBe('fr-FR');
    expect(formatAbsolute(T)).toBe('21 nov. 2026, 00:57:21 UTC');
    expect(formatRelative('2026-11-19T00:57:21Z', { now: Date.parse(T) })).toBe('il y a 2 jours');
  });

  it('survives unreadable settings', () => {
    window.localStorage.getItem.mockImplementation(() => 'not json');
    expect(() => formatAbsolute(T)).not.toThrow();
  });
});

describe('dates: shapes', () => {
  beforeEach(() => prefs({ timezone: 'UTC' }));

  it('absolute time always carries the zone unless asked otherwise', () => {
    expect(formatAbsolute(T)).toBe('21 Nov 2026, 00:57:21 UTC');
    expect(formatAbsolute(T, { seconds: false })).toBe('21 Nov 2026, 00:57 UTC');
    expect(formatAbsolute(T, { zone: false })).toBe('21 Nov 2026, 00:57:21');
  });

  it('a zone east of UTC changes the day', () => {
    prefs({ timezone: 'Europe/Paris' });
    expect(formatAbsolute('2026-11-21T23:30:00Z')).toBe('22 Nov 2026, 00:30:00 CET');
    expect(zoneLabel('2026-11-21T23:30:00Z')).toBe('CET');
    expect(zoneLabel('2026-07-01T12:00:00Z')).toBe('CEST');
  });

  it('date, day and month, month and year, time only', () => {
    expect(formatDate(T)).toBe('21 Nov 2026');
    expect(formatDayMonth(T)).toBe('21 Nov');
    expect(formatMonthYear(T)).toBe('November 2026');
    expect(formatTime(T)).toBe('00:57:21');
    expect(formatTime(T, { seconds: false })).toBe('00:57');
    expect(formatTime(T, { zone: true })).toBe('00:57:21 UTC');
    expect(zoneLabel(T)).toBe('UTC');
  });

  it('accepts a Date, a number and a string; an empty or bad value gives the fallback', () => {
    expect(formatDate(new Date(T))).toBe('21 Nov 2026');
    expect(formatDate(Date.parse(T))).toBe('21 Nov 2026');
    expect(toDate('nonsense')).toBeNull();
    for (const bad of [null, undefined, '', 'nonsense']) {
      expect(formatAbsolute(bad)).toBe('—');
      expect(formatRelative(bad)).toBe('—');
    }
    expect(formatAbsolute(null, { fallback: 'Unknown' })).toBe('Unknown');
  });
});

describe('dates: relative time, one style', () => {
  beforeEach(() => prefs({ timezone: 'UTC' }));
  const now = Date.parse(T);
  const ago = (seconds) => formatRelative(now - seconds * 1000, { now });

  it('writes the unit out: "2 days ago", never "2d ago"', () => {
    expect(ago(0)).toBe('now');
    expect(ago(30)).toBe('now');
    expect(ago(60)).toBe('1 minute ago');
    expect(ago(59 * 60)).toBe('59 minutes ago');
    expect(ago(3600)).toBe('1 hour ago');
    expect(ago(23 * 3600 + 3599)).toBe('23 hours ago');
    expect(ago(86400)).toBe('1 day ago');
    expect(ago(2 * 86400 + 5)).toBe('2 days ago');
    expect(ago(45 * 86400)).toBe('1 month ago');
    expect(ago(800 * 86400)).toBe('2 years ago');
  });

  it('handles the future', () => {
    expect(formatRelative(now + 3 * 3600 * 1000, { now })).toBe('in 3 hours');
  });
});
