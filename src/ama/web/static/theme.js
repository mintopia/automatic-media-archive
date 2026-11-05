(() => {
  const KEY = "ama-theme";
  const root = document.documentElement;
  const apply = (t) => {
    if (t === "light" || t === "dark") root.dataset.theme = t;
    else delete root.dataset.theme;
  };
  let saved = null;
  try { saved = localStorage.getItem(KEY); } catch {}
  // ?theme=light|dark forces a theme for screenshots.
  apply(new URLSearchParams(location.search).get("theme") || saved);

  document.addEventListener("DOMContentLoaded", () => {
    const menu = document.querySelector("details.menu");
    if (!menu) return;
    const buttons = menu.querySelectorAll("[data-theme-set]");
    const sync = () => buttons.forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.themeSet === (root.dataset.theme || "system"))));
    sync();
    buttons.forEach((b) => b.addEventListener("click", () => {
      const t = b.dataset.themeSet;
      try { t === "system" ? localStorage.removeItem(KEY) : localStorage.setItem(KEY, t); } catch {}
      apply(t);
      sync();
    }));
    const close = () => { menu.open = false; };
    menu.addEventListener("keydown", (e) => {
      if (e.key === "Escape" && menu.open) { close(); menu.querySelector("summary").focus(); }
    });
    document.addEventListener("click", (e) => { if (menu.open && !menu.contains(e.target)) close(); });
    menu.addEventListener("focusout", (e) => { if (e.relatedTarget && !menu.contains(e.relatedTarget)) close(); });
  });

  // Skip SSE swaps that change nothing, so live regions only speak on real changes.
  const words = (s) => s.replace(/\s+/g, " ").trim();
  document.addEventListener("htmx:sseBeforeMessage", (e) => {
    const el = e.target;
    const data = e.detail.data;
    let same = el._amaLast === data;
    if (!same && (el.hasAttribute("aria-live") || el.hasAttribute("role"))) {
      const t = document.createElement("template");
      t.innerHTML = data;
      same = words(t.content.textContent) === words(el.textContent);
    }
    el._amaLast = data;
    if (same) e.preventDefault();
  });
})();
