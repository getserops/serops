// Time-window helpers for the Investigate form. Pure functions, so the
// prefill rules ("analyze this deploy", "re-run") are testable on their own.

export const MINUTE = 60 * 1000;

export const PRESETS = [
  { key: "15m", minutes: 15 },
  { key: "30m", minutes: 30 },
  { key: "1h", minutes: 60 },
  { key: "3h", minutes: 180 },
];

// <input type="datetime-local"> speaks local wall-clock time without a zone.
export function toLocalInput(date) {
  const pad = (n) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function fromLocalInput(value) {
  const date = value ? new Date(value) : null;
  return date && !Number.isNaN(date.getTime()) ? date : null;
}

// Fit a window into the limits the API enforces: it ends no later than now,
// lasts between minMinutes and maxHours, and keeps its end where possible.
export function clampWindow(start, end, { minMinutes = 5, maxHours = 6 } = {}, now = new Date()) {
  let e = end > now ? now : end;
  let s = start;
  if (e - s > maxHours * 60 * MINUTE) s = new Date(e - maxHours * 60 * MINUTE);
  if (e - s < minMinutes * MINUTE) s = new Date(e - minMinutes * MINUTE);
  return { start: s, end: e };
}

// "Analyze this deploy": five minutes before it to thirty after.
export function deployWindow(deployedAt, limits, now = new Date()) {
  const at = new Date(deployedAt);
  return clampWindow(new Date(at - 5 * MINUTE), new Date(at.getTime() + 30 * MINUTE), limits, now);
}

export function validateWindow(start, end, { minMinutes = 5, maxHours = 6, maxLookbackDays = 30 } = {}, now = new Date()) {
  if (!start || !end) return "invalid";
  if (end - now > MINUTE) return "future";
  if (end - start < minMinutes * MINUTE) return "tooShort";
  if (end - start > maxHours * 60 * MINUTE) return "tooLong";
  if (now - start > maxLookbackDays * 24 * 60 * MINUTE) return "tooOld";
  return null;
}
