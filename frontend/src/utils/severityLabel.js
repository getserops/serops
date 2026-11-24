// A severity or log level in the user's language, in capitals as the chips
// have always shown it ("CRITICAL", "CRITIQUE"). The words come from the
// existing issues.* keys; an unknown level (FATAL, DEBUG…) is shown as sent.
const KNOWN = new Set(["critical", "high", "medium", "low", "warning", "info", "error"]);

export function severityLabel(t, value) {
  const raw = String(value ?? "").trim();
  if (!raw) return "";
  const key = raw.toLowerCase();
  const label = KNOWN.has(key) ? t(`issues.${key}`, { defaultValue: raw }) : raw;
  return String(label).toUpperCase();
}

// How sure the AI is (HIGH, MEDIUM, LOW), in the user's language, written as
// the server words it ("High"). French agrees with "Confiance": "Élevée".
const CONFIDENCE = new Set(["high", "medium", "low"]);

export function confidenceLabel(t, value, fallback) {
  const key = String(value ?? "").trim().toLowerCase();
  if (CONFIDENCE.has(key)) return t(`detail.incident.confidenceLevel.${key}`, { defaultValue: fallback || value });
  return fallback || String(value ?? "");
}
