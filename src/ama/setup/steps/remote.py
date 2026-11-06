"""Reach AMA from other devices? Yes (the default) listens on every address; No keeps AMA
to this PC. Yes offers a password, stored as `web.password`, the same one Settings sets.
Setup itself always runs on 127.0.0.1 (ADR 0016); AMA moves to the chosen host after it.
The port stays at its default: Setup and AMA share it, so the tray's address holds."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from ama.config import SETUP_HOST, load_config
from ama.db import Database
from ama.setup import Draft, Step, Values
from ama.web import auth

REMOTE, PASSWORD = "remote", "password"


class Remote(StrEnum):
    """The answer: the form's radio values."""

    YES = "yes"
    NO = "no"


HOSTS = {Remote.YES: "0.0.0.0", Remote.NO: SETUP_HOST}


def _remote(values: Values) -> Remote | None:
    try:
        return Remote(values.get(REMOTE, ""))
    except ValueError:
        return None


def _defaults(config: Path) -> dict[str, str]:
    return {REMOTE: Remote.YES, PASSWORD: ""}


def _check(values: Values) -> dict[str, str]:
    if _remote(values) is None:
        return {REMOTE: "Choose Yes or No"}
    return {}


def _password(values: Values) -> str:
    """The password to keep: only with remote access, where it's what keeps others out."""
    return values.get(PASSWORD, "") if _remote(values) is Remote.YES else ""


def _settings(values: Values) -> Draft:
    changes = {"web.host": HOSTS[Remote(values[REMOTE])]}  # _check passed
    if password := _password(values):
        changes["web.password"] = password
    return Draft(changes=changes)


def _summary(values: Values) -> list[tuple[str, str]]:
    if _remote(values) is not Remote.YES:
        return [("Other devices", "No: only this PC can open AMA")]
    return [("Other devices", "Yes: phones and computers at home can open AMA"),
            ("Password", "Set" if _password(values) else "None: anyone at home can use AMA")]


def _cookies(values: Values, config: Path) -> dict[str, str]:
    """Sign the browser that ran Setup in, so the password doesn't greet it straight away."""
    if not (password := _password(values)):
        return {}
    db = Database(load_config(config).paths.state_db)
    try:
        return {auth.COOKIE: auth.signed_in_token(db, password)}
    finally:
        db.close()


STEP = Step(slug="remote", title="Reach AMA from other devices?", order=50,
            template="setup/remote.html", fields=(REMOTE, PASSWORD),
            secrets=frozenset({PASSWORD}), defaults=_defaults, check=_check,
            settings=_settings, summary=_summary, cookies=_cookies)
