"""The per-Job settings panel (#30, docs/mockups/job-settings-*.html) and its saves.

Each control posts on change to `POST /jobs/{id}/settings` (`key` + `value`, or
`reset`); the answer is the panel body again, with "Saved" by the group's heading, or
a notice when the group locked first and the change wasn't saved."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from ama.encoder_probe import ProbeFailed
from ama.job_settings import Group, GroupState, Locked, Value, setting
from ama.jobs import JobRecord, JobStatus
from ama.web import TEMPLATES

if TYPE_CHECKING:
    from ama.app import Services

router = APIRouter()


@dataclass(frozen=True)
class Option:
    value: str
    label: str
    selected: bool
    disabled: bool = False


@dataclass(frozen=True)
class FieldView:
    v: Value
    options: list[Option] | None  # None: typed text
    default_phrase: str  # "Default Movies", "Blu-ray default 22"

    @property
    def id(self) -> str:
        return "js-" + self.v.setting.key.replace(".", "-")

    @property
    def changed_phrase(self) -> str:
        """For a locked override: "Changed for this Job · default No"."""
        p = self.default_phrase
        return f"Changed for this Job · {p[0].lower() + p[1:] if p.startswith('Default') else p}"


@dataclass(frozen=True)
class GroupView:
    state: GroupState
    fields: list[FieldView]
    unrecorded: bool = False  # filed before AMA kept per-Job settings

    @property
    def group(self) -> Group:
        return self.state.group

    @property
    def locked(self) -> bool:
        return self.state.locked or self.unrecorded


@dataclass(frozen=True)
class JobsetView:
    job: JobRecord
    groups: list[GroupView]

    @property
    def differences(self) -> list[Value]:
        """What differs from the defaults, for the rip card's summary line."""
        return [f.v for g in self.groups for f in g.fields if f.v.overridden]


def _default_phrase(v: Value, job: JobRecord) -> str:
    if v.setting.key == "encode.quality":
        return f"{job.disc_type.long_name} default {v.default_text}"
    return f"Default {v.default_text}"


def _options(services: Services, v: Value, choices) -> list[Option]:
    key = v.setting.key
    if key == "encode.quality":  # a window around the default and the value, not all 52
        lo = max(0, min(int(v.default), int(v.value)) - 4)
        hi = min(51, max(int(v.default), int(v.value)) + 4)
        choices = [(c, label) for c, label in choices if lo <= int(c) <= hi]
    out = []
    for value, label in choices:
        disabled = (key == "encode.encoder" and value != v.value
                    and isinstance(services.encoders.states.get(value), ProbeFailed))
        if disabled:
            label += " (not available on this PC)"
        elif key == "encode.speed" and value == v.default:
            label += " (default)"
        out.append(Option(value, label, value == v.value, disabled))
    return out


def jobset_view(services: Services, job: JobRecord | int | None) -> JobsetView | None:
    if isinstance(job, int):
        job = services.jobs.get(job)
    if job is None or services.job_settings is None:
        return None
    scope = services.job_settings.scope(job)
    groups = []
    for state in services.job_settings.groups(job):
        fields = [FieldView(v, None if v.setting.choices is None or state.locked else
                            _options(services, v, v.setting.choices(scope)),
                            _default_phrase(v, job)) for v in state.values]
        groups.append(GroupView(state, fields,
                                unrecorded=not state.locked and job.status == JobStatus.FILED))
    return JobsetView(job, groups)


def _job(services: Services, job_id: int) -> JobRecord:
    job = services.jobs.get(job_id)
    if job is None:
        raise HTTPException(404, "No such Job")
    return job


@router.post("/jobs/{job_id}/settings", response_class=HTMLResponse)
def save(request: Request, job_id: int, key: str = Form(""), value: str = Form(""),
         reset: str = Form(""), summary: str = Form("")) -> Response:
    services = request.app.state.services
    job = _job(services, job_id)
    settings = services.job_settings
    target = reset or key
    found = setting(target)
    saved: Group | None = None
    refused: Locked | None = None
    error: str | None = None
    try:
        if reset:
            settings.reset(job_id, reset)
        else:
            settings.set(job_id, key, value)
        saved = found.group if found else None
    except Locked as e:
        refused = e
    except ValueError as e:
        error = str(e)
    if "hx-request" not in request.headers:
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)
    label = found.label if found else target
    ctx = {"jobset": jobset_view(services, job), "saved": saved, "refused": refused,
           "error": error, "changed": label, "summary": bool(summary), "oob_summary": bool(summary)}
    return TEMPLATES.TemplateResponse(request, "partials/job_settings_body.html", ctx)
