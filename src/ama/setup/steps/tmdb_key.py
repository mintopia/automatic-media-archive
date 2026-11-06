"""The TMDB key (ADR 0016): checked with TMDB before Setup goes on, or skipped, in which
case films and TV aren't identified and Now says so until a key is added."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

import httpx

from ama.setup import Draft, Step, Values
from ama.tmdb import Tmdb, TmdbError, TmdbKeyRefused

CHOICE = "tmdb"  # a Choice
KEY = "tmdb_key"


class Choice(StrEnum):
    """Use a key, or skip: the form's radio values."""

    KEY = "key"
    SKIP = "skip"

SKIPPED = "Skipped — CDs only for now"


def client() -> httpx.Client:
    return httpx.Client(timeout=10)


def key_problem(key: str) -> str | None:
    """Why `key` can't be used (TMDB refused it or couldn't be asked), or None."""
    try:
        with client() as http:
            Tmdb(http, key).authenticate()
    except TmdbKeyRefused:
        return ("TMDB didn't accept this key. Copy the v3 \"API Key\" from your TMDB "
                "account settings (API) again.")
    except TmdbError as e:
        return f"{e}. Check this computer is online and try again, or choose Skip for now."
    return None


def _skipped(values: Values) -> bool:
    """Skip chosen, or no key given (the built-in default, as for every other setting)."""
    return values.get(CHOICE) == Choice.SKIP or not values.get(KEY)


def _defaults(config: Path) -> dict[str, str]:
    return {CHOICE: Choice.KEY, KEY: ""}


def _check(values: Values) -> dict[str, str]:
    if _skipped(values):
        return {}
    problem = key_problem(values[KEY])
    return {KEY: problem} if problem else {}


def _settings(values: Values) -> Draft:
    return Draft(changes={"tmdb.api_key": "" if _skipped(values) else values[KEY]})


def _summary(values: Values) -> list[tuple[str, str]]:
    return [("TMDB key", SKIPPED if _skipped(values) else "Checked with TMDB")]


STEP = Step(slug="tmdb", title="TMDB key", order=40, template="setup/tmdb.html",
            fields=(CHOICE, KEY), defaults=_defaults, check=_check, settings=_settings,
            summary=_summary)
