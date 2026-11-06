import { defineConfig } from "astro/config";
import { copyFileSync } from "node:fs";

// The site uses the app's own icon sprite, copied in so Markdown pages can reference it by a stable path.
const appIcons = {
  name: "app-icons",
  hooks: {
    "astro:config:setup": () => copyFileSync(new URL("../src/ama/web/static/icons.svg", import.meta.url), new URL("./public/icons.svg", import.meta.url)),
  },
};

export default defineConfig({
  site: "https://mintopia.github.io",
  base: "/automatic-media-archive",
  trailingSlash: "always",
  redirects: { "/docs/": "/automatic-media-archive/docs/install/" },
  integrations: [appIcons],
  vite: { server: { fs: { allow: [".."] } } },
});
