"""This project's one opinionated serving rule: markup and code are never
stale, images are cached hard.

Text assets (.html/.css/.js/...) are read on every request and sent with
Cache-Control: private, no-cache and an ETag. The browser keeps its copy but
asks again on every load; an unchanged file is answered 304 with no body, a
changed one with the new bytes, gzipped. A deploy is therefore live on the
next load, with no content hashing, no ?v=123 query strings, and no
cache-busting build step to keep in sync -- and a repeat load downloads only
what changed.

Images and other binaries get the opposite treatment. Gzip does nothing for
already-compressed formats, and nobody wants a photo re-downloaded on every
page view, so those get a long max-age.

That trade-off is the whole reason this module exists instead of Starlette's
StaticFiles.
"""
from __future__ import annotations

import gzip
import hashlib
import mimetypes
import posixpath
import re
from pathlib import Path

from starlette.concurrency import run_in_threadpool
from starlette.requests import Request
from starlette.responses import FileResponse, PlainTextResponse, Response

from app.core import error_page

# Extensions that are text, change often, and must never go stale.
ALWAYS_FRESH_EXTENSIONS = {
    ".html", ".htm", ".css", ".js", ".mjs", ".json", ".svg", ".txt", ".map",
    ".xml", ".webmanifest", ".yaml", ".yml",
}

BINARY_CACHE_SECONDS = 60 * 60 * 24 * 7  # 7 days

# The paths of the app's screens and cards, as index.html declares them
# (<section class="view" data-view="users" data-path="/admin/users">).
SCREEN_PATH = re.compile(r'data-path="/([a-z0-9-]+(?:/[a-z0-9-]+)*)"')

# The signed-out page says why someone is there by its path: a login link that
# did not work, a sign-in that took too long, a session that ended.
SIGNED_OUT_PATHS = frozenset({"signed-out/invalid", "signed-out/expired", "signed-out/ended"})

# The platform's MIME table varies; these are the ones the frontend relies on.
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/json", ".map")
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("application/yaml", ".yaml")
mimetypes.add_type("application/yaml", ".yml")
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")


def has_dot_dot(request_path: str) -> bool:
    """Spot a parent-directory segment in the raw request.

    The resolved-path check in resolve() is the real guarantee -- nothing can
    escape the root without it. This exists so such a request answers 404
    directly instead of being looked up as a screen path, which is
    clearer to whoever reads the access log, and so the intent is stated
    rather than left implicit."""
    return ".." in request_path.replace("\\", "/").split("/")


def has_dot_file(cleaned: str) -> bool:
    """Spot a segment that starts with a dot: .env, .git/config, .htpasswd,
    an editor's swap file. Nothing the app serves is named like that, and a
    directory that ends up served by mistake is exactly where such files are,
    so they are never served -- defense in depth behind the startup check
    (assets.check_static_dir). .well-known/ is the exception: it is public
    by definition (RFC 8615)."""
    segments = cleaned.split("/")
    if segments and segments[0] == ".well-known":
        segments = segments[1:]
    return any(segment.startswith(".") for segment in segments)


def etag(body: bytes) -> str:
    """The validator for a text asset: a hash of its bytes, so it changes
    exactly when the file does. Weak, because the gzipped and plain replies
    carry the same tag."""
    return 'W/"' + hashlib.blake2b(body, digest_size=8).hexdigest() + '"'


def etag_matches(header: str, tag: str) -> bool:
    """If-None-Match's weak comparison: any listed tag equal to ours once the
    W/ prefixes are set aside, or "*"."""
    want = tag.removeprefix("W/")
    for candidate in header.split(","):
        candidate = candidate.strip()
        if candidate == "*" or candidate.removeprefix("W/") == want:
            return True
    return False


