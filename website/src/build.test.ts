import { test, before } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, existsSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { PAGES, sectionOf } from "./docs.ts";

const root = fileURLToPath(new URL("..", import.meta.url));
const dist = (path: string) => fileURLToPath(new URL(`../dist/${path}`, import.meta.url));
const unescape = (s: string) => s.replaceAll("&amp;", "&");

before(() => {
  execFileSync(process.execPath, ["node_modules/astro/bin/astro.mjs", "build", "--silent"], { cwd: root, stdio: "pipe" });
});

test("the landing page builds with the headline", () => {
  const html = readFileSync(dist("index.html"), "utf8");
  assert.match(html, /<h1[^>]*>Put a Disc in, it turns up in Plex\.<\/h1>/);
});

for (const page of PAGES) {
  test(`docs page "${page.title}" builds with its title and open section`, () => {
    const file = dist(`docs/${page.slug}/index.html`);
    assert.ok(existsSync(file), `${file} missing`);
    const html = unescape(readFileSync(file, "utf8"));
    assert.match(html, new RegExp(`<h1[^>]*>${page.title}</h1>`));
    assert.match(html, new RegExp(`aria-current="true"[^>]*>${sectionOf(page.slug).label}<`));
  });
}

test("/docs/ sends you to the first docs page under the site's base path", () => {
  const html = readFileSync(dist("docs/index.html"), "utf8");
  assert.match(html, /url=\/automatic-media-archive\/docs\/install\/"/);
});
