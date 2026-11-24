import React from "react";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, it, expect, vi } from "vitest";
import { render, screen } from "@testing-library/react";

const pies = [];
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children, width, height }) => (
    <div data-testid="gauge-box" data-width={width} data-height={height}>{children}</div>
  ),
  PieChart: ({ children, margin }) => <div data-testid="gauge-chart" data-margin={JSON.stringify(margin)}>{children}</div>,
  Pie: (props) => { pies.push(props); return <div>{props.children}</div>; },
  Cell: ({ fill }) => <span data-testid="gauge-cell" data-fill={fill} />,
}));
vi.mock("react-i18next", () => ({ useTranslation: () => ({ t: (k, o) => o?.defaultValue ?? k }) }));

import HealthScoreCard, { GAUGE, GAUGE_TRACK } from "../HealthScoreCard";

const css = readFileSync(resolve(__dirname, "../Dashboard.css"), "utf8");

describe("System Health gauge", () => {
  it.each([[96, "healthy"], [72, "warning"], [31, "critical"]])(
    "draws the whole half-circle inside its box (score %i, %s)",
    (score, status) => {
      pies.length = 0;
      render(<HealthScoreCard score={score} status={status} loading={false} />);
      const box = screen.getByTestId("gauge-box");
      const w = Number(box.dataset.width);
      const h = Number(box.dataset.height);
      expect(JSON.parse(screen.getByTestId("gauge-chart").dataset.margin)).toEqual({ top: 0, right: 0, bottom: 0, left: 0 });
      const p = pies.at(-1);
      expect(typeof p.cx).toBe("number");
      expect(typeof p.cy).toBe("number");
      expect(p.cy - p.outerRadius).toBeGreaterThanOrEqual(0);
      expect(p.cy).toBeLessThan(h);
      expect(p.cx - p.outerRadius).toBeGreaterThanOrEqual(0);
      expect(p.cx + p.outerRadius).toBeLessThanOrEqual(w);
      expect(screen.getByText(`${score}%`)).toBeTruthy();
    },
  );

  it("gives the unfilled track a token that shows on the card in both themes", () => {
    render(<HealthScoreCard score={40} status="critical" loading={false} />);
    const fills = screen.getAllByTestId("gauge-cell").map((c) => c.dataset.fill);
    expect(fills[1]).toBe(GAUGE_TRACK);
    expect(GAUGE_TRACK).toBe("var(--border-hover)");
  });

  it("keeps the chart box the size of the gauge, with no negative margin", () => {
    const rule = css.match(/\.health-chart \{[^}]*\}/)[0];
    expect(rule).not.toMatch(/margin-top:\s*-/);
    expect(rule).toContain(`width: ${GAUGE.width}px`);
    expect(rule).toContain(`height: ${GAUGE.height}px`);
    expect(css.match(/\.health-score-overlay \{[^}]*\}/)[0]).not.toMatch(/bottom:\s*-/);
  });
});
