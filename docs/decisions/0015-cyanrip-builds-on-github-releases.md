# Decision: AMA's cyanrip builds are published as GitHub Releases

Status: accepted
Date: 2026-11-06

## Context
ADR 0007 publishes AMA's self-built cyanrip to the Forgejo package registry on `git.mintopia.net`, and every install downloads it from there. Now that AMA is public on GitHub, installs shouldn't depend on a private server being reachable. The build is GPL (static libcdio/paranoia), so its source must be available wherever the binary is published.

## Decision
- Each cyanrip build is a **GitHub Release on `mintopia/automatic-media-archive`** tagged `cyanrip-<PACKAGE_VERSION>` (e.g. `cyanrip-0.9.4-rc3-g648b1dd`). It carries the same zip (`cyanrip.exe`, `LICENSE.md`, `BUILDINFO.txt`).
- The release notes link the upstream commit and the pinned `tools/cyanrip` build inputs at that tag. This satisfies the GPL source offer.
- The tag is not semver-shaped, so it never triggers the app release workflow, which runs on `v*.*.*` only (ADR 0013).
- `tools/cyanrip/build.ps1 -PublishOnly` uploads to the GitHub Release instead of Forgejo, and the `Pin` URL in `src/ama/tools.py` points there. Releases are never overwritten: a new build is a new tag.

## Consequences
- Installs depend only on GitHub.
- The existing Forgejo package can stay for old installs, but new pins never use it.

## Supersedes
The publishing location in ADR 0007 (step 3 and the Forgejo package paragraph). The rest of ADR 0007 still holds.
