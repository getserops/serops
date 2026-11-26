import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// Second phone and tablet review (1.5.5, Part C).
const read = (p) => readFileSync(resolve(__dirname, "..", p), "utf8");
const primitives = read("../styles/primitives.css");
const phoneBlock = (() => {
  const i = primitives.indexOf("Tables that turn into one card per row on phones");
  return primitives.slice(i, primitives.indexOf("\n}\n", i));
})();
const touchBlock = (() => {
  const i = primitives.indexOf("Touch devices: everything a finger presses");
  return primitives.slice(i, primitives.indexOf("\n}\n", i));
})();

describe("C1: a card that stands for one record opens on tap", () => {
  it("lets the record's link cover the card on a phone, controls above it", () => {
    expect(phoneBlock).toMatch(/\.table-stack \.ds-row-link::after \{[^}]*position: absolute; inset: 0;/);
    expect(phoneBlock).toMatch(/\.table-stack tr:has\(\.ds-row-link\) \{ position: relative;/);
    expect(phoneBlock).toMatch(/:is\(a, button, input, select, label, \[role="button"\], \.clickable-issue\):not\(\.ds-row-link\) \{ position: relative; z-index: 1; \}/);
  });

  it.each([
    ["Data.jsx", /to=\{`\/dash\/data\/details\/\$\{item\.id\}`\} className="view-btn ds-row-link"/],
    ["Traces.jsx", /to=\{`\/dash\/traces\/\$\{tr\.trace_id\}`\}\s*className="text-decoration-none ds-row-link"/],
    ["BatchTraces.jsx", /<Link to=\{tracePath\(span\)\} className="text-decoration-none ds-row-link">/],
  ])("marks the record's link in %s", (file, re) => {
    expect(read(file)).toMatch(re);
  });
});

describe("C5: the chat on a short phone screen", () => {
  it("lets the page scroll instead of cutting off the message box", () => {
    const css = read("ChatIssues.css");
    expect(css).toMatch(/@media \(max-width: 767px\) and \(max-height: 639px\) \{\s*:is\(html, :root\[data-theme\]\) \.chat-container-modern \{ height: auto; min-height: 0; \}/);
    // it comes after the rule that sets the screen-high card, so it wins
    expect(css.indexOf("max-height: 639px")).toBeGreaterThan(css.indexOf("height: calc(var(--visual-vh, 100dvh)"));
  });
});

describe("C6: notification actions on touch", () => {
  it("makes the icon buttons 44 px square", () => {
    expect(touchBlock).toMatch(/\.notification-icon-btn, \.notification-close-btn\) \{\s*min-width: var\(--tap-min\) !important;\s*min-height: var\(--tap-min\) !important;/);
  });
});

describe("C7: Traces cards on a phone", () => {
  const design = read("../styles/design.css");
  const block = (() => {
    const i = design.indexOf("Traces on a phone: a compact card");
    return design.slice(i, design.indexOf("\n}\n", i));
  })();

  it("puts the trace on three lines, column names hidden but for the spans", () => {
    expect(read("Traces.jsx")).toMatch(/className="align-middle table-stack traces-compact"/);
    expect(block).toMatch(/@media \(max-width: 767px\)/);
    expect(block).toMatch(/\.traces-compact tbody tr \{\s*display: flex !important;\s*flex-wrap: wrap;/);
    expect(block).toMatch(/\.traces-compact tbody tr > td::before \{ content: none; \}/);
    for (const cell of ["id", "service", "op", "duration", "spans", "status", "start"]) {
      expect(read("Traces.jsx")).toContain(`trace-cell-${cell}`);
      expect(block).toContain(`.trace-cell-${cell}`);
    }
  });
});

describe("C8: the Analyses table and the log table fit at 1280", () => {
  it("tightens the Analyses cells below 1440 only", () => {
    const css = read("Data.css");
    const i = css.indexOf("C8 (1.5.5)");
    const block = css.slice(i, css.indexOf("\n}\n", i));
    expect(block).toMatch(/@media \(min-width: 768px\) and \(max-width: 1439px\)/);
    expect(block).toMatch(/\.modern-table\.data-compact :is\(th, td\) \{ padding-left: var\(--space-3\); padding-right: var\(--space-3\); \}/);
  });

  it("lets a long log line break", () => {
    expect(read("Detail.css")).toMatch(/\.detail-logs-table td\.detail-log-message \{ overflow-wrap: anywhere; \}/);
  });
});

