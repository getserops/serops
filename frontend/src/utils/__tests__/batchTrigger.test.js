import { describe, it, expect } from 'vitest';
import { batchTrigger, sentinelOutcome, sentinelReasonLabels } from '../batchTrigger';
import en from '../../locales/en.json';
import fr from '../../locales/fr.json';

describe('batchTrigger', () => {
  it('names what created the batch', () => {
    expect(batchTrigger({ trigger: 'scheduled' }).fallback).toBe('Scheduled');
    expect(batchTrigger({ trigger: 'alert' }).fallback).toBe('Alert received');
    expect(batchTrigger({ trigger: 'manual' }).fallback).toBe('Investigation');
  });

  it('treats a missing or unknown trigger as scheduled', () => {
    expect(batchTrigger({}).key).toBe('scheduled');
    expect(batchTrigger(null).key).toBe('scheduled');
    expect(batchTrigger({ trigger: 'webhook?' }).key).toBe('scheduled');
  });
});

describe('sentinelOutcome', () => {
  it('a scheduled run Sentinel let through is not an alert', () => {
    const b = { trigger: 'scheduled', sentinel_decision: 'alert', sentinel_triggers: ['error_rate_spike'] };
    expect(batchTrigger(b).fallback).toBe('Scheduled');
    expect(sentinelOutcome(b).fallback).toBe('Signals found');
  });

  it('an alert-triggered run keeps its own Sentinel decision', () => {
    const b = { trigger: 'alert', sentinel_decision: 'quiet', ai_skipped: false };
    expect(batchTrigger(b).fallback).toBe('Alert received');
    expect(sentinelOutcome(b).key).toBe('quietShadow');
  });

  it('says when the AI was skipped', () => {
    expect(sentinelOutcome({ sentinel_decision: 'quiet', ai_skipped: true }).key).toBe('skipped');
  });

  it('calls a periodic-only pass a periodic check', () => {
    expect(sentinelOutcome({ sentinel_decision: 'alert', sentinel_triggers: ['forced_periodic'] }).key).toBe('routine');
    expect(sentinelOutcome({ sentinel_decision: 'alert', sentinel_triggers: ['forced_periodic', 'cpu_anomaly'] }).key).toBe('signals');
  });

  it('is not consulted for an investigation', () => {
    expect(sentinelOutcome({ trigger: 'manual', sentinel_decision: 'manual' })).toBeNull();
    expect(sentinelOutcome({ sentinel_decision: 'manual' })).toBeNull();
  });

  it('maps first and the shadow default', () => {
    expect(sentinelOutcome({ sentinel_decision: 'first' }).key).toBe('first');
    expect(sentinelOutcome({ sentinel_decision: 'shadow' }).key).toBe('shadow');
    expect(sentinelOutcome({}).key).toBe('shadow');
  });
});

describe('labels', () => {
  it('turns reason codes into words', () => {
    expect(sentinelReasonLabels(['deployment_detected', 'unknown_code'])).toEqual(['New deployment', 'unknown_code']);
  });

  it('every label exists in English and French', () => {
    const outcomes = [
      { sentinel_decision: 'quiet', ai_skipped: true }, { sentinel_decision: 'quiet' },
      { sentinel_decision: 'alert', sentinel_triggers: ['forced_periodic'] }, { sentinel_decision: 'alert' },
      { sentinel_decision: 'first' }, { sentinel_decision: 'shadow' },
    ].map(sentinelOutcome);
    const keys = [
      ...['scheduled', 'alert', 'manual'].map((k) => batchTrigger({ trigger: k }).label),
      ...outcomes.map((o) => o.label),
      'batchTrigger.sentinel.notConsulted', 'batchTrigger.sentinel.notConsultedHint',
    ];
    const get = (obj, path) => path.split('.').reduce((o, k) => (o ? o[k] : undefined), obj);
    for (const k of keys) {
      expect(get(en, k), `en ${k}`).toBeTruthy();
      expect(get(fr, k), `fr ${k}`).toBeTruthy();
    }
    for (const r of Object.keys(en.batchTrigger.reason)) expect(fr.batchTrigger.reason[r], r).toBeTruthy();
  });
});
