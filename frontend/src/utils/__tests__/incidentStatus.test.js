import { describe, it, expect } from 'vitest';
import { incidentStatus } from '../incidentStatus';

describe('incidentStatus', () => {
  it('says no issues when the analysis found none', () => {
    expect(incidentStatus([]).kind).toBe('none');
    expect(incidentStatus(undefined).kind).toBe('none');
  });

  it('is open while any issue is open and unacknowledged', () => {
    const s = incidentStatus([{ status: 'RESOLVED' }, { status: 'OPEN' }], 'CRITICAL');
    expect(s.kind).toBe('open');
    expect(s.klass).toBe('ds-chip-err');
    expect(incidentStatus([{ id: 1 }]).klass).toBe('ds-chip-warn');
  });

  it('is acknowledged only when open issues are all acknowledged', () => {
    expect(incidentStatus([{ status: 'OPEN', acknowledged_at: '2026-11-18T10:00:00Z' }]).kind).toBe('acknowledged');
  });

  it('is resolved, not acknowledged, when the issue is resolved', () => {
    const s = incidentStatus([{ status: 'RESOLVED' }]);
    expect(s.kind).toBe('resolved');
    expect(s.labelKey).toBe('detail.incident.statusResolved');
  });

  it('is muted when every issue is muted, resolved when some are', () => {
    expect(incidentStatus([{ status: 'MUTED' }, { status: 'muted' }]).kind).toBe('muted');
    expect(incidentStatus([{ status: 'MUTED' }, { status: 'RESOLVED' }]).kind).toBe('resolved');
  });
});
