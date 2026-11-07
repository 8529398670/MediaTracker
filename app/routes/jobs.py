"""Background jobs: anyone signed in can see what is running (it explains
why posters are appearing); only an admin can start or stop one. That is a
deliberate exception to "features are for everyone": each of these jobs can
make thousands of outbound calls, and that is a decision about the server,
not about one person's list."""
from __future__ import annotations

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from app.jobs import runner
from app.reference.images import CACHE
from app.routes.helpers import bad_request, error, get_config, not_found
from app.routes.titles import _body


async def list_jobs(request: Request) -> Response:
    return JSONResponse({"jobs": runner.statuses(), "images": CACHE.stats(), "network": get_config(request).providers.network})


async def start_job(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    job = runner.REGISTRY.get(request.path_params["name"])
    if job is None or not job.manual:
        return not_found("no such job")
    if not get_config(request).providers.network:
        return error(503, "lookups_off")
    options = {key: value for key, value in (body.get("options") or {}).items() if isinstance(key, str)}
    try:
        started = job.start(**options)
    except TypeError:
        return bad_request("unknown option")
    return JSONResponse({"started": started, "job": job.status()})


async def stop_job(request: Request) -> Response:
    body = await _body(request)
    if isinstance(body, Response):
        return body
    job = runner.REGISTRY.get(request.path_params["name"])
    if job is None:
        return not_found("no such job")
    job.stop()
    return JSONResponse({"job": job.status()})
