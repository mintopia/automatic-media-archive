---
layout: ../../layouts/Docs.astro
slug: contributing
description: AMA is developed in the open on GitHub. Everything you need to work on it is in the repository.
---

The code is at [github.com/mintopia/automatic-media-archive](https://github.com/mintopia/automatic-media-archive). Start with [`CONTRIBUTING.md`](https://github.com/mintopia/automatic-media-archive/blob/develop/CONTRIBUTING.md): it covers where things live, the branches, how releases and the installer are built, and how to run the lint and tests.

## Reporting a problem

Issues are tracked on the project’s [Forgejo](https://git.mintopia.net/mintopia/automatic-media-archive/issues), not on GitHub. Say which Disc Type it was, what you expected and what happened. The Job’s log helps most: open the Job from History or **Didn’t work**, and choose **View log**.

## Working on the code

AMA is a Python app, run with [uv](https://docs.astral.sh/uv/). The tests use fake drives and tools, so you need no optical drive to run them:

```powershell
git clone https://github.com/mintopia/automatic-media-archive.git
cd automatic-media-archive
uv sync
uv run pytest
```

Work branches from `develop`. The words AMA uses for things, like Job, Rip, Title and Naming Pattern, are defined in the repository’s `GLOSSARY.md`, and past design decisions are recorded in `docs/decisions/`.

This website is in `website/`, and its Settings reference is built from `ama.example.toml`, so a change to a setting’s comment there changes the page.

## Licence

AMA is under the MIT licence. A new dependency needs a line in `THIRD_PARTY_NOTICES.md`, the list behind [Third-party tools & licences](../third-party/), and AMA can’t take a GPL dependency.
