// Regenerates docs/mockups/screenshots/: node docs/mockups/tools/screenshots.mjs [page.html ...]
// Each mockup page gets desktop (1440x850 viewport) and mobile (390px, full page) shots in light and dark.
import { spawn } from "node:child_process";
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { extname, normalize } from "node:path";
import { mkdtempSync, readdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const MOCKUPS = join(dirname(fileURLToPath(import.meta.url)), "..");
const OUT = join(MOCKUPS, "screenshots");
const CHROME = process.env.CHROME || [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
].find(existsSync);
const PORT = 9333;
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

const profile = mkdtempSync(join(tmpdir(), "ama-shots-"));
const chrome = spawn(CHROME, [
  "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
  `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "about:blank",
], { stdio: "ignore" });

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function target() {
  for (let i = 0; i < 50; i++) {
    try {
      const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
      const page = list.find((t) => t.type === "page");
      if (page) return page.webSocketDebuggerUrl;
    } catch {}
    await sleep(200);
  }
  throw new Error("Chrome didn't start");
}

function connect(url) {
  const ws = new WebSocket(url);
  let id = 0;
  const pending = new Map();
  const waiters = [];
  ws.onmessage = (e) => {
    const msg = JSON.parse(e.data);
    if (msg.id && pending.has(msg.id)) {
      const { resolve, reject } = pending.get(msg.id);
      pending.delete(msg.id);
      msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
    } else if (msg.method) {
      for (const w of waiters.splice(0)) w(msg);
    }
  };
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    pending.set(++id, { resolve, reject });
    ws.send(JSON.stringify({ id, method, params }));
  });
  const until = (method) => new Promise((resolve) => {
    const check = (msg) => (msg.method === method ? resolve(msg) : waiters.push(check));
    waiters.push(check);
  });
  return new Promise((resolve) => { ws.onopen = () => resolve({ send, until, close: () => ws.close() }); });
}

try {
  const cdp = await connect(await target());
  await cdp.send("Page.enable");
  for (const file of pages) {
    const url = `http://127.0.0.1:${HTTP_PORT}/${file}`;
    for (const view of VIEWS) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width: view.width, height: view.height, deviceScaleFactor: 1, mobile: view.mobile,
      });
      for (const theme of THEMES) {
        await cdp.send("Emulation.setEmulatedMedia", {
          features: [{ name: "prefers-color-scheme", value: theme }],
        });
        const loaded = cdp.until("Page.loadEventFired");
        await cdp.send("Page.navigate", { url });
        await loaded;
        await cdp.send("Runtime.evaluate", { expression: "document.fonts.ready", awaitPromise: true });
        await sleep(150);
        let clip;
        if (view.fullPage) {
          const { cssContentSize } = await cdp.send("Page.getLayoutMetrics");
          clip = { x: 0, y: 0, width: view.width, height: Math.ceil(cssContentSize.height), scale: 1 };
        }
        const { data } = await cdp.send("Page.captureScreenshot", {
          format: "png", captureBeyondViewport: view.fullPage, ...(clip ? { clip } : {}),
        });
        const name = `${file.replace(/\.html$/, "")}-${view.name}-${theme}.png`;
        writeFileSync(join(OUT, name), Buffer.from(data, "base64"));
      }
    }
    console.log(file);
  }
  cdp.close();
} finally {
  chrome.kill();
  server.close();
  await sleep(300);
  try { rmSync(profile, { recursive: true, force: true }); } catch {}
}
