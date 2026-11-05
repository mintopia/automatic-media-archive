"""What the Settings page shows: tabs, sections, groups and field rows (DESIGN.md "Settings Page").

This is the one place to add a setting to the UI. Each `Field` names a dotted
`ama.toml` key; its input kind (text, number, secret) comes from the config
model, and whether it applies at once from `settings.LIVE_TABLES`. A new
section is a `Section` appended to `SECTIONS` (with its tab in `TABS`); a section
with its own UI beyond field rows (e.g. Libraries) can name a `template` partial
rendered after its groups. tests/test_web_settings.py fails if a config key has
no field, or appears twice.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from markupsafe import Markup

from ama.web import settings_libraries

if TYPE_CHECKING:
    from fastapi import Request

    from ama.app import Services

# A placeholder or status can depend on the running app (e.g. the drive Windows found).
Dynamic = Callable[["Services"], str]


@dataclass(frozen=True)
class Status:
    text: str
    ok: bool = True


@dataclass(frozen=True)
class Field:
    key: str  # dotted ama.toml key, e.g. "web.port"
    label: str
    hint: str | Markup = ""
    tech: str | Markup = ""  # the technical term, under the hint
    unit: str = ""
    placeholder: str | Dynamic = ""
    status: Callable[[Services], Status] | None = None  # e.g. a tool's state

    def keys(self) -> Iterator[str]:
        yield self.key


@dataclass(frozen=True)
class PerType:
    """One row holding a table with a value per Disc Type (scratch need, Encode quality)."""

    id: str
    label: str
    column: str  # the value column's heading
    rows: tuple[tuple[str, str], ...]  # (Disc Type name, key)
    hint: str | Markup = ""
    tech: str | Markup = ""
    unit: str = ""

    def keys(self) -> Iterator[str]:
        for _, key in self.rows:
            yield key


Row = Field | PerType


@dataclass(frozen=True)
class Group:
    title: str
    rows: tuple[Row, ...]
    # Live groups say when their change is used; the others say "Used after a restart".
    live: bool = False
    note: str = ""
    advanced: bool = False  # an "Advanced" disclosure, closed by default
    intro: str = ""  # a paragraph at the top of an Advanced disclosure
    status: Callable[[Services], Status] | None = None  # e.g. "Connected" by the heading

    def keys(self) -> Iterator[str]:
        for r in self.rows:
            yield from r.keys()


@dataclass(frozen=True)
class Section:
    slug: str  # URL under /settings/
    tab: str  # TABS key
    name: str  # "General", or the sub-section name ("NAS")
    groups: tuple[Group, ...]
    note: str | Markup = ""  # under the sheet; default says the file is the source
    # A section with its own UI beyond field rows: a partial rendered after the groups'
    # save bar, the context it needs, and the keys it edits (saved by its own routes).
    template: str = ""
    context: Callable[[Services, Request], dict[str, Any]] | None = None
    owns: tuple[str, ...] = ()
    foot: str = ""  # the save bar's name for the groups ("Plex connection"); default `name`
    note_only: bool = False  # `note` replaces the usual "Saved to ama.toml…" line

    @property
    def sub(self) -> bool:
        return self.slug.count("/") > 0

    def field_keys(self) -> Iterator[str]:
        """The keys the section's own form posts."""
        for g in self.groups:
            yield from g.keys()

    def keys(self) -> Iterator[str]:
        yield from self.field_keys()
        yield from self.owns


# --- dynamic bits --------------------------------------------------------------

def _drive_placeholder(services: Services) -> str:
    try:
        device = services.drive.device()
    except Exception:  # noqa: BLE001 - only a hint
        device = None
    return f"Automatic ({device})" if device else "Automatic"


def _tool_status(name: str) -> Callable[[Services], Status]:
    def status(services: Services) -> Status:
        from ama.tools import (ToolDownloading, ToolFailed, ToolPending, ToolReady,
                               makemkv_headline)
        st = services.tools.status(name)
        match st:
            case ToolReady(source="config"):
                return Status("Working · your copy")
            case ToolReady(source="installed", version=v):
                return Status(f"Working · {v}, registered" if v else "Working")
            case ToolReady(version=v):
                return Status(f"Working · {v}, AMA's copy" if v else "Working · AMA's copy")
            case ToolPending():
                return Status("Checking", ok=False)
            case ToolDownloading():
                return Status("Downloading", ok=False)
            case ToolFailed():
                return Status("Download failed", ok=False)
        return Status(makemkv_headline(st), ok=False)
    return status


def _nas_status(services: Services) -> Status:
    from ama.nas import NasConnected, NasUnreachable
    match services.nas.status:
        case NasConnected():
            return Status("Connected")
        case NasUnreachable():
            return Status("Can't reach the NAS", ok=False)
    return Status("Connecting", ok=False)


