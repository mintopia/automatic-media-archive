# Decision: The public website is an Astro site in `website/`, deployed from `main`

Status: accepted
Date: 2026-11-06

## Context
AMA needs a public site for people archiving their own Discs: what it does, install, Setup, Libraries and Naming Patterns, and a settings reference. It should look as considered as the app's UI, not like a stock docs theme. MkDocs Material would match the Python stack but looks like every other docs site.

## Decision
- The site is built with **Astro** from `website/` in this repo. It is designed to the app's visual language (`DESIGN.md`), using the impeccable design pass before any content is written.
- **GitHub Actions builds and deploys it to GitHub Pages on pushes to `main`**, so the site always describes the released version. The default `mintopia.github.io/automatic-media-archive` URL is used for now.
- Pages: Landing, Install, Setup walkthrough, How a Disc flows, Libraries & Naming Patterns, Settings reference, Third-party tools & licences, Contributing (one page that points to the repo).
- The Settings reference is **generated from `ama.example.toml`'s comments** at build time, so it can't drift from the real settings.
- Contributor material (ADRs, glossary, agent docs) stays in the repo, not on the site.

## Consequences
- A Node toolchain lives in a Python repo, confined to `website/`. App CI doesn't need it.
- Changes on `develop` reach the site only at the next release.
- `ama.example.toml` comments become user-facing documentation and must be written as such.

## Supersedes
None
