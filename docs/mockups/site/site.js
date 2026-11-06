// Mockup-only: screenshots follow a forced theme.
const forced = document.documentElement.dataset.theme;
if (forced) document.querySelectorAll("picture").forEach((pic) => {
  const dark = pic.querySelector("source");
  const img = pic.querySelector("img");
  if (forced === "dark" && dark) img.src = dark.srcset;
  dark?.remove();
});