def _plex_status(services: Services) -> Status:
    if not services.plex.configured:
        return Status("Not set up", ok=False)
    if services.plex.listing() is None:
        return Status("Can't reach Plex", ok=False)
    return Status("Connected")


def _key(*keys: str) -> Markup:
    return Markup("Key ") + Markup(", ").join(Markup("<code>{}</code>").format(k) for k in keys)


# --- the page ----------------------------------------------------------------

# Tabs in order: (key, label). A tab with sub-sections opens on its first one.
# Logs joins when its setting lands (#34).
TABS: list[tuple[str, str]] = [("general", "General"), ("ripping", "Ripping"),
                               ("archive", "Archive"), ("alerts", "Alerts")]

_DISC_TYPES = (("DVD", "dvd"), ("Blu-ray", "bd"), ("UHD Blu-ray", "uhd"))

SECTIONS: list[Section] = [
    Section("general", "general", "General", (
        Group("Web UI", (
            Field("web.host", "Address",
                  "Who can open AMA. 0.0.0.0 lets phones and other computers at home reach it; "
                  "127.0.0.1 limits it to this PC."),
            Field("web.port", "Port",
                  "The number after the address in the browser bar (:8080). Change it only if "
                  "another program already uses it."),
            Field("web.password", "Password",
                  "Without a password, anyone on your home network can use AMA. Once saved it's "
                  "never shown again."),
        )),
        Group("Storage", (
            Field("paths.scratch", "Scratch folder",
                  "Rips wait here for Identification, Review and Encode. Needs at least 256 GB "
                  "free."),
            PerType("scratch-need", "Space needed before a Rip", "Free space",
                    (("CD", "scratch.cd"),
                     *((n, f"scratch.{k}") for n, k in _DISC_TYPES)),
                    hint="With less free, an inserted Disc is ejected unripped and Now shows "
                         "what's holding scratch.", unit="GB"),
        )),
        Group("Database and log file", (
            Field("paths.state_db", "Database",
                  Markup("AMA's record of every Disc. A plain name is kept next to "
                         "<code>ama.toml</code>."), _key("[paths] state_db")),
            Field("paths.log_file", "Log file", "AMA's own diagnostic log.",
                  _key("[paths] log_file")),
        ), advanced=True),
    )),
    Section("ripping", "ripping", "Ripping", (
        Group("Drive", (
            Field("drive.letter", "Drive letter",
                  "Leave empty to use the first optical drive Windows finds.",
                  placeholder=_drive_placeholder),
            Field("drive.poll_seconds", "Check for a Disc every",
                  "How soon AMA notices a Disc going in or coming out. 3 seconds suits most "
                  "drives.", unit="seconds"),
        )),
        Group("Reading CDs", (
            Field("cd.offset", "Read offset",
                  "Lines up your drive's reading so each CD Rip can be checked against "
                  "AccurateRip, a database of other people's Rips. +667 is right for the "
                  "PIONEER BDR-S11JX.",
                  Markup("In EAC's convention. Measure it once with cyanrip's offset test, "
                         "<code>cyanrip -f</code>. ") + _key("[cd] offset"), unit="samples"),
            Field("cd.retries", "Re-reads",
                  "How many times AMA reads a scratched spot again before counting it as an "
                  "error. More is slower but rescues more.", _key("[cd] retries"),
                  unit="per frame"),
        ), live=True, note="Used from the next CD Rip", advanced=True),
        Group("Tools", (
            Field("tools.ffmpeg", "ffmpeg", "Encodes video.", _key("[tools] ffmpeg"),
                  placeholder="Use AMA's copy", status=_tool_status("ffmpeg")),
            Field("tools.ffprobe", "ffprobe", "Reads each Title's length, tracks and picture.",
                  _key("[tools] ffprobe"), placeholder="Use AMA's copy",
                  status=_tool_status("ffprobe")),
            Field("tools.cyanrip", "cyanrip", "Rips CDs.", _key("[tools] cyanrip"),
                  placeholder="Use AMA's copy", status=_tool_status("cyanrip")),
            Field("tools.makemkvcon", "MakeMKV",
                  "Rips DVDs and Blu-rays. It's yours to install and register; AMA never does "
                  "either.", _key("[tools] makemkvcon"), placeholder="Find the installed MakeMKV",
                  status=_tool_status("makemkvcon")),
            Field("tools.dir", "Tools folder",
                  "Where AMA keeps its copies. The first start needs internet and about 0.5 GB.",
                  _key("[tools] dir"), placeholder=r"%LOCALAPPDATA%\ama\tools"),
        ), note="Checked when AMA starts · used after a restart", advanced=True,
            intro="AMA downloads its own checked copies of ffmpeg and cyanrip. Give a full path "
                  "only to use your own copy instead; it's used as-is."),
    )),
    Section("archive/encode", "archive", "Encode", (
        Group("Encoder", (
            PerType("enc-q", "Quality and size", "Quality",
                    tuple((n, f"encode.cq.{k}") for n, k in _DISC_TYPES),
                    hint="Lower numbers keep more detail and make bigger files; 18 to 24 suits "
                         "most Discs. Archives are kept for good, so settle these before you "
                         "archive a lot.",
                    tech=Markup("Constant quality (CQ), 0 to 51. ")
                    + _key("[encode.cq] dvd", "bd", "uhd")),
        ), live=True, note="Used for Encodes that haven't started"),
    ), note="Changes apply to Discs whose Encode hasn't started."),
    Section("archive/libraries", "archive", "Libraries", (
        Group("Plex connection", (
            Field("plex.url", "Plex server",
                  "Where Plex runs, with its port. Plex normally uses 32400."),
            Field("plex.token", "Plex sign-in token",
                  "Lets AMA tell Plex to look for new files as soon as a Disc is filed. "
                  "Without it, Plex finds them on its next scheduled scan.",
                  "Plex calls it the X-Plex-Token."),
            Field("plex.nas_path", "Share path seen by Plex",
                  "Only if Plex runs on another machine: where that machine sees the NAS share. "
                  "Leave empty when Plex sees the same path as AMA.",
                  placeholder="Same as the NAS share"),
        ), live=True, status=_plex_status),
    ), note=Markup("A Job goes to its kind's default unless you pick another Library in its "
                   "settings before it's filed. Each Library saves on its own, to "
                   "<code>ama.toml</code>."), note_only=True,
        template="partials/settings_libraries.html", context=settings_libraries.context,
        owns=("libraries",), foot="Plex connection"),
    Section("archive/nas", "archive", "NAS", (
        Group("NAS share", (
            Field("nas.unc", "Share",
                  r"The shared folder on your NAS that holds your Libraries, like \\nas\media. "
                  "AMA connects when it starts and keeps trying while it can't.",
                  Markup("Connected with Windows' <code>net use</code>.")),
            Field("nas.username", "Username",
                  "Leave empty to connect as the Windows user AMA runs as.",
                  placeholder="Logged-on Windows user"),
            Field("nas.password", "Password", "Once saved it's never shown again."),
            Field("nas.retry_seconds", "Try again every",
                  "How often AMA tries again while it can't reach the NAS.", unit="seconds"),
        ), status=_nas_status),
    )),
    Section("archive/identification", "archive", "Identification", (
        Group("TMDB", (
            Field("tmdb.api_key", "TMDB API key",
                  "Lets AMA recognise films and TV series using The Movie Database. Without it "
                  "every video Disc goes to Review with no suggestions.",
                  'The v3 "API Key" from your TMDB account settings.'),
        ), live=True, note="Used from the next Identification"),
    )),
    Section("alerts", "alerts", "Alerts", (
        Group("Discord", (
            Field("discord.webhook_url", "Webhook URL",
                  "Posts to a Discord channel when a Disc needs Review, is done or failed. "
                  "Empty turns Discord off."),
        ), live=True, note="Used from the next alert"),
        Group("ntfy", (
            Field("ntfy.url", "Server",
                  "The ntfy server your phone's ntfy app listens to. https://ntfy.sh is the "
                  "free public one."),
            Field("ntfy.topic", "Topic",
                  "Anyone who knows the topic can read your alerts, so it's kept like a "
                  "password. Empty turns ntfy off."),
        ), live=True, note="Used from the next alert"),
    ), note=Markup("Alerts go out when a Disc needs Review, is filed (“insert the next one”) "
                   "or failed. Plex scans are set under <a href=\"/settings/archive/libraries\">"
                   "Archive › Libraries</a>.")),
]

BY_SLUG: dict[str, Section] = {s.slug: s for s in SECTIONS}


def first_of(tab: str) -> Section:
    return next(s for s in SECTIONS if s.tab == tab)


def label_of(key: str) -> str:
    """'Port (General)': how the restart banner names a saved key."""
    for s in SECTIONS:
        for g in s.groups:
            for r in g.rows:
                if key in set(r.keys()):
                    name = r.label
                    if isinstance(r, PerType):
                        name += f", {next(n for n, k in r.rows if k == key)}"
                    where = f"{dict(TABS)[s.tab]} › {s.name}" if s.sub else s.name
                    return f"{name} ({where})"
    return key
