// The status shown in an analysis header, from the issues it found.
//
// It used to be "Acknowledged" whenever no issue was open and unacknowledged,
// so an analysis whose issue was resolved or muted read "Acknowledged" next
// to an issue row saying "Resolved".
//
// Order: anything still open decides first; with nothing open, the header
// says how the issues were closed.
export function incidentStatus(issues, primarySeverity = '') {
  const list = Array.isArray(issues) ? issues : [];
  if (list.length === 0) return { kind: 'none', klass: 'ds-chip-ok', labelKey: 'detail.incident.statusNoIssues' };
  const statusOf = (i) => String(i.status || 'OPEN').toUpperCase();
  const open = list.filter((i) => statusOf(i) === 'OPEN');
  if (open.some((i) => !i.acknowledged_at)) {
    return {
      kind: 'open',
      klass: String(primarySeverity).toUpperCase() === 'CRITICAL' ? 'ds-chip-err' : 'ds-chip-warn',
      labelKey: 'detail.incident.statusOpen',
    };
  }
  if (open.length > 0) return { kind: 'acknowledged', klass: 'ds-chip-info', labelKey: 'detail.incident.statusAcknowledged' };
  if (list.every((i) => statusOf(i) === 'MUTED')) return { kind: 'muted', klass: 'ds-chip-neutral', labelKey: 'detail.incident.statusMuted' };
  return { kind: 'resolved', klass: 'ds-chip-ok', labelKey: 'detail.incident.statusResolved' };
}
