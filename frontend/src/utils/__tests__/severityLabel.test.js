import { describe, it, expect } from "vitest";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, resolve } from "node:path";
import { severityLabel, confidenceLabel } from "../severityLabel";

// 1.5.4: the severity chip read "CRITICAL" in the French interface.
describe("severityLabel", () => {
  it("gives the severity in French, in capitals", async () => {
    const { default: i18n } = await import("../../i18n");
    await i18n.changeLanguage("fr");
    try {
      const t = i18n.t.bind(i18n);
      expect(severityLabel(t, "CRITICAL")).toBe("CRITIQUE");
      expect(severityLabel(t, "WARNING")).toBe("AVERTISSEMENT");
      expect(severityLabel(t, "high")).toBe("ÉLEVÉ");
      expect(severityLabel(t, "ERROR")).toBe("ERREUR");
      expect(severityLabel(t, "FATAL")).toBe("FATAL");
      expect(severityLabel(t, "")).toBe("");
      expect(severityLabel(t, null)).toBe("");
    } finally {
      await i18n.changeLanguage("en");
    }
  });

  it("keeps the English chips as they were", async () => {
    const { default: i18n } = await import("../../i18n");
    await i18n.changeLanguage("en");
    const t = i18n.t.bind(i18n);
    expect(severityLabel(t, "CRITICAL")).toBe("CRITICAL");
    expect(severityLabel(t, "info")).toBe("INFO");
    expect(severityLabel(t, "DEBUG")).toBe("DEBUG");
  });
});

// No component writes a severity straight into the page.
describe("severity chips", () => {
  const root = resolve(__dirname, "../../components");
  const files = [];
  const walk = (d) => readdirSync(d).forEach((n) => {
    const p = join(d, n);
    if (statSync(p).isDirectory()) { if (n !== "__tests__") walk(p); } else if (p.endsWith(".jsx")) files.push(p);
  });
  walk(root);

  it("go through severityLabel or SeverityChip", () => {
    const raw = /(>\s*\{[\w?.]*\.severity\}\s*<)|(^\s*\{[\w?.]*\.severity\}\s*$)|(\{\(?[\w?.]*\.(severity|type)[^}]*\.toUpperCase\(\)\})/m;
    const offenders = files.filter((f) => raw.test(readFileSync(f, "utf8"))).map((f) => f.slice(root.length + 1));
    expect(offenders).toEqual([]);
  });
});

// 1.5.4: the confidence word of the analysis page read "High" in French.
describe("confidenceLabel", () => {
  it("gives the confidence in French, agreeing with \"Confiance\"", async () => {
    const { default: i18n } = await import("../../i18n");
    await i18n.changeLanguage("fr");
    try {
      const t = i18n.t.bind(i18n);
      expect(confidenceLabel(t, "HIGH", "High")).toBe("Élevée");
      expect(confidenceLabel(t, "MEDIUM", "Medium")).toBe("Moyenne");
      expect(confidenceLabel(t, "low", "Low")).toBe("Faible");
      expect(confidenceLabel(t, "UNKNOWN", "Unknown")).toBe("Unknown");
    } finally {
      await i18n.changeLanguage("en");
    }
  });

  it("keeps the English words the server sends", async () => {
    const { default: i18n } = await import("../../i18n");
    await i18n.changeLanguage("en");
    const t = i18n.t.bind(i18n);
    expect(confidenceLabel(t, "HIGH", "High")).toBe("High");
    expect(confidenceLabel(t, "MEDIUM")).toBe("Medium");
  });
});

describe("the analysis page", () => {
  it("shows the confidence through confidenceLabel", () => {
    const src = readFileSync(resolve(__dirname, "../../components/Detail.jsx"), "utf8");
    expect(src).not.toMatch(/\{primary\.confidence_display \|\| confidence\}/);
    expect(src.match(/confidenceLabel\(t, confidence, primary\.confidence_display\)/g)).toHaveLength(2);
  });
});
