// Why a batch exists and what Sentinel decided about it are two different
// things. The trigger is what created the batch (the schedule, an alert
// webhook, a user's investigation). Sentinel's decision is whether the window
// held anything new enough to send to the AI. They used to share one chip, so
// a scheduled run Sentinel let through read "ALERT" although no alert fired.

const TRIGGERS = {
  scheduled: { label: 'batchTrigger.trigger.scheduled', fallback: 'Scheduled', klass: 'ds-chip-neutral' },
  alert: { label: 'batchTrigger.trigger.alert', fallback: 'Alert received', klass: 'ds-chip-err' },
  manual: { label: 'batchTrigger.trigger.manual', fallback: 'Investigation', klass: 'ds-chip-brand' },
};

export const SENTINEL_REASON_FALLBACKS = {
  forced_periodic: 'Periodic health check',
  deployment_detected: 'New deployment',
  new_error_pattern: 'New error pattern',
  error_rate_spike: 'Error rate spike',
  memory_anomaly: 'Memory anomaly',
  cpu_anomaly: 'CPU anomaly',
  error_rate_escalating: 'Error rate escalating',
  first_batch: 'First batch',
  kubernetes_failure: 'Kubernetes restarts or unavailable pods',
  trace_latency_spike: 'Trace latency spike',
  trace_error_spike: 'Trace error spike',
};

/** What created the batch: 'scheduled' (default), 'alert' or 'manual'. */
export function batchTrigger(batch) {
  const key = batch?.trigger;
  const known = TRIGGERS[key] ? key : 'scheduled';
  return { key: known, ...TRIGGERS[known] };
}

/**
 * Sentinel's decision, in words a reader can act on. ``null`` when Sentinel
 * was not consulted (an investigation always runs the AI).
 */
export function sentinelOutcome(batch) {
  const decision = (batch?.sentinel_decision || '').toLowerCase();
  const reasons = Array.isArray(batch?.sentinel_triggers) ? batch.sentinel_triggers : [];
  if (decision === 'manual' || batch?.trigger === 'manual') return null;
  if (batch?.ai_skipped) {
    return { key: 'skipped', label: 'batchTrigger.sentinel.skipped', fallback: 'AI skipped: nothing new', klass: 'sentinel-quiet', reasons };
  }
  if (decision === 'quiet') {
    return { key: 'quietShadow', label: 'batchTrigger.sentinel.quietShadow', fallback: 'Nothing new, AI ran anyway (shadow mode)', klass: 'sentinel-quiet', reasons };
  }
  if (decision === 'alert') {
    const routine = reasons.length === 1 && reasons[0] === 'forced_periodic';
    return routine
      ? { key: 'routine', label: 'batchTrigger.sentinel.routine', fallback: 'Periodic check', klass: 'sentinel-routine', reasons }
      : { key: 'signals', label: 'batchTrigger.sentinel.signals', fallback: 'Signals found', klass: 'sentinel-alert', reasons };
  }
  if (decision === 'first') {
    return { key: 'first', label: 'batchTrigger.sentinel.first', fallback: 'First analysis', klass: 'sentinel-first', reasons };
  }
  return { key: 'shadow', label: 'batchTrigger.sentinel.shadow', fallback: 'Shadow mode', klass: 'sentinel-shadow', reasons };
}

/** Human labels for Sentinel's reasons, for a tooltip or chips. */
export function sentinelReasonLabels(reasons, t) {
  return (reasons || []).map((r) => {
    const fallback = SENTINEL_REASON_FALLBACKS[r] || r;
    return t ? t(`batchTrigger.reason.${r}`, fallback) : fallback;
  });
}
