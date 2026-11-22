import { describe, it, expect } from 'vitest';
import { needsAction, statusTone, severityTone, statusChipClass, severityChipClass, severityAccent, severityTextColor } from '../tones';

describe('statusTone: one mapping on every page', () => {
  it.each([
    ['OPEN', 'brand'], ['open', 'brand'], ['ACKNOWLEDGED', 'neutral'], ['RESOLVED', 'ok'], ['MUTED', 'neutral'],
    ['REGRESSED', 'err'], ['', 'neutral'], [undefined, 'neutral'], ['SOMETHING', 'neutral'],
  ])('%s is %s', (status, tone) => expect(statusTone(status)).toBe(tone));

  it('never uses amber for a status', () => {
    for (const s of ['OPEN', 'ACKNOWLEDGED', 'RESOLVED', 'MUTED', 'REGRESSED']) expect(statusTone(s)).not.toBe('warn');
  });
});

describe('severityTone: colour only while somebody has to act', () => {
  it.each([
    ['CRITICAL', 'err'], ['HIGH', 'err'], ['WARNING', 'warn'], ['MEDIUM', 'warn'], ['INFO', 'neutral'], ['LOW', 'neutral'],
    ['critical', 'err'], [null, 'neutral'],
  ])('an open %s issue is %s', (severity, tone) => {
    expect(severityTone(severity, 'OPEN')).toBe(tone);
    expect(severityTone(severity)).toBe(tone);
    expect(severityTone(severity, 'ACKNOWLEDGED')).toBe(tone);
  });

  it.each(['RESOLVED', 'MUTED', 'resolved'])('a %s critical issue is outlined, not red', (status) => {
    expect(severityTone('CRITICAL', status)).toBe('outline');
    expect(severityChipClass('CRITICAL', status)).toBe('ds-chip ds-chip-outline');
    expect(severityAccent('CRITICAL', status)).toBe('var(--border-hover)');
    expect(severityTextColor('CRITICAL', status)).toBe('var(--text-tertiary)');
  });

  it('red and amber accents for open issues', () => {
    expect(severityAccent('CRITICAL', 'OPEN')).toBe('var(--tone-red-solid)');
    expect(severityAccent('WARNING', 'OPEN')).toBe('var(--tone-amber-text)');
    expect(severityAccent('INFO', 'OPEN')).toBe('var(--border-hover)');
    expect(severityTextColor('CRITICAL')).toBe('var(--tone-red-text)');
  });
});

describe('needsAction and chip classes', () => {
  it('open, acknowledged, regressed and "no status" need action; resolved and muted do not', () => {
    expect(['OPEN', 'ACKNOWLEDGED', 'REGRESSED', '', undefined].map(needsAction)).toEqual([true, true, true, true, true]);
    expect(['RESOLVED', 'MUTED'].map(needsAction)).toEqual([false, false]);
  });
  it('builds ds-chip classes', () => {
    expect(statusChipClass('OPEN')).toBe('ds-chip ds-dot ds-chip-brand');
    expect(statusChipClass('RESOLVED')).toBe('ds-chip ds-dot ds-chip-ok');
    expect(severityChipClass('CRITICAL', 'OPEN')).toBe('ds-chip ds-chip-err');
  });
});
