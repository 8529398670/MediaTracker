"""Background jobs: anyone signed in can see what is running (it explains
why posters are appearing); only an admin can start or stop one. That is a
deliberate exception to "features are for everyone": each of these jobs can
make thousands of outbound calls, and that is a decision about the server,
not about one person's list."""
from __future__ import annotations

from typing import Annotated, Any

from msgspec import Meta
from starlette.requests import Request

from app.apidocs import ADMIN, PATH, Reply, route
from app.apidocs import Request as RequestType
from app.jobs import runner
from app.reference.images import CACHE
from app.routes.helpers import Refused, get_config

TAG = "Jobs"


class Jobs(Reply, kw_only=True):
    jobs: Annotated[list[dict[str, Any]], Meta(description="Each job's name, whether it runs by hand (manual), and what it is doing.")]
    images: Annotated[dict[str, Any], Meta(description="The poster cache.")]
    network: Annotated[bool, Meta(description="providers.network: whether lookups are on.")]


@route(
    "GET /api/jobs", summary="Background jobs",
    tag=TAG,
    description="What the server is doing in the background (filling in titles, IMDb ratings, the "
    "catalogue), the poster cache, and whether lookups are on.",
    mcp="jobs_status", read_only=True,
)
def list_jobs(request: Request) -> Jobs:
    return Jobs(jobs=runner.statuses(), images=CACHE.stats(), network=get_config(request).providers.network)


class JobPath(RequestType, kw_only=True):
    name: Annotated[str, PATH, Meta(description="A job's name, from GET /api/jobs.")]


class StartJob(JobPath, kw_only=True):
    options: Annotated[dict[str, Any], Meta(description="The job's own settings.")] = {}


class JobStarted(Reply, kw_only=True):
    started: bool
    job: dict[str, Any]


@route(
    "POST /api/jobs/{name}/start", summary="Start a job",
    tag=TAG, role=ADMIN, errors=(404, 503),
    description="Start a background job by its name (one marked manual). options are the job's own "
    "settings. Each job can make thousands of outbound calls.",
    mcp="admin_start_job",
)
def start_job(request: Request, body: StartJob) -> JobStarted:
    job = runner.REGISTRY.get(body.name)
    if job is None or not job.manual:
        raise Refused(404, "no such job")
    if not get_config(request).providers.network:
        raise Refused(503, "lookups_off")
    try:
        started = job.start(**body.options)
    except TypeError:
        raise Refused(400, "unknown option") from None
    return JobStarted(started=started, job=job.status())


class JobReply(Reply, kw_only=True):
    job: dict[str, Any]


@route(
    "POST /api/jobs/{name}/stop", summary="Stop a job",
    tag=TAG, role=ADMIN, errors=(404,),
    description="Ask a running background job to stop.",
    mcp="admin_stop_job",
)
def stop_job(request: Request, body: JobPath) -> JobReply:
    job = runner.REGISTRY.get(body.name)
    if job is None:
        raise Refused(404, "no such job")
    job.stop()
    return JobReply(job=job.status())
