// Per-Job settings on the rip card (#30): the summary line's button opens and closes
// "This Job's settings". The card re-renders live, so the button's state follows the panel
// (which htmx keeps, hx-preserve) after every swap.
(() => {
  function sync() {
    for (const b of document.querySelectorAll("[data-jobset-toggle]")) {
      const panel = document.getElementById(b.getAttribute("aria-controls"));
      const open = !!panel && !panel.hidden;
      b.setAttribute("aria-expanded", String(open));
      b.textContent = open ? "Hide settings" : "Settings";
    }
  }
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-jobset-toggle]");
    if (!b) return;
    const panel = document.getElementById(b.getAttribute("aria-controls"));
    if (!panel) return;
    panel.hidden = !panel.hidden;
    sync();
  });
  document.addEventListener("htmx:afterSettle", sync);
  document.addEventListener("htmx:oobAfterSwap", sync);
  document.addEventListener("DOMContentLoaded", sync);
})();
