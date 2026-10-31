// During an incident, an issue found by reviewing the code (scope CODE,
// severity INFO) is a note, not a suspect. The backend demotes such findings
// when the batch has a runtime issue; the analysis page lists them apart.
const upper = (v) => String(v || '').toUpperCase();

export const splitCodeNotes = (issues = []) => {
  const incident = issues.some((i) => upper(i.scope) !== 'CODE');
  if (!incident) return { issues, notes: [] };
  const isNote = (i) => upper(i.scope) === 'CODE' && upper(i.severity) === 'INFO';
  return { issues: issues.filter((i) => !isNote(i)), notes: issues.filter(isNote) };
};
