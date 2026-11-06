// Screenshots of running pages: node docs/mockups/tools/capture.mjs shots.json
// shots.json is a list of { url, out, width, height, mobile, fullPage, theme } (app_screenshots.py writes it).
import { readFileSync, writeFileSync } from "node:fs";
import { open } from "./chrome.mjs";

const shots = JSON.parse(readFileSync(process.argv[2], "utf8"));
const chrome = await open();
try {
  for (const s of shots) {
    writeFileSync(s.out, await chrome.shoot(s.url, s, s.theme));
    console.log(s.out);
  }
} finally {
  await chrome.close();
}
