# Contributing

## Where things live

- **Code**: GitHub, [`mintopia/automatic-media-archive`](https://github.com/mintopia/automatic-media-archive).
  This is the `origin` remote. Clone it with
  `git clone https://github.com/mintopia/automatic-media-archive.git`.
- **Issues**: still on the Forgejo at
  [`git.mintopia.net/mintopia/automatic-media-archive`](https://git.mintopia.net/mintopia/automatic-media-archive/issues).
  GitHub Issues are turned off until issues move (ADR 0013).
- The Forgejo repo mirrors GitHub. Never push to it by hand. If you have it as a
  remote, call it `forgejo`.

## Citing issues

Cite an issue by its **full Forgejo URL**, in commit messages and PR bodies:

```
Cancel a Job from its page

https://git.mintopia.net/mintopia/automatic-media-archive/issues/62
```

Never write a bare `#62`: GitHub links that to its own tracker, which is empty.

## Branches (gitflow, no release branches)

| Branch | Holds | Created from | Merges into |
| --- | --- | --- | --- |
| `develop` | the integration branch; GitHub's default | | `main`, by a release PR |
| `main` | released code only; every release is a tag on it | | `develop`, by a back-merge |
| `feature/*` | one piece of work | `develop` | `develop` |
| `hotfix/*` | an urgent fix to a release | `main` | `main`, by a PR; then back-merged into `develop` |

### Features

1. Branch `feature/<name>` from `develop`.
2. Merge it into `develop` when done (a PR or a local merge). A small change may be
   committed straight to `develop`.

### Releases

1. Bump `version` in `pyproject.toml` to the next semver version, `X.Y.Z`, on
   `develop`, and run `uv lock` so `uv.lock` carries it too. Commit both.
2. Open a PR from `develop` to `main`. CI runs the lint and the tests on it.
3. Merge it once CI passes.
4. Tag the merge on `main` and push the tag:

   ```powershell
   git switch main
   git pull
   git tag vX.Y.Z
   git push origin vX.Y.Z
   ```

   The tag drives the release (`.github/workflows/release.yml`). The workflow fails,
   and creates nothing, unless the tag is exactly `vX.Y.Z`, matches the
   `pyproject.toml` version and is on `main`. Otherwise it creates a GitHub Release
   with notes generated from the merged PRs, `AMA-Setup-X.Y.Z.exe` built from the
   tagged commit on a Windows runner, plus GitHub's source archives.
   If the tag is wrong, delete it (`git push origin :refs/tags/vX.Y.Z`), fix the
   cause and tag again. `cyanrip-*` tags (cyanrip builds) never start a release.
5. Back-merge `main` into `develop`, so `develop` holds the release merge and tag:

   ```powershell
   git switch develop
   git merge main
   git push origin develop
   ```

### Hotfixes

1. Branch `hotfix/<name>` from `main`.
2. Bump the patch version in `pyproject.toml` (and `uv lock`) on the hotfix branch.
3. Open a PR from it to `main`; CI runs on it. Merge, then tag `vX.Y.Z` as for a release.
4. Back-merge `main` into `develop`.

## The Windows installer

`AMA-Setup-X.Y.Z.exe` (ADR 0017) is built by one script, on Windows, with
[Inno Setup](https://jrsoftware.org/isinfo.php) 6.7 or later:

```powershell
uv run python tools/installer/build.py      # writes dist\AMA-Setup-X.Y.Z.exe
```

It takes the version from `pyproject.toml`, builds AMA's wheel, exports the locked
requirements (`uv export --frozen`), downloads the pinned `uv.exe` (hash-checked) and runs
Inno Setup's `ISCC.exe` on `tools/installer/ama.iss`. It finds `ISCC.exe` through
`--iscc`, `$ISCC`, `PATH` or Inno Setup's usual install folders. Inno Setup installs
without admin rights when its own installer runs with `/CURRENTUSER`. The script needs no
input and exits non-zero on any failure. `--stage-only` stops before Inno Setup.
The release workflow installs the Inno Setup version pinned in `release.yml`
(`INNO_VERSION`, `INNO_SHA256`) rather than the runner's own.

The installer is unsigned for now. At install time `install-env.cmd` has uv install
the Python pinned in `build.py` and the locked requirements into the app folder
(`%LOCALAPPDATA%\Programs\AMA`). To bump uv or Python, change `UV_VERSION`,
`UV_SHA256` (from the release's `.sha256` file) or `PYTHON_VERSION` in `build.py`, and
replace the uv licence texts in `tools/installer/licenses/`.

Silent installs take Inno Setup's usual switches (`/VERYSILENT`, `/TASKS=""` to leave
"Start AMA when I sign in" off) and exit 1 if Python or the requirements couldn't be
installed. The uninstaller (`unins000.exe` in the app folder) takes `/REMOVEDATA` to
remove `%LOCALAPPDATA%\AMA` when silent too; Libraries are never touched.

## Lint and tests

```powershell
uv sync
uv run ruff check
uv run pytest
```

No hardware is needed. The lint is Ruff with only its error rules (syntax, unused
and undefined names); the rule list is in `pyproject.toml`. There is no formatter.

CI (`.github/workflows/ci.yml`) runs these same three commands, from the lockfile, on a
Windows runner for every PR into `main`. A lint error or a failing test fails the check.
