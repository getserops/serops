import { describe, it, expect, afterEach } from "vitest";
import i18n from "../../i18n";

// 1.5.5, C2: the page said lang="en" whatever the language shown.
describe("the page's lang attribute", () => {
  afterEach(async () => { await i18n.changeLanguage("en"); });

  it("is set at start", () => {
    expect(document.documentElement.getAttribute("lang")).toBe(String(i18n.resolvedLanguage).split("-")[0]);
  });

  it("follows every switch", async () => {
    await i18n.changeLanguage("fr");
    expect(document.documentElement.getAttribute("lang")).toBe("fr");
    await i18n.changeLanguage("en");
    expect(document.documentElement.getAttribute("lang")).toBe("en");
    await i18n.changeLanguage("fr-FR");
    expect(document.documentElement.getAttribute("lang")).toBe("fr");
  });
});
