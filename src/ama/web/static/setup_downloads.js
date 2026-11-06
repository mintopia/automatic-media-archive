// Setup's Ready step: Finish stays disabled while AMA's tools are still downloading.
(() => {
  const sync = () => {
    const busy = document.querySelector("[data-downloads-busy]") !== null;
    for (const b of document.querySelectorAll(".setup-foot button[type=submit]")) b.disabled = busy;
  };
  sync();
  document.addEventListener("htmx:afterSettle", sync);
})();
