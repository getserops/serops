// The one place that turns a timestamp into text.
//
// Every date on screen follows the two settings of the user menu: the time
// zone and the language. Three shapes:
//   - absolute: "21 Nov 2026, 12:57:21 UTC" (detail views; always with the
//     zone, so a time is never ambiguous);
//   - relative: "2 days ago" (tables; put formatAbsolute() in the title);
//   - time only: "12:57:21" (when the day is clear from the context).
// Do not call toLocaleString / toLocaleDateString / toLocaleTimeString on a
// date anywhere else (see frontend/DESIGN.md).

const saved = () => {
  try {
    return JSON.parse(window.localStorage.getItem('seropsSettings') || '{}') || {};
  } catch {
    return {};
  }
};

/** The time zone picked in the user menu, else the browser's, else UTC. */
export const userTimeZone = () => {
  const zone = saved().timezone;
  if (zone) {
    try {
      new Intl.DateTimeFormat('en-US', { timeZone: zone });
      return zone;
    } catch { /* an unknown zone falls back to the browser's */ }
  }
  return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
};

/** The language picked in the user menu, as a locale. */
export const userLocale = () => {
  let language = null;
  try { language = window.localStorage.getItem('seropsLanguage'); } catch { /* no storage */ }
  language = language || saved().language || 'en';
  return String(language).toLowerCase().startsWith('fr') ? 'fr-FR' : 'en-GB';
};

/** A Date, or null for an empty or unreadable value. */
export const toDate = (value) => {
  if (value === null || value === undefined || value === '') return null;
  const date = value instanceof Date ? value : new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
};

const format = (value, options, fallback) => {
  const date = toDate(value);
  if (!date) return fallback;
  return new Intl.DateTimeFormat(userLocale(), { timeZone: userTimeZone(), ...options }).format(date);
};

/**
 * "9 Oct" for a calendar day given as "2026-10-09": a day, not an instant,
 * so no time zone moves it.
 */
export const formatCalendarDay = (value) => {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(value || '');
  if (!m) return value;
  return new Intl.DateTimeFormat(userLocale(), { timeZone: 'UTC', month: 'short', day: 'numeric' })
    .format(new Date(Date.UTC(+m[1], +m[2] - 1, +m[3])));
};

const DAY = { year: 'numeric', month: 'short', day: 'numeric' };
const CLOCK = { hour: '2-digit', minute: '2-digit', hourCycle: 'h23' };

/** "21 Nov 2026, 12:57:21 UTC". `seconds: false` drops the seconds, `zone: false` the zone. */
export const formatAbsolute = (value, { seconds = true, zone = true, fallback = '—' } = {}) => format(value, {
  ...DAY, ...CLOCK,
  ...(seconds ? { second: '2-digit' } : {}),
  ...(zone ? { timeZoneName: 'short' } : {}),
}, fallback);

/** "21 Nov 2026". */
export const formatDate = (value, { fallback = '—' } = {}) => format(value, DAY, fallback);

/** "21 Nov" (chart axes, compact lists). */
export const formatDayMonth = (value, { fallback = '—' } = {}) => format(value, { month: 'short', day: 'numeric' }, fallback);

/** "November 2026". */
export const formatMonthYear = (value, { fallback = '—', utc = false } = {}) => format(value, { month: 'long', year: 'numeric', ...(utc ? { timeZone: 'UTC' } : {}) }, fallback);

/** "12:57:21"; `seconds: false` gives "12:57", `zone: true` adds the zone. */
export const formatTime = (value, { seconds = true, zone = false, fallback = '—' } = {}) => format(value, {
  ...CLOCK,
  ...(seconds ? { second: '2-digit' } : {}),
  ...(zone ? { timeZoneName: 'short' } : {}),
}, fallback);

/** The short name of the user's zone at that moment: "UTC", "CET", "GMT+9". */
export const zoneLabel = (value = new Date()) => {
  const date = toDate(value) || new Date();
  const parts = new Intl.DateTimeFormat(userLocale(), { timeZone: userTimeZone(), timeZoneName: 'short' }).formatToParts(date);
  return parts.find((part) => part.type === 'timeZoneName')?.value || userTimeZone();
};

const STEPS = [
  ['year', 365 * 86400],
  ['month', 30 * 86400],
  ['day', 86400],
  ['hour', 3600],
  ['minute', 60],
];

/**
 * "2 days ago", "in 3 hours", "now": one style everywhere, in the user's
 * language. Whole units, rounded down, like a clock that has not ticked yet.
 */
export const formatRelative = (value, { now = Date.now(), fallback = '—' } = {}) => {
  const date = toDate(value);
  if (!date) return fallback;
  const seconds = Math.round((date.getTime() - now) / 1000);
  const size = Math.abs(seconds);
  const relative = new Intl.RelativeTimeFormat(userLocale(), { numeric: 'auto' });
  for (const [unit, length] of STEPS) {
    if (size >= length) {
      const count = Math.floor(size / length) * Math.sign(seconds);
      return new Intl.RelativeTimeFormat(userLocale(), { numeric: 'always' }).format(count, unit);
    }
  }
  return relative.format(0, 'second');
};
