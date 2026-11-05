"""Logs (DESIGN.md "Logs"): every Run, newest first, and each Run's Steps with their output.

- `/logs` the run list (`?kind=jobs|app`, `?problems=1`, `?before=<ISO time>` for older runs)
- `/logs/runs/{id}` one Run; `/logs/jobs/{job id}` a Job's Run
- `/logs/runs/{id}/live` what the run page polls on each `logs` SSE event: new output for
  its running Steps (out-of-band appends), or a reload once a Step's state changes
- `/logs/steps/{id}/download` a Step's whole output as text
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse, Response

from ama.runs import RunKind
from ama.web import TEMPLATES, view_context
from ama.web.logs_view import bins, run_view, when

router = APIRouter()

PAGE = 100  # runs on one page of the list
_KINDS = {"jobs": [RunKind.JOB],
          "app": [RunKind.APP, RunKind.NAS, RunKind.TOOLS, RunKind.SCRATCH]}


def _services(request: Request):
    return request.app.state.services


@router.get("/logs", response_class=HTMLResponse)
def logs(request: Request, kind: str = "", problems: str = "", before: str = "") -> Response:
    services = _services(request)
    now = datetime.now()
    try:
        cutoff = datetime.fromisoformat(before) if before else None
    except ValueError:
        cutoff = None
    runs = services.runs.list_runs(_KINDS.get(kind), limit=PAGE + 1, before=cutoff)
    more = len(runs) > PAGE
    views = [run_view(services, r, now) for r in runs[:PAGE]]
    if problems:
        views = [v for v in views if v.problem]
    query = {k: v for k, v in (("kind", kind if kind in _KINDS else ""),
                               ("problems", "1" if problems else "")) if v}
    return TEMPLATES.TemplateResponse(request, "logs.html", view_context(services) | {
        "current": "/logs", "bins": bins(views, now.date()), "kind": query.get("kind", ""),
        "problems": bool(problems), "query": query, "now": now, "before": cutoff,
        "keep_days": services.config.logs.keep_days,
        "older": runs[PAGE - 1].started_at.isoformat() if more else None})


def _run_or_404(services, run_id: int):
    run = services.runs.get_run(run_id)
    if run is None:
        raise HTTPException(404, "No such run")
    return run


@router.get("/logs/jobs/{job_id}")
def job_run(request: Request, job_id: int) -> Response:
    services = _services(request)
    if services.jobs.get(job_id) is None:
        raise HTTPException(404, "No such Job")
    return RedirectResponse(f"/logs/runs/{services.runs.job_run(job_id)}", status_code=303)


@router.get("/logs/runs/{run_id}", response_class=HTMLResponse)
def run_page(request: Request, run_id: int) -> Response:
    services = _services(request)
    now = datetime.now()
    view = run_view(services, _run_or_404(services, run_id), now)
    output = {s.stored.id: services.runs.tail(s.stored.id) if s.state == "running"
              else services.runs.output(s.stored.id)
              for s in view.steps if s.has_output and s.stored is not None and not s.removed}
    return TEMPLATES.TemplateResponse(request, "logs_run.html", view_context(services) | {
        "current": "/logs", "v": view, "output": output, "now": now,
        "when": lambda at: when(at, now.date())})


@router.get("/logs/runs/{run_id}/live", response_class=HTMLResponse)
def run_live(request: Request, run_id: int, sig: str = "") -> Response:
    """New output for the page's running Steps (`after_<step id>` = the last line it has)."""
    services = _services(request)
    now = datetime.now()
    view = run_view(services, _run_or_404(services, run_id), now)
    if sig != view.signature:
        return Response(headers={"HX-Refresh": "true"})
    fresh = {}
    for s in view.steps:
        if s.state != "running" or s.stored is None:
            continue
        after = int(request.query_params.get(f"after_{s.stored.id}", "0") or 0)
        fresh[s.stored.id] = [ln for ln in services.runs.tail(s.stored.id) if ln.n > after]
    return TEMPLATES.TemplateResponse(request, "partials/logs_live.html", {
        "v": view, "fresh": fresh, "now": now})


@router.get("/logs/steps/{step_id}/download", response_class=PlainTextResponse)
def download(request: Request, step_id: int) -> Response:
    services = _services(request)
    step = services.runs.get_step(step_id)
    if step is None:
        raise HTTPException(404, "No such step")
    text = "".join(f"{ln.at:%Y-%m-%d %H:%M:%S}  {ln.text}\n"
                   for ln in services.runs.output(step_id))
    name = f"{step.key.replace(':', '-')}-{step.started_at:%Y%m%d-%H%M}.log"
    return PlainTextResponse(text, headers={"Content-Disposition": f'attachment; filename="{name}"'})
