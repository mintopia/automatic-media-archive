// Mockup-only: ?theme=light|dark forces a theme for screenshots.
const t = new URLSearchParams(location.search).get("theme");
if (t === "light" || t === "dark") document.documentElement.dataset.theme = t;
