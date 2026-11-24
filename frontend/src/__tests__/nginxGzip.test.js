import { describe, it, expect } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

// 1.5.5: behind Caddy the scripts and styles were sent uncompressed.
describe("nginx.conf", () => {
  const conf = readFileSync(resolve(__dirname, "../../nginx.conf"), "utf8");
  it("compresses also when a proxy sits in front", () => {
    expect(conf).toMatch(/^\s*gzip on;/m);
    expect(conf).toMatch(/^\s*gzip_proxied any;/m);
    expect(conf).toMatch(/^\s*gzip_types [^;]*application\/javascript[^;]*;/m);
    expect(conf).toMatch(/^\s*gzip_types [^;]*text\/css[^;]*;/m);
  });
});
