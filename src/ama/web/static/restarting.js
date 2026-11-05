// The restarting page: ask /boot until a new server answers, then go back.
(() => {
  const el = document.querySelector("[data-restarting]");
  if (!el) return;
  const { boot, bootUrl, after } = el.dataset;
  const started = Date.now();
  async function poll() {
    try {
      const r = await fetch(bootUrl, { cache: "no-store" });
      if (r.ok && (await r.json()).boot !== boot) {
        location.href = after;
        return;
      }
    } catch (e) { /* down while it restarts */ }
    if (Date.now() - started > 60000) el.querySelector("[data-slow]").hidden = false;
    setTimeout(poll, 500);
  }
  setTimeout(poll, 500);
})();
