"""Background jobs: anyone signed in can see what is running (it explains
why posters are appearing); only an admin can start or stop one. That is a
deliberate exception to "features are for everyone": each of these jobs can
make thousands of outbound calls, and that is a decision about the server,
not about one person's list."""
from __future__ import annotations

from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.core.config import Config
from app.jobs import runner
from app.reference.images import CACHE
from app.routes.helpers import Refused, get_config
from app.routes.titles import _body


def jobs_payload(cfg: Config) -> dict[str, Any]:
    """GET /api/jobs, shared with MCP."""
    return {"jobs": runner.statuses(), "images": CACHE.stats(), "network": cfg.providers.network}


async def list_jobs(request: Request) -> Response:
    return JSONResponse(jobs_payload(get_config(request)))


def start_job_checked(cfg: Config, name: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST /api/jobs/{name}/start, shared with MCP."""
    job = runner.REGISTRY.get(name)
    if job is None or not job.manual:
        raise Refused(404, "no such job")
    if not cfg.providers.network:
        raise Refused(503, "lookups_off")
    options = {key: value for key, value in (body.get("options") or {}).items() if isinstance(key, str)}
    try:
        started = job.start(**options)
    except TypeError:
        raise Refused(400, "unknown option") from None
    return {"started": started, "job": job.status()}


async def start_job(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        return JSONResponse(start_job_checked(get_config(request), request.path_params["name"], body))
    except Refused as refused:
        return refused.response()


def stop_job_checked(name: str) -> dict[str, Any]:
    """POST /api/jobs/{name}/stop, shared with MCP."""
    job = runner.REGISTRY.get(name)
    if job is None:
        raise Refused(404, "no such job")
    job.stop()
    return {"job": job.status()}


async def stop_job(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    try:
        return JSONResponse(stop_job_checked(request.path_params["name"]))
    except Refused as refused:
        return refused.response()
