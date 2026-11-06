// Mockup-only behaviour for the site pages: the hero Disc advances stage by stage, and screenshots follow a forced theme.
const PHASES = [
  { cls: "rip", label: "Ripping", step: "Ripping Title 2 of 6 · 18 min left", pct: 64, done: 0 },
  { cls: "rev", label: "Review", step: "Two close matches. AMA asks you which film it is.", pct: null, done: 1 },
  { cls: "enc", label: "Encoding", step: "Encoding the Main Feature to HEVC · 11 min left", pct: 38, done: 2 },
  { cls: "fil", label: "Archived", step: "Named and moved into your Films Library.", pct: null, done: 3 },
];
const EDGE = { rip: "var(--rip)", rev: "var(--rev)", enc: "var(--enc)", fil: "var(--fil)" };

const hero = document.querySelector("[data-hero]");
if (hero && !matchMedia("(prefers-reduced-motion: reduce)").matches && !new URLSearchParams(location.search).has("still")) {
  const tabs = hero.querySelectorAll(".htab");
  const stk = hero.querySelector(".stk.xl");
  const step = hero.querySelector(".step");
  const segs = hero.querySelectorAll(".strip b");
  const bar = hero.querySelector(".hprog .bar");
  const fill = hero.querySelector(".hprog .bar i");
  const pct = hero.querySelector(".hprog .pct");
  const where = hero.querySelector(".hprog .where");
  let n = 0;
  const show = (p) => {
    hero.style.setProperty("--edge", EDGE[p.cls]);
    tabs.forEach((t, i) => t.classList.toggle("on", i === PHASES.indexOf(p)));
    stk.className = "stk xl " + p.cls;
    stk.textContent = p.label;
    step.textContent = p.step;
    segs.forEach((s, i) => { s.className = i < p.done ? "done" : i === p.done ? "now" : ""; });
    const hasBar = p.pct !== null;
    bar.hidden = pct.hidden = !hasBar;
    where.hidden = p.cls !== "fil";
    if (hasBar) { fill.style.width = p.pct + "%"; pct.textContent = p.pct + "%"; }
  };
  setInterval(() => { n = (n + 1) % PHASES.length; show(PHASES[n]); }, 2800);
}

const forced = document.documentElement.dataset.theme;
if (forced) document.querySelectorAll("picture").forEach((pic) => {
  const dark = pic.querySelector("source");
  const img = pic.querySelector("img");
  if (forced === "dark" && dark) img.src = dark.srcset;
  dark?.remove();
});
