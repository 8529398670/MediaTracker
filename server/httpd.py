"""The HTTP surface: static files, the JSON API, and the image proxy.

Everything above this module is ignorant of HTTP; everything here is a thin
translation between requests and the library, the providers and the enricher.
"""

from __future__ import annotations

import gzip
import json
import mimetypes
import socket
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import auth
from config import (BASE_HEADERS, COMPRESSIBLE, EXTRA_TYPES, IMG_ALLOW_ANY,
                    ITEM_TYPES, LIBRARY_PATH, LOOKUP_AS, MAX_BODY, NET_ENABLED, OMDB_KEY,
                    PUBLIC_DIR, PUBLIC_URL, SCHEMA, TMDB_KEY, UA, VERSION,
                    env_flag, log)
from enrich import ENRICHER, Enricher
from library import LIBRARY
import lists
import imgcache
from netio import IMG_HOSTS, OUTBOUND_LIMIT, smaller_img
from normalize import _int, _s
from providers import lookup, lookup_detail
from resolve import identify, resolve
import verdicts


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def version_string(self) -> str:  # do not advertise Python/BaseHTTP versions
        return "mediatracker"

    def log_message(self, fmt: str, *args: object) -> None:
        if env_flag("MT_ACCESS_LOG", False):
            log(self.address_string(), fmt % args)

    # -- plumbing ------------------------------------------------------

    def _accepts_gzip(self) -> bool:
        return "gzip" in (self.headers.get("Accept-Encoding") or "").lower()

    def _send(self, status: int, body: bytes | str = b"", ctype: str = "text/plain; charset=utf-8",
              headers: dict | None = None, compress: bool = True) -> None:
        if isinstance(body, str):
            body = body.encode("utf-8")
        out = dict(BASE_HEADERS)
        if headers:
            out.update(headers)
        # A None means "this base header does not apply here" — artwork is
        # immutable and must not inherit the global no-store.
        out = {k: v for k, v in out.items() if v is not None}
        if compress and len(body) >= 400 and self._accepts_gzip() \
                and ctype.split(";")[0].strip() in COMPRESSIBLE:
            body = gzip.compress(body, 6, mtime=0)
            out["Content-Encoding"] = "gzip"
        out["Vary"] = "Accept-Encoding"
        out["Content-Type"] = ctype
        out["Content-Length"] = str(len(body))
        try:
            self.send_response(status)
            for key, value in out.items():
                self.send_header(key, value)
            self.end_headers()
            if self.command != "HEAD" and body:
                self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _json(self, status: int, payload: object, headers: dict | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        self._send(status, body, "application/json; charset=utf-8", headers)

    def _fail(self, status: int, message: str) -> None:
        self._json(status, {"error": message, "status": status})

    def _body(self) -> object | None:
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            self._fail(400, "bad content-length")
            return None
        if length < 0 or length > MAX_BODY:
            self.close_connection = True
            self._fail(413, "request body too large")
            return None
        raw = self.rfile.read(length) if length else b""
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._fail(400, "body must be JSON")
            return None

    # -- who is asking -------------------------------------------------

    def _cookie(self, name: str) -> str:
        for part in (self.headers.get("Cookie") or "").split(";"):
            key, _, value = part.strip().partition("=")
            if key == name:
                return value.strip()
        return ""

    def _https(self) -> bool:
        """Came in over https — through the tunnel, which says so."""
        proto = (self.headers.get("X-Forwarded-Proto") or "").lower()
        return proto == "https" or '"https"' in (self.headers.get("CF-Visitor") or "")

    def _session_cookie(self, token: str) -> str:
        # Lax, not Strict: a Strict cookie is left off a link followed from
        # another site, so opening the app from a message would bounce you to
        # Google. Secure only over https — a browser on the LAN address would
        # otherwise refuse to keep it at all.
        return (f"{auth.COOKIE}={token}; Path=/; Max-Age={auth.COOKIE_AGE}; HttpOnly; "
                f"SameSite=Lax{'; Secure' if self._https() else ''}")

    def _client(self) -> str:
        """Who is knocking, for the throttle. Behind the tunnel every request
        comes from the same address, and the tunnel names the real one."""
        forwarded = (self.headers.get("CF-Connecting-IP")
                     or (self.headers.get("X-Forwarded-For") or "").split(",")[0]).strip()
        return forwarded or (self.client_address[0] if self.client_address else "?")

    def _navigating(self) -> bool:
        """A page being opened, as opposed to a script, a poster or a fetch."""
        mode = self.headers.get("Sec-Fetch-Mode")
        if mode:
            return mode == "navigate"
        return "text/html" in (self.headers.get("Accept") or "")

    def _same_origin(self) -> bool:
        """Whether a write came from this app's own pages.

        SameSite keeps the cookie off a cross-site POST, but not off one from
        another port on the same host — and on the LAN, every app on this box
        is the same host. The browser says where a request came from; anything
        that says somewhere else is refused.
        """
        site = self.headers.get("Sec-Fetch-Site")
        if site:
            return site in ("same-origin", "none")
        origin = self.headers.get("Origin")
        if not origin:
            return True                 # not a browser: nothing ambient to abuse
        hosts = {self.headers.get("Host") or "", self.headers.get("X-Forwarded-Host") or ""}
        return urllib.parse.urlsplit(origin).netloc in hosts - {""}

    # -- verbs ---------------------------------------------------------

    def do_GET(self) -> None:
        self._route("GET")

    def do_HEAD(self) -> None:
        self._route("GET")

    def do_POST(self) -> None:
        self._route("POST")

    def do_PUT(self) -> None:
        self._route("PUT")

    def do_PATCH(self) -> None:
        self._route("PATCH")

    def do_DELETE(self) -> None:
        self._route("DELETE")

    def do_OPTIONS(self) -> None:
        self._send(204, b"", "text/plain", {"Allow": "GET, HEAD, POST, PUT, PATCH, DELETE"})

    # -- routing -------------------------------------------------------

    def _route(self, method: str) -> None:
        parsed = urllib.parse.urlsplit(self.path)
        path = urllib.parse.unquote(parsed.path)
        query = urllib.parse.parse_qs(parsed.query)

        # One handler can serve several requests on a kept-alive connection,
        # so who is asking is worked out afresh every time.
        self.token = self._cookie(auth.COOKIE)
        self.user = None

        try:
            self.user = auth.ACCOUNTS.user_for(self.token) if self.token else None
            if method != "GET" and not self._same_origin():
                self._fail(403, "refused: that came from another site")
            elif path == "/login" and method == "GET":
                # A login link's page is the same whoever opens it: the one
                # opening it may be signed in as somebody else already.
                self._gate()
            elif self.user is None:
                self._stranger(method, path)
            elif path.startswith("/api/"):
                self._api(method, path, query)
            elif method == "GET":
                self._static(path)
            else:
                self._fail(405, "method not allowed")
        except Exception as exc:  # never leak a traceback to the client
            log(f"!! {method} {path}: {type(exc).__name__}: {exc}")
            self._fail(500, "internal error")

    # -- without a session ---------------------------------------------

    def _stranger(self, method: str, path: str) -> None:
        """All that anyone without a session gets: a way in, and Google."""
        if path == "/api/health":
            # The container's own health check. It says nothing but "up".
            self._json(200, {"ok": True})
        elif path in auth.OPEN_FILES and method == "GET":
            self._static(path)
        elif path.startswith("/api/auth/") and method == "POST":
            self._api_auth(method, [p for p in path.split("/") if p][1:])
        elif self._navigating():
            self._gate()
        elif path.startswith("/api/"):
            self._fail(401, "sign in first")
        else:
            self._send(302, b"", "text/plain", {"Location": auth.AWAY})

    def _gate(self) -> None:
        """The page a browser without a session is given in place of any other.

        No app and no data in it: one script, which spends a login link if
        there is one in the address, or hands back the session this browser
        kept in localStorage if its cookie went missing — and otherwise
        leaves for Google, which is all a stranger ever sees.
        """
        target = self._resolve("/gate.html")
        try:
            body = target.read_bytes() if target else b""
        except OSError:
            body = b""
        self._send(200, body, "text/html; charset=utf-8")

    def _api(self, method: str, path: str, query: dict) -> None:
        parts = [p for p in path.split("/") if p][1:]  # drop "api"
        head = parts[0] if parts else ""

        if head == "health":
            self._json(200, {"ok": True, "version": VERSION, **LIBRARY.meta()})
            return

        if head == "auth":
            self._api_auth(method, parts)
            return

        if head == "config":
            self._json(200, {
                "me": self.user,
                "publicUrl": PUBLIC_URL,
                "version": VERSION,
                "schema": SCHEMA,
                "network": NET_ENABLED,
                "providers": {
                    "tmdb": bool(TMDB_KEY), "omdb": bool(OMDB_KEY),
                    "itunes": True, "tvmaze": True, "openlibrary": True, "wikipedia": True,
                },
                "dataPath": str(LIBRARY_PATH),
            })
            return

        if head == "library":
            self._api_library(method, parts, query)
            return

        if head == "enrich":
            if method == "GET":
                self._json(200, ENRICHER.status())
                return
            if method == "POST":
                payload = self._body()
                if payload is None:
                    return
                body = payload if isinstance(payload, dict) else {}
                action = _s(body.get("action"), 16) or "start"
                if action == "stop":
                    self._json(200, ENRICHER.stop())
                    return
                scope = _s(body.get("scope"), 16) or "missing"
                if scope not in Enricher.SCOPES:
                    scope = "missing"
                # Named titles, for filling in something just added rather
                # than sweeping the whole library for it.
                raw_ids = body.get("ids")
                ids = tuple(_s(i, 64) for i in raw_ids[:200]
                            if _s(i, 64)) if isinstance(raw_ids, list) else ()
                self._json(200, ENRICHER.start(
                    scope, _int(body.get("limit"), 0, 100000) or 0, ids))
                return
            self._fail(405, "GET or POST")
            return

        # The harvested Wikipedia lists: what has been collected, how to
        # collect more, and the merged catalogue to browse.
        if head == "lists":
            self._api_lists(method, parts, query)
            return

        # What you have said about a film in those lists that is not yours.
        if head == "verdicts":
            payload = self._body() if method == "POST" else None
            if method == "POST" and payload is None:
                return
            self._api_verdicts(method, payload)
            return

        if head == "resolve":
            if not OUTBOUND_LIMIT.allow(self.client_address[0] if self.client_address else "?"):
                self._fail(429, "slow down")
                return
            if method == "GET":
                text = (query.get("q") or [""])[0]
            elif method == "POST":
                payload = self._body()
                if payload is None:
                    return
                body = payload if isinstance(payload, dict) else {}
                text = _s(body.get("text") or body.get("q"), 600)
                query = {**query,
                         "type": [_s(body.get("type"), 16) or (query.get("type") or ["any"])[0]],
                         "limit": [str(body.get("limit") or (query.get("limit") or ["8"])[0])]}
            else:
                self._fail(405, "GET or POST")
                return
            text = _s(text, 600)
            if not text:
                self._fail(400, "q is required")
                return
            kind = (query.get("type") or ["any"])[0][:32]
            # One of Other's own types asks the way its list says to.
            kind = LIBRARY.lookup_for(kind) or kind
            if kind not in ITEM_TYPES:
                kind = "any"
            limit = max(1, min(_int((query.get("limit") or ["8"])[0], 1, 20) or 8, 20))
            self._json(200, resolve(text, kind, limit))
            return

        # What a pasted link is, without going and asking anyone. Free, and
        # instant, so the importer can label a link as you paste it.
        if head == "identify":
            self._json(200, identify(_s((query.get("q") or [""])[0], 600)))
            return

        if head in ("lookup", "img"):
            if not OUTBOUND_LIMIT.allow(self.client_address[0] if self.client_address else "?"):
                self._fail(429, "slow down")
                return
            if head == "img":
                self._api_img(query)
            elif len(parts) > 1 and parts[1] == "detail":
                source = (query.get("source") or [""])[0][:24]
                ref = (query.get("id") or [""])[0][:64]
                self._json(200, lookup_detail(source, ref))
            else:
                term = (query.get("q") or [""])[0].strip()[:200]
                if not term:
                    self._fail(400, "q is required")
                    return
                kind = (query.get("type") or ["any"])[0][:32]
                kind = LIBRARY.lookup_for(kind) or LOOKUP_AS.get(kind, kind)
                limit = max(1, min(_int((query.get("limit") or ["12"])[0], 1, 40) or 12, 40))
                self._json(200, lookup(term, kind, limit))
            return

        self._fail(404, "no such endpoint")

    # -- people ----------------------------------------------------------

    def _api_auth(self, method: str, parts: list[str]) -> None:
        """Signing in and out, and the people who can.

        Everyone signed in may do all of it — there are no roles, only names.
        """
        one = parts[1] if len(parts) > 1 else ""

        # The two ways in, open to anyone, since getting in is what they are for.
        if one in ("redeem", "resume") and method == "POST":
            who = self._client()
            if auth.THROTTLE.blocked(who):
                self._fail(429, "slow down")
                return
            payload = self._body()
            if payload is None:
                return
            given = _s((payload if isinstance(payload, dict) else {}).get("token"), 200)
            if one == "redeem":
                self._redeem(given, who)
            else:
                self._resume(given, who)
            return

        if self.user is None:
            self._fail(401, "sign in first")
            return

        if one == "me" and method == "GET":
            self._json(200, self.user)
            return

        if one == "logout" and method == "POST":
            auth.ACCOUNTS.end(self.token)
            log(f"auth: {self.user['name']} signed out of a browser")
            self._json(200, {"ok": True}, {"Set-Cookie": (
                f"{auth.COOKIE}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
                f"{'; Secure' if self._https() else ''}")})
            return

        if one == "users":
            self._api_users(method, parts[2:])
            return

        # /api/auth/links/<id> — cancel a link nobody has opened yet.
        if one == "links" and method == "DELETE" and len(parts) > 2:
            ok = auth.ACCOUNTS.revoke(parts[2])
            if ok:
                log(f"auth: {self.user['name']} cancelled an unused login link")
            self._json(200 if ok else 404, {"ok": ok})
            return

        self._fail(404, "no such endpoint")

    def _redeem(self, token: str, who: str) -> None:
        """A login link, opened. It is spent whether or not this goes well."""
        got = auth.ACCOUNTS.redeem(token, self.headers.get("User-Agent") or "")
        if not got:
            auth.THROTTLE.fail(who)
            self._fail(401, "that link has been used, or has lapsed")
            return
        session, user = got
        # The browser was signed in already: that session is over, not left
        # behind as a device nobody is using.
        if self.user:
            auth.ACCOUNTS.end(self.token)
        log(f"auth: {user['name']} signed in with a login link")
        # The token goes back in the body as well as the cookie, for the page
        # to keep in localStorage — the one copy that outlives a lost cookie.
        self._json(200, {"token": session, "name": user["name"]},
                   {"Set-Cookie": self._session_cookie(session)})

    def _resume(self, token: str, who: str) -> None:
        """Put back a session this browser kept, or confirm the one it has."""
        user = auth.ACCOUNTS.user_for(token) if token else None
        if user:
            self._json(200, {"name": user["name"]},
                       {"Set-Cookie": self._session_cookie(token)})
            return
        if self.user:
            self._json(200, {"name": self.user["name"]})
            return
        auth.THROTTLE.fail(who)
        self._fail(401, "not signed in")

    def _api_users(self, method: str, rest: list[str]) -> None:
        me = self.user
        # /api/auth/users
        if not rest:
            if method == "GET":
                self._json(200, {"me": me["id"], "users": auth.ACCOUNTS.users()})
                return
            if method != "POST":
                self._fail(405, "GET or POST")
                return
            payload = self._body()
            if payload is None:
                return
            name = (payload if isinstance(payload, dict) else {}).get("name")
            user, why = auth.ACCOUNTS.add(name, me["id"])
            if not user:
                self._fail(400, why)
                return
            log(f"auth: {me['name']} added {user['name']}")
            # Somebody is added to be let in, so their first link comes with them.
            made = auth.ACCOUNTS.link(user["id"], me["id"])
            self._json(201, {"user": user, "link": self._link_out(made)})
            return

        uid = _s(rest[0], 32)
        # /api/auth/users/<id>/link — another one-time link for them.
        if len(rest) == 2 and rest[1] == "link" and method == "POST":
            made = auth.ACCOUNTS.link(uid, me["id"])
            if not made:
                self._fail(404, "nobody by that id")
                return
            log(f"auth: {me['name']} made a login link for {made['name']}")
            self._json(201, self._link_out(made))
            return

        # /api/auth/users/<id> — take them out, and every browser they are in.
        if len(rest) == 1 and method == "DELETE":
            if uid == me["id"]:
                self._fail(400, "you cannot remove yourself — somebody else can")
                return
            name = auth.ACCOUNTS.remove(uid)
            if name is None:
                self._fail(404, "nobody by that id")
                return
            log(f"auth: {me['name']} removed {name}")
            self._json(200, {"ok": True})
            return

        self._fail(405, "GET or POST /users, POST /users/<id>/link, DELETE /users/<id>")

    @staticmethod
    def _link_out(made: dict | None) -> dict | None:
        if not made:
            return None
        return {"id": made["id"], "path": made["path"], "expiresAt": made["expiresAt"],
                "url": f"{PUBLIC_URL}{made['path']}" if PUBLIC_URL else ""}

    def _api_verdicts(self, method: str, body: object) -> None:
        """What you have said about a film you do not own.

        GET is the whole record, which is what a recommendation will one day
        be learned from. POST gives one film a verdict, or takes it back with
        an empty one.
        """
        if method == "GET":
            self._json(200, {"counts": verdicts.STORE.counts(),
                             "verdicts": verdicts.STORE.all()})
            return
        if method != "POST":
            self._fail(405, "GET or POST")
            return
        given = body if isinstance(body, dict) else {}
        key = _s(given.get("key"), 200)
        if not key:
            self._fail(400, "which film")
            return
        verdict = _s(given.get("verdict"), 16)
        if verdict and verdict not in verdicts.VERDICTS:
            self._fail(400, "no such verdict")
            return
        self._json(200, {"counts": verdicts.STORE.set(key, verdict)})

    def _api_lists(self, method: str, parts: list[str], query: dict) -> None:
        one = parts[1] if len(parts) > 1 else ""

        # /api/lists/films — the merged catalogue, filtered and paged.
        if one == "films":
            if method != "GET":
                self._fail(405, "GET")
                return
            first = (query.get("q") or [""])[0]
            # `genre=` may be given once with commas, or once per genre; both
            # say the same thing, and `genremode` decides whether they widen
            # the net or narrow it.
            genres = [_s(name, 40) for chunk in (query.get("genre") or [])[:12]
                      for name in _s(chunk, 240).split(",")]
            # `rating=` reads the same way, and carries two ids that are not
            # ratings: `none` for the films Wikidata says have none, and
            # `unknown` for the ones the rating pass has not reached.
            ratings = [_s(name, 12) for chunk in (query.get("rating") or [])[:12]
                       for name in _s(chunk, 120).split(",")]
            self._json(200, lists.query(
                year_from=_int((query.get("from") or ["0"])[0], 0, 3000) or 0,
                year_to=_int((query.get("to") or ["0"])[0], 0, 3000) or 0,
                text=_s(first, 120),
                topic=_s((query.get("topic") or [""])[0], 40),
                genres=genres,
                genre_mode=_s((query.get("genremode") or [""])[0], 8),
                actor=_s((query.get("actor") or [""])[0], 120),
                only=_s((query.get("only") or [""])[0], 16),
                skipped=_s((query.get("skipped") or [""])[0], 8) or "hide",
                ratings=ratings,
                sort=_s((query.get("sort") or [""])[0], 16) or "notable",
                limit=_int((query.get("limit") or ["60"])[0], 1, 300) or 60,
                offset=_int((query.get("offset") or ["0"])[0], 0, 100000) or 0))
            return

        # /api/lists/facts?a=<article>&a=… — the poster, the IMDb id and the
        # age rating for each of these. Addresses and identifiers only: no
        # image passes through here and nothing is written to disk. The
        # browser fetches and caches the picture itself, which is the only
        # copy kept anywhere.
        if one == "facts":
            if method != "GET":
                self._fail(405, "GET")
                return
            names = [_s(name, 200) for name in (query.get("a") or [])[:60]]
            self._json(200, {"facts": lists.facts([n for n in names if n])})
            return

        # /api/lists/certs — what each film was rated, and the pass that
        # fills it in. GET is where it has got to; POST starts or stops it.
        # A rating cannot be filtered by until it has been fetched, and the
        # year lists never printed one, so this is the only way it gets there.
        if one == "certs":
            if method == "GET":
                self._json(200, lists.CERTIFIER.status())
                return
            if method != "POST":
                self._fail(405, "GET or POST")
                return
            payload = self._body()
            if payload is None:
                return
            given = payload if isinstance(payload, dict) else {}
            action = _s(given.get("action"), 16) or "start"
            if action == "stop":
                self._json(200, lists.CERTIFIER.stop())
                return
            # `all` asks again about films already answered for, which is what
            # a year re-rated since the last pass needs.
            scope = _s(given.get("scope"), 16) or "missing"
            self._json(200, lists.CERTIFIER.start(scope))
            return

        # /api/lists/raw/<set>/<year|topic> — one archived page, as parsed.
        if one == "raw":
            if method != "GET":
                self._fail(405, "GET")
                return
            if len(parts) < 4:
                self._json(200, {"pages": lists.archived()})
                return
            set_id = _s(parts[2], 24)
            ref = _s(parts[3], 40)
            page = lists.load_raw(set_id, _int(ref, 0, 3000) or 0,
                                  "" if ref.isdigit() else ref)
            self._json(200 if page else 404, page or {"error": "not harvested"})
            return

        if one:
            self._fail(404, "no such endpoint")
            return

        # /api/lists
        if method == "GET":
            self._json(200, {"catalogue": lists.source_catalogue(),
                             **lists.HARVESTER.status()})
            return
        if method != "POST":
            self._fail(405, "GET or POST")
            return

        payload = self._body()
        if payload is None:
            return
        body = payload if isinstance(payload, dict) else {}
        action = _s(body.get("action"), 16) or "start"
        if action == "stop":
            self._json(200, lists.HARVESTER.stop())
            return
        # Re-fold the archive without asking Wikipedia for any of it again.
        if action == "rebuild":
            lists.rebuild()
            self._json(200, lists.HARVESTER.status())
            return

        sets = [_s(x, 16) for x in (body.get("sets") or []) if _s(x, 16)][:8]
        topics = [_s(x, 40) for x in (body.get("topics") or []) if _s(x, 40)][:20]
        low = _int(body.get("from"), lists.FIRST_YEAR, lists.LAST_YEAR) or 0
        high = _int(body.get("to"), lists.FIRST_YEAR, lists.LAST_YEAR) or low
        years = list(range(min(low, high), max(low, high) + 1)) if low else []
        # A century of three pages each is four hundred paced calls; more than
        # that in one press is a mistake rather than a plan.
        self._json(200, lists.HARVESTER.start(sets, years[:200], topics))
        return

    def _api_library(self, method: str, parts: list[str], query: dict) -> None:
        # /api/library
        if len(parts) == 1:
            if method == "GET":
                self._json(200, LIBRARY.snapshot())
            elif method == "PUT":
                payload = self._body()
                if payload is None:
                    return
                if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
                    self._fail(400, "expected {items: [...]}")
                    return
                ok, result = LIBRARY.replace(payload)
                if not ok:
                    self._json(409 if result.get("error") == "conflict" else 400, result)
                    return
                self._json(200, {"ok": True, "rev": result["rev"], **LIBRARY.meta()})
            else:
                self._fail(405, "GET or PUT")
            return

        # /api/library/items[/<id>]
        if parts[1] == "items":
            item_id = parts[2] if len(parts) > 2 else ""
            if method == "POST" and not item_id:
                payload = self._body()
                if payload is None:
                    return
                item = LIBRARY.upsert(payload if isinstance(payload, dict) else {})
                self._json(201 if item else 400,
                           item or {"error": "an item needs at least a title"})
                return
            if method == "PATCH" and item_id:
                payload = self._body()
                if payload is None:
                    return
                item = LIBRARY.patch(item_id, payload if isinstance(payload, dict) else {})
                self._json(200 if item else 404, item or {"error": "not found"})
                return
            if method == "DELETE" and item_id:
                hard = (query.get("hard") or ["0"])[0] == "1"
                ok = LIBRARY.delete(item_id, hard)
                self._json(200 if ok else 404, {"ok": ok, **LIBRARY.meta()})
                return
            self._fail(405, "POST /items, PATCH /items/<id>, DELETE /items/<id>")
            return

        self._fail(404, "no such endpoint")

    def _api_img(self, query: dict) -> None:
        target = (query.get("u") or [""])[0]
        if not target:
            self._fail(400, "u is required")
            return
        parsed = urllib.parse.urlsplit(target)
        if parsed.scheme != "https" or not parsed.netloc:
            self._fail(400, "https urls only")
            return
        if not IMG_ALLOW_ANY and not IMG_HOSTS.match(parsed.hostname or ""):
            self._fail(403, "image host is not allow-listed")
            return

        # Keyed on what the browser asked for, so stepping the size down below
        # never changes the key and a cached file keeps being found.
        key = imgcache.key_for(target)
        etag = f'"{key}"'
        if (self.headers.get("If-None-Match") or "").strip() == etag:
            self._send(304, b"", "image/jpeg", self._img_headers(etag), compress=False)
            return

        hit = imgcache.get(key)
        if hit is not None:
            blob, ctype = hit
            self._send(200, blob, ctype, self._img_headers(etag), compress=False)
            return

        if not NET_ENABLED:
            self._fail(503, "network lookups are disabled")
            return

        # The smaller rendition first; the original only if that 404s, because
        # not every provider has one at the size the path implies.
        got = self._fetch_img(smaller_img(target))
        if got is None and smaller_img(target) != target:
            got = self._fetch_img(target)
        if got is None:
            self._fail(502, "could not fetch that image")
            return

        blob, ctype = got
        imgcache.put(key, blob, ctype)
        self._send(200, blob, ctype, self._img_headers(etag), compress=False)

    @staticmethod
    def _img_headers(etag: str) -> dict:
        """Artwork never changes under a given URL, so let it be kept."""
        return {"Cache-Control": "public, max-age=31536000, immutable",
                "ETag": etag, "Pragma": None, "Expires": None}

    @staticmethod
    def _fetch_img(url: str) -> tuple[bytes, str] | None:
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": UA, "Accept": "image/*"})
            with urllib.request.urlopen(request, timeout=8) as response:  # noqa: S310
                ctype = (response.headers.get("Content-Type") or "").split(";")[0].strip()
                if not ctype.startswith("image/"):
                    return None
                return response.read(8 * 1024 * 1024), ctype
        except (urllib.error.URLError, socket.timeout, TimeoutError, ValueError):
            return None

    # -- static --------------------------------------------------------

    def _static(self, path: str) -> None:
        target = self._resolve(path)
        if target is None:
            # Unknown non-asset path: hand back the app shell.
            if "." not in path.rsplit("/", 1)[-1]:
                target = self._resolve("/index.html")
            if target is None:
                self._fail(404, "not found")
                return
        try:
            body = target.read_bytes()
        except OSError:
            self._fail(404, "not found")
            return
        suffix = target.suffix.lower()
        ctype = EXTRA_TYPES.get(suffix) or mimetypes.guess_type(target.name)[0] \
            or "application/octet-stream"
        # Opening the app sets the cookie again. A browser drops a cookie 400
        # days after it was last set, so this is what makes a sign-in for good.
        renew = ({"Set-Cookie": self._session_cookie(self.token)}
                 if self.user and target.name == "index.html" else None)
        self._send(200, body, ctype, renew)

    @staticmethod
    def _resolve(path: str) -> Path | None:
        if "\x00" in path:
            return None
        relative = path.lstrip("/") or "index.html"
        try:
            candidate = (PUBLIC_DIR / relative).resolve()
            candidate.relative_to(PUBLIC_DIR)      # blocks ../ traversal
        except (ValueError, OSError):
            return None
        if candidate.is_dir():
            candidate = candidate / "index.html"
        return candidate if candidate.is_file() else None


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    request_queue_size = 64
