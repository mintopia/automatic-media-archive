// Regenerates docs/mockups/screenshots/: node docs/mockups/tools/screenshots.mjs [page.html ...]
// Each mockup page gets desktop (1440x850 viewport) and mobile (390px, full page) shots in light and dark.
import { createServer } from "node:http";
import { existsSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, extname, join, normalize } from "node:path";
import { fileURLToPath } from "node:url";
import { open } from "./chrome.mjs";

const MOCKUPS = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(MOCKUPS, "screenshots");
const HTTP_PORT = 9334;
const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml", ".png": "image/png" };
const VIEWS = [
  { name: "desktop", width: 1440, height: 850, mobile: false, fullPage: false },
  { name: "mobile", width: 390, height: 844, mobile: true, fullPage: true },
];
const THEMES = ["light", "dark"];

const pages = process.argv.slice(2).length
  ? process.argv.slice(2)
  : readdirSync(MOCKUPS).filter((f) => f.endsWith(".html") && f !== "index.html").sort();

// Served over HTTP: Chrome won't load the icons.svg sprite from file:// pages.
const server = createServer((req, res) => {
  const path = normalize(join(MOCKUPS, decodeURIComponent(new URL(req.url, "http://x").pathname)));
  if (!path.startsWith(MOCKUPS) || !existsSync(path)) { res.writeHead(404); res.end(); return; }
  res.writeHead(200, { "Content-Type": TYPES[extname(path)] || "application/octet-stream" });
  res.end(readFileSync(path));
}).listen(HTTP_PORT, "127.0.0.1");

const chrome = await open();
try {
  for (const file of pages) {
    for (const view of VIEWS) {
      for (const theme of THEMES) {
        const png = await chrome.shoot(`http://127.0.0.1:${HTTP_PORT}/${file}`, view, theme);
        writeFileSync(join(OUT, `${file.replace(/\.html$/, "")}-${view.name}-${theme}.png`), png);
      }
    }
    console.log(file);
  }
} finally {
  await chrome.close();
  server.close();
}
