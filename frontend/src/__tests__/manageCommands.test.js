import { describe, it, expect } from "vitest";
import { existsSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import en from "../locales/en.json";
import fr from "../locales/fr.json";

// 1.5.6: the single sign-on screen told the admin to run
// "manage.py sso_email_domains"; the command is sso_domains. Every command
// a page names must exist in the backend.
const backend = resolve(__dirname, "../../../backend");
const commands = new Set();
for (const app of readdirSync(backend)) {
  const dir = join(backend, app, "management", "commands");
  if (existsSync(dir)) readdirSync(dir).filter((f) => f.endsWith(".py")).forEach((f) => commands.add(f.slice(0, -3)));
}

const named = (obj) => JSON.stringify(obj).match(/manage\.py\s+[\w-]+/g)?.map((m) => m.split(/\s+/)[1]) ?? [];

describe("manage.py commands named in the interface", () => {
  it("finds the backend commands", () => {
    expect(commands.has("sso_domains")).toBe(true);
  });

  it.each([["en", en], ["fr", fr]])("exist (%s)", (_, locale) => {
    const names = named(locale);
    expect(names).toContain("sso_domains");
    expect(names.filter((n) => !commands.has(n))).toEqual([]);
  });
});
