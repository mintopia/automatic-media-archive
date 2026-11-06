// Headless Chrome over the DevTools protocol, for the screenshot tools: open(), then shoot()
// pages at a viewport and colour scheme. Set CHROME to use a Chrome that isn't in the usual place.
import { spawn } from "node:child_process";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = process.env.CHROME || [
  "C:/Program Files/Google/Chrome/Application/chrome.exe",
  "C:/Program Files (x86)/Google/Chrome/Application/chrome.exe",
  "/usr/bin/google-chrome",
].find(existsSync);
const PORT = 9333;

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

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

// view: { width, height, mobile, fullPage }; theme: "light" | "dark". Resolves to PNG bytes.
export async function open() {
  const profile = mkdtempSync(join(tmpdir(), "ama-shots-"));
  const chrome = spawn(CHROME, [
    "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
    `--remote-debugging-port=${PORT}`, `--user-data-dir=${profile}`, "about:blank",
  ], { stdio: "ignore" });
  let cdp;
  try {
    cdp = await connect(await target());
    await cdp.send("Page.enable");
  } catch (e) {
    chrome.kill();
    throw e;
  }
  return {
    async shoot(url, view, theme) {
      await cdp.send("Emulation.setDeviceMetricsOverride", {
        width: view.width, height: view.height, deviceScaleFactor: 1, mobile: view.mobile,
      });
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
        format: "png", captureBeyondViewport: !!view.fullPage, ...(clip ? { clip } : {}),
      });
      return Buffer.from(data, "base64");
    },
    async close() {
      cdp.close();
      chrome.kill();
      await sleep(300);
      try { rmSync(profile, { recursive: true, force: true }); } catch {}
    },
  };
}
