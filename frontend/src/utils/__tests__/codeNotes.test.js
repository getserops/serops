import { describe, it, expect } from 'vitest';
import { splitCodeNotes } from '../codeNotes';

const incident = { id: 1, scope: 'SERVICE', severity: 'CRITICAL' };
const note = { id: 2, scope: 'CODE', severity: 'INFO' };
const codeWarning = { id: 3, scope: 'CODE', severity: 'WARNING' };

describe('code-review notes', () => {
  it('are set apart during an incident', () => {
    expect(splitCodeNotes([incident, note])).toEqual({ issues: [incident], notes: [note] });
  });

  it('stay issues when there is no incident (a code-only review)', () => {
    expect(splitCodeNotes([note, codeWarning])).toEqual({ issues: [note, codeWarning], notes: [] });
  });

  it('only INFO findings are notes', () => {
    expect(splitCodeNotes([incident, codeWarning]).notes).toEqual([]);
  });
});
