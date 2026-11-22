// What the notifications panel shows for a stored notification. The server
// writes escalations as "ESCALATION (Level 2): POD_CRASH in Shopfront": a
// raw code, and one notification per level for the same issue. Display only;
// nothing stored is changed.

const ESCALATION = /^ESCALATION \(Level (\d+)\):\s*([A-Za-z0-9_]+) in (.+)$/;

// "POD_CRASH" -> "Pod crash". Short all-capital words that are names stay
// as they are ("OOM kill", "CPU throttling", "HTTP 5xx").
const KEEP = new Set(['OOM', 'CPU', 'HTTP', 'DNS', 'TLS', 'SSL', 'API', 'DB', 'IO', 'CI', 'CD', 'SQL', 'JVM', 'GC', 'MTU', 'TCP', 'UDP', 'URL', 'K8S']);
export const humanCode = (code) => {
  const words = String(code || '').split(/[_\s]+/).filter(Boolean)
    .map((w) => (KEEP.has(w.toUpperCase()) ? w.toUpperCase() : w.toLowerCase()));
  if (!words.length) return '';
  if (!KEEP.has(words[0])) words[0] = words[0][0].toUpperCase() + words[0].slice(1);
  return words.join(' ');
};

export const parseEscalation = (subject) => {
  const m = ESCALATION.exec(String(subject || '').trim());
  return m ? { level: Number(m[1]), type: m[2], project: m[3].trim() } : null;
};

// "[CRITICAL] POD_CRASH on shippingservice" and "CRITICAL: POD_CRASH in
// Shopfront": a new issue, named by its severity and its type code.
const ISSUE = /^(?:\[([A-Z]+)\]|([A-Z]+):)\s*([A-Z][A-Z0-9_]+)(?: (on|in) (.+))?$/;
const SEVERITIES = new Set(['CRITICAL', 'HIGH', 'WARNING', 'MEDIUM', 'LOW', 'INFO']);
export const parseIssueSubject = (subject) => {
  const m = ISSUE.exec(String(subject || '').trim());
  if (!m) return null;
  const severity = m[1] || m[2];
  if (!SEVERITIES.has(severity)) return null;
  return { severity, type: m[3], where: m[4] || null, target: m[5] ? m[5].trim() : null };
};

const issueName = (type, t) => t(`notifications.panel.issueTypes.${type}`, { defaultValue: humanCode(type) });

// The title to show: escalations and new issues in words and translated,
// anything else as the server wrote it.
export const notificationTitle = (note, t) => {
  const subject = note?.subject || '';
  const esc = parseEscalation(subject);
  if (esc) {
    return t('notifications.panel.escalationTitle', { level: esc.level, issue: issueName(esc.type, t), project: esc.project });
  }
  const found = parseIssueSubject(subject);
  if (found) {
    const values = {
      severity: t(`notifications.panel.severities.${found.severity}`, { defaultValue: humanCode(found.severity) }),
      issue: issueName(found.type, t),
      target: found.target,
    };
    if (found.where === 'on') return t('notifications.panel.issueOnTitle', values);
    if (found.where === 'in') return t('notifications.panel.issueInTitle', values);
    return t('notifications.panel.issueTitle', values);
  }
  return subject;
};

// One entry per issue for escalations: the highest level (the newest of
// that level), unread while any of its notifications is unread. `ids` holds
// every notification the entry stands for, so that marking it read or
// deleting it acts on all of them. Other notifications pass through, each
// with its own id. The order of the list is kept (first appearance).
export const groupEscalations = (notes) => {
  const out = [];
  const byIssue = new Map();
  for (const note of notes || []) {
    const esc = note.issue != null ? parseEscalation(note.subject) : null;
    if (!esc) { out.push({ ...note, ids: [note.id] }); continue; }
    const at = byIssue.get(note.issue);
    if (at === undefined) {
      byIssue.set(note.issue, out.length);
      out.push({ ...note, ids: [note.id], level: esc.level });
      continue;
    }
    const kept = out[at];
    const ids = [...kept.ids, note.id];
    const is_read = kept.is_read && note.is_read;
    const higher = esc.level > kept.level
      || (esc.level === kept.level && new Date(note.created_at) > new Date(kept.created_at));
    out[at] = higher ? { ...note, ids, is_read, level: esc.level } : { ...kept, ids, is_read };
  }
  return out;
};
