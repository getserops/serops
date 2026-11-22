// One place that decides the colour of a status or a severity.
// Rules (frontend/DESIGN.md, "Colour usage"):
//   - red means "needs action now": only an issue that is open,
//     acknowledged or regressed shows its severity in colour;
//   - a resolved or muted issue keeps its severity as an outlined neutral
//     chip, with no red accent;
//   - status: open = brand, acknowledged = neutral, resolved = green,
//     muted = gray, regressed = red (it is open again);
//   - severity: critical and high = red, warning and medium = amber,
//     info and low = neutral.
// Tones are the names of the ds-chip-* classes.

const up = (value) => String(value || '').toUpperCase();

/** An issue with no status is treated as open (what the API means by it). */
export const needsAction = (status) => ['', 'OPEN', 'ACKNOWLEDGED', 'REGRESSED'].includes(up(status));

const STATUS = { OPEN: 'brand', ACKNOWLEDGED: 'neutral', RESOLVED: 'ok', MUTED: 'neutral', REGRESSED: 'err' };
export const statusTone = (status) => STATUS[up(status)] || 'neutral';

const SEVERITY = { CRITICAL: 'err', HIGH: 'err', WARNING: 'warn', MEDIUM: 'warn', INFO: 'neutral', LOW: 'neutral' };
/** Pass the issue's status when there is one; without it the issue counts as open. */
export const severityTone = (severity, status) => (needsAction(status) ? SEVERITY[up(severity)] || 'neutral' : 'outline');

export const statusChipClass = (status) => `ds-chip ds-dot ds-chip-${statusTone(status)}`;
export const severityChipClass = (severity, status) => `ds-chip ds-chip-${severityTone(severity, status)}`;

const ACCENT = { err: 'var(--tone-red-solid)', warn: 'var(--tone-amber-text)' };
/** The 3px accent on the left of a row or card; neutral once nobody has to act. */
export const severityAccent = (severity, status) => ACCENT[severityTone(severity, status)] || 'var(--border-hover)';

const TEXT = { err: 'var(--tone-red-text)', warn: 'var(--tone-amber-text)' };
/** Colour of a severity icon or figure. */
export const severityTextColor = (severity, status) => TEXT[severityTone(severity, status)] || 'var(--text-tertiary)';
