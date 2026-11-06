"""Fail a release whose tag isn't `vX.Y.Z` or doesn't match pyproject.toml (ADR 0013).

The release workflow runs this before creating the GitHub Release.
Usage: python check_tag_version.py <tag> [pyproject.toml]
"""

import re
import sys
import tomllib
from pathlib import Path

RELEASE_TAG = re.compile(r"v(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)")


def main(argv: list[str]) -> int:
    tag, pyproject = argv[0], Path(argv[1] if len(argv) > 1 else "pyproject.toml")
    if not RELEASE_TAG.fullmatch(tag):
        print(f"Tag {tag} isn't a release tag: releases are tagged vX.Y.Z.", file=sys.stderr)
        return 1
    version = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"]["version"]
    if tag != f"v{version}":
        print(
            f"Tag {tag} doesn't match pyproject.toml version {version}. "
            f"Bump the version in the release PR, or tag v{version}.",
            file=sys.stderr,
        )
        return 1
    print(f"Tag {tag} matches pyproject.toml version {version}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
