import { test, before } from "node:test";
import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync, existsSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { PAGES, sectionOf } from "./docs.ts";
import { parseExample } from "./settings.ts";

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

test("every root-relative link and asset in the built site is under the repo sub-path and exists", () => {
  const base = "/automatic-media-archive/";
  const pages = readdirSync(dist(""), { recursive: true, encoding: "utf8" }).filter((f) => f.endsWith(".html"));
  assert.ok(pages.length > 1);
  for (const page of pages) {
    const html = readFileSync(dist(page), "utf8");
    for (const [, ref] of html.matchAll(/(?:href|src|srcset)="(\/[^"\s]*)/g)) {
      assert.ok(ref.startsWith(base), `${page}: ${ref} is outside ${base}`);
      const target = decodeURI(ref.slice(base.length).split(/[?#]/)[0]);
      const onDisk = target === "" || target.endsWith("/") ? `${target}index.html` : target;
      assert.ok(existsSync(dist(onDisk)), `${page}: ${ref} points at nothing in dist/`);
    }
  }
});

test("the Settings reference shows every table and key of ama.example.toml", () => {
  const html = readFileSync(dist("docs/settings/index.html"), "utf8");
  const { tables } = parseExample(readFileSync(new URL("../../ama.example.toml", import.meta.url), "utf8"));
  for (const t of tables) {
    assert.match(html, new RegExp(`<h2 id="${t.name}"[^>]*>\\[{1,2}${t.name}\\]{1,2}</h2>`));
    for (const k of t.groups.flatMap((g) => g.keys)) assert.ok(html.includes(`id="${t.name}.${k.name}"`), `${t.name}.${k.name}`);
  }
});

test("the Settings reference marks secrets, restarts and defaults", () => {
  const html = readFileSync(dist("docs/settings/index.html"), "utf8");
  assert.match(html, /id="tmdb\.api_key"[\s\S]*?<span class="mark">Secret<\/span>/);
  assert.match(html, /id="web"[^>]*>\[web\]<\/h2>\s*<p class="mark">Needs a restart<\/p>/);
  assert.doesNotMatch(html, /id="cd"[^>]*>\[cd\]<\/h2>\s*<p class="mark">/);
  assert.match(html, /id="web\.port"[\s\S]*?<code>8080<\/code>/);
});

test("Third-party tools & licences lists every row of THIRD_PARTY_NOTICES.md with its licence", () => {
  const html = unescape(readFileSync(dist("docs/third-party/index.html"), "utf8"));
  const notices = readFileSync(new URL("../../THIRD_PARTY_NOTICES.md", import.meta.url), "utf8");
  const rows = [...notices.matchAll(/^\| ([^|]+?) \| ([^|]+?) \|/gm)]
    .map(([, name, licence]) => [name, licence.replace(/ \(.*/, "")])
    .filter(([name]) => !/^(Package|Tool|File|-+)$/.test(name));
  assert.ok(rows.length > 20);
  for (const [name, licence] of rows) {
    assert.match(html, new RegExp(`<td>${name}</td>\\s*<td>${licence}`), `${name} (${licence})`);
  }
});

test("/docs/ sends you to the first docs page under the site's base path", () => {
  const html = readFileSync(dist("docs/index.html"), "utf8");
  assert.match(html, /url=\/automatic-media-archive\/docs\/install\/"/);
});