def content_type(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


def _not_found(request: Request) -> Response:
    """A browser gets the error page. A stylesheet or script tag keeps plain
    text, which is what makes a missing asset easy to read in the console."""
    if error_page.wanted(request):
        return error_page.response(request, 404)
    return PlainTextResponse("Not found", status_code=404)


class StaticServer:
    def __init__(self, root: Path, index_file: str = "index.html") -> None:
        self.root = root.resolve()
        self.index_file = index_file
        # index.html's paths, kept until the file changes.
        self._screens: tuple[int, frozenset[str]] = (-1, frozenset())

    def resolve(self, request_path: str) -> Path | None:
        """Turn a request path into a file path under the root, or None. The
        final check verifies where the path actually landed (after symlinks)
        rather than trying to blocklist how it got there.

        Every file this server sends comes through here, index.html for a
        screen path included -- a path built by hand and served without this
        check is how a symlinked static/index.html pointing at ../config/config.yaml
        would reach a visitor. Static content should still be writable only by
        whoever deploys the app: the check runs before the read, so a writer
        able to swap a file for a symlink between the two could still win."""
        if has_dot_dot(request_path):
            return None
        cleaned = posixpath.normpath("/" + request_path.replace("\\", "/")).lstrip("/")
        if cleaned in ("", ".") or has_dot_file(cleaned):
            return None
        candidate = (self.root / cleaned).resolve()
        if not candidate.is_relative_to(self.root):
            return None
        return candidate

    def screen_paths(self) -> frozenset[str]:
        """The paths index.html declares with data-path, without the leading
        slash. Read again whenever the file changes, so a pruned feature or a
        new screen needs nothing registered here."""
        path = self.resolve(self.index_file)
        try:
            stamp = path.stat().st_mtime_ns if path is not None else -1
            if stamp != self._screens[0]:
                found = frozenset(SCREEN_PATH.findall(path.read_text(encoding="utf-8")))
                self._screens = (stamp, found)
        except OSError:
            return frozenset()
        return self._screens[1]

    def _read_text_asset(self, path: Path, accepts_gzip: bool, if_none_match: str) -> tuple[bytes | None, str, bool]:
        """The body to send (None for a 304), its tag, and whether it is gzipped.
        The tag is compared before gzipping: an unchanged file costs neither
        the bytes nor the CPU."""
        body = path.read_bytes()
        tag = etag(body)
        if if_none_match and etag_matches(if_none_match, tag):
            return None, tag, False
        if not accepts_gzip:
            return body, tag, False
        # Fastest level: this runs on every request, and most of the saving
        # comes from the first pass anyway.
        return gzip.compress(body, compresslevel=1), tag, True

    async def endpoint(self, request: Request) -> Response:
        """The catch-all. Registered last: it matches everything, so any route
        declared after it is unreachable."""
        request_path = request.path_params.get("path", "")
        page = request_path.strip("/")
        if request_path == "" or request_path.endswith("/"):
            request_path = posixpath.join(request_path, self.index_file)

        # No blanket fallback to index.html. Each screen is a path
        # (/admin/users) that index.html declares; those, and the signed-out
        # reasons, get index.html, and anything else is a real 404. The pages
        # with a credential in the path have their own routes (/login/...,
        # /join/...).
        path = self.resolve(request_path)
        if (path is None or not path.is_file()) and (page in SIGNED_OUT_PATHS or page in await run_in_threadpool(self.screen_paths)):
            path = self.resolve(self.index_file)
        if path is None or not path.is_file():
            return _not_found(request)

        return await self._send(request, path)

    async def serve_join_page(self, request: Request) -> Response:
        """An invite link's page. While auth.invite_links is off a person with
        an old link gets the styled 404, not RequireInviteLinks's JSON."""
        if not request.app.state.settings.get().invite_links_enabled:
            response = _not_found(request)
            # The credential is in this URL too.
            response.headers["referrer-policy"] = "no-referrer"
            return response
        return await self.serve_login_page(request)

    async def serve_docs_page(self, request: Request) -> Response:
        """/docs/api and /docs/mcp: docs.html, which reads its own path to
        pick the file and shows an error for any other /docs/ path. The page
        itself is public, like index.html; the Markdown it fetches needs a
        sign-in."""
        path = self.resolve("docs.html")
        if path is None or not path.is_file():
            return _not_found(request)
        # no-store, like every route in the table rather than the files
        # behind the catch-all.
        response = await self._send(request, path, keep=False)
        response.headers["referrer-policy"] = "no-referrer"
        response.headers["x-robots-tag"] = "noindex"
        return response

    async def serve_login_page(self, request: Request) -> Response:
        """A login link (or an invite link) opens the ordinary app page,
        which sees the /login/ (or /join/) path and asks the person to confirm
        -- nothing is redeemed by the GET. See app/routes/auth.py and
        app/routes/join.py."""
        path = self.resolve(self.index_file)
        if path is None or not path.is_file():
            return _not_found(request)
        # The credential is in this page's URL: not even the browser keeps a
        # copy filed under it.
        response = await self._send(request, path, keep=False)
        # The credential is in this page's URL; make sure no request the page
        # makes carries it onward in a Referer header.
        response.headers["referrer-policy"] = "no-referrer"
        return response

    async def _send(self, request: Request, path: Path, keep: bool = True) -> Response:
        """Serve a file resolve() has already approved, by the caching rule at
        the top of this module. keep=False is for the pages routes serve (one
        whose URL holds a credential, the docs page): no-store, no tag."""
        if path.suffix.lower() not in ALWAYS_FRESH_EXTENSIONS:
            return FileResponse(
                path,
                headers={"cache-control": f"public, max-age={BINARY_CACHE_SECONDS}", "vary": "Accept-Encoding"},
            )

        accepts_gzip = "gzip" in request.headers.get("accept-encoding", "")
        if_none_match = request.headers.get("if-none-match", "") if keep else ""
        try:
            body, tag, compressed = await run_in_threadpool(self._read_text_asset, path, accepts_gzip, if_none_match)
        except OSError:
            return _not_found(request)
        # private: the browser keeps it, a proxy or CDN never does (see the
        # no-store middleware). no-cache: the browser asks again every load.
        headers = {"cache-control": "private, no-cache", "vary": "Accept-Encoding", "etag": tag}
        if not keep:
            headers = {"cache-control": "no-store, private", "vary": "Accept-Encoding"}
        if body is None:
            return Response(status_code=304, headers=headers)
        if compressed:
            headers["content-encoding"] = "gzip"
        return Response(body, media_type=content_type(path), headers=headers)
