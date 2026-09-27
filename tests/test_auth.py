"""Nobody without a session gets anything; a login link works once.

Runs the real server on a spare port, against a scratch data directory, and
knocks on it the way a browser, a script and a stranger each would. Also runs
the shell side — ``auth.py link`` in a second process — to check that a link
made there is good in the running server a request later.

    python3 tests/test_auth.py
"""
import http.client
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = tempfile.mkdtemp(prefix="mt-auth-")
os.environ.update({"MT_DATA_DIR": DATA, "MT_ENABLE_NET": "0", "MT_SEED": "0",
                   "MT_ENV_FILE": os.devnull, "MT_PUBLIC_URL": "",
                   "MT_PUBLIC_DIR": str(ROOT / "public")})
sys.path.insert(0, str(ROOT / "server"))

import auth                         # noqa: E402
from httpd import Handler, Server   # noqa: E402

failures = 0


def check(label, got, want=True):
    global failures
    ok = got == want
    failures += not ok
    print(f"{'ok  ' if ok else 'FAIL'}  {label}" + ("" if ok else f"\n        got  {got!r}\n        want {want!r}"))


server = Server(("127.0.0.1", 0), Handler)
threading.Thread(target=server.serve_forever, daemon=True).start()
PORT = server.server_address[1]

NAVIGATE = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Site": "none", "Accept": "text/html"}
SAME = {"Sec-Fetch-Mode": "cors", "Sec-Fetch-Site": "same-origin"}


def ask(method, path, body=None, headers=None, cookie=""):
    conn = http.client.HTTPConnection("127.0.0.1", PORT, timeout=10)
    sent = dict(headers or {})
    if cookie:
        sent["Cookie"] = f"{auth.COOKIE}={cookie}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        sent["Content-Type"] = "application/json"
    conn.request(method, path, data, sent)
    res = conn.getresponse()
    raw = res.read()
    conn.close()
    try:
        payload = json.loads(raw)
    except ValueError:
        payload = raw.decode("utf-8", "replace")
    return res.status, dict(res.getheaders()), payload


def cookie_of(headers):
    value = headers.get("Set-Cookie", "")
    return value.split(";")[0].partition("=")[2]


# ----------------------------------------------------------- a stranger

status, headers, body = ask("GET", "/", headers=NAVIGATE)
check("a stranger opening the app gets the gate", (status, "/gate.js" in body, "app.js" in body),
      (200, True, False))
check("  and it is not for search engines", headers.get("X-Robots-Tag"), "noindex, nofollow")

status, headers, _ = ask("GET", "/")
check("a script asking for / is sent to Google", (status, headers.get("Location")),
      (302, auth.AWAY))
status, headers, _ = ask("GET", "/js/app.js",
                         headers={"Sec-Fetch-Mode": "no-cors", "Sec-Fetch-Dest": "script"})
check("the app's code is not handed out", (status, headers.get("Location")), (302, auth.AWAY))
status, headers, _ = ask("GET", "/css/app.css")
check("nor its stylesheet", status, 302)
status, _, body = ask("GET", "/api/library")
check("the library is refused", (status, "items" in json.dumps(body)), (401, False))
status, _, _ = ask("PUT", "/api/library", {"rev": 0, "items": []}, headers=SAME)
check("and cannot be written", status, 401)
status, _, _ = ask("POST", "/api/enrich", {"action": "start"}, headers=SAME)
check("nor anything started", status, 401)
status, _, _ = ask("GET", "/api/lists/films")
check("nor the catalogue read", status, 401)
status, _, _ = ask("GET", "/api/library", headers=NAVIGATE)
check("an API address typed into the bar gets the gate too", status, 200)
status, _, body = ask("GET", "/api/health")
check("health says up and nothing else", (status, body), (200, {"ok": True}))
status, _, body = ask("GET", "/gate.js")
check("the gate's script is open", (status, "api/auth/redeem" in body), (200, True))
status, _, _ = ask("GET", "/favicon.svg")
check("and so is the icon", status, 200)
status, _, _ = ask("GET", "/gate.html", headers={"Accept": "*/*"})
check("the gate page by name is not a way round it", status, 302)
status, _, _ = ask("POST", "/api/auth/users", {"name": "me"}, headers=SAME)
check("a stranger cannot add themselves", status, 401)
status, _, _ = ask("POST", "/api/auth/redeem", {"token": "x" * 43}, headers=SAME)
check("a made-up link is refused", status, 401)

# ------------------------------------------------------------ a link

alice, _ = auth.ACCOUNTS.add("Alice")
made = auth.ACCOUNTS.link(alice["id"])
check("a link is a path with the token after the #",
      made["path"].startswith("/login#") and len(made["token"]) >= 40)
raw = pathlib.Path(DATA, "users.json").read_text()
check("the file never holds the token itself", made["token"] in raw, False)
check("  and is readable only by its owner",
      oct(pathlib.Path(DATA, "users.json").stat().st_mode & 0o777), "0o600")

status, _, body = ask("GET", "/login", headers=NAVIGATE)
check("the link's page is the gate, with nothing to spend in it", (status, "/gate.js" in body),
      (200, True))
status, headers, body = ask("POST", "/api/auth/redeem", {"token": made["token"]}, headers=SAME)
session = cookie_of(headers)
check("opening the link signs the browser in", (status, body.get("name")), (200, "Alice"))
check("  the cookie is the session the page keeps", session, body.get("token"))
check("  and it lasts as long as a browser allows",
      "Max-Age=34560000" in headers.get("Set-Cookie", "")
      and "HttpOnly" in headers["Set-Cookie"] and "SameSite=Lax" in headers["Set-Cookie"])
check("  and is not marked Secure over plain http", "Secure" in headers["Set-Cookie"], False)
status, _, _ = ask("POST", "/api/auth/redeem", {"token": made["token"]}, headers=SAME)
check("the same link a second time is refused", status, 401)

status, headers, body = ask("GET", "/", headers=NAVIGATE, cookie=session)
check("signed in, the app itself is served", (status, "/js/app.js" in body), (200, True))
check("  and opening it sets the cookie again, for another 400 days",
      cookie_of(headers), session)
status, _, _ = ask("GET", "/js/app.js", cookie=session)
check("  with its code", status, 200)
status, _, body = ask("GET", "/api/library", cookie=session)
check("  and its library", (status, "items" in body), (200, True))
status, _, body = ask("GET", "/api/config", cookie=session)
check("config says who is signed in", body.get("me"), {"id": alice["id"], "name": "Alice"})
status, _, body = ask("GET", "/api/health", cookie=session)
check("health tells someone signed in the rest", "items" in body)

second = auth.ACCOUNTS.link(alice["id"])
status, headers, _ = ask("POST", "/api/auth/redeem", {"token": second["token"]},
                         headers={"Sec-Fetch-Site": "same-origin", "X-Forwarded-Proto": "https"})
check("through the tunnel the cookie is Secure", "; Secure" in headers.get("Set-Cookie", ""))
tunnel_session = cookie_of(headers)

# ------------------------------------------------------ writes from elsewhere

status, _, _ = ask("POST", "/api/auth/users", {"name": "Mallory"},
                   headers={"Sec-Fetch-Site": "cross-site"}, cookie=session)
check("a write from another site is refused, cookie or not", status, 403)
status, _, _ = ask("POST", "/api/auth/users", {"name": "Mallory"},
                   headers={"Sec-Fetch-Site": "same-site"}, cookie=session)
check("  and from another app on the same box", status, 403)
status, _, _ = ask("POST", "/api/auth/users", {"name": "Mallory"},
                   headers={"Origin": "http://192.168.5.41:8123", "Host": "192.168.5.41:8674"},
                   cookie=session)
check("  and from another port, told by Origin alone", status, 403)
check("  nobody was added by any of them", auth.ACCOUNTS.find("Mallory"), None)
status, _, body = ask("GET", "/api/auth/me",
                      headers={"Origin": "http://192.168.5.41:8123", "Host": "192.168.5.41:8674"},
                      cookie=session)
check("  a read is not a write: GET is answered wherever it came from",
      (status, body.get("name")), (200, "Alice"))
status, _, body = ask("POST", "/api/auth/logout",
                      headers={"Origin": "http://192.168.5.41:8674", "Host": "192.168.5.41:8674"},
                      cookie=tunnel_session)
check("  but a write from its own address is fine", (status, body), (200, {"ok": True}))
second = auth.ACCOUNTS.link(alice["id"])
status, headers, _ = ask("POST", "/api/auth/redeem", {"token": second["token"]},
                         headers={"Sec-Fetch-Site": "same-origin", "X-Forwarded-Proto": "https"})
tunnel_session = cookie_of(headers)

# ---------------------------------------------------------------- people

status, _, body = ask("POST", "/api/auth/users", {"name": "  Bob  "}, headers=SAME, cookie=session)
check("anyone signed in can add someone", (status, body["user"]["name"]), (201, "Bob"))
check("  and their first link comes with them", body["link"]["path"].startswith("/login#"))
bob_id = body["user"]["id"]
bob_link = body["link"]["path"].split("#", 1)[1]
status, _, body = ask("POST", "/api/auth/users", {"name": "bob"}, headers=SAME, cookie=session)
check("a name is only used once, whatever the case", status, 400)
status, _, body = ask("POST", "/api/auth/users", {"name": "​ \t"}, headers=SAME, cookie=session)
check("a name has to have something in it", status, 400)

status, _, body = ask("GET", "/api/auth/users", cookie=session)
names = [p["name"] for p in body["users"]]
check("the list has everyone", names, ["Alice", "Bob"])
check("  and says which one is you", body["me"], alice["id"])
bob = next(p for p in body["users"] if p["name"] == "Bob")
check("  Bob has not signed in, and has a link waiting", (bob["devices"], len(bob["links"])), (0, 1))

status, headers, body = ask("POST", "/api/auth/redeem", {"token": bob_link}, headers=SAME)
bob_session = cookie_of(headers)
check("Bob's link signs Bob in", body.get("name"), "Bob")
status, _, body = ask("GET", "/api/auth/users", cookie=session)
bob = next(p for p in body["users"] if p["name"] == "Bob")
check("  and he shows as signed in, with no link waiting", (bob["devices"], bob["links"]), (1, []))

status, _, body = ask("POST", f"/api/auth/users/{bob_id}/link", headers=SAME, cookie=bob_session)
check("Bob can make links too — everyone is an admin", status, 201)
spare = body["id"]
status, _, _ = ask("DELETE", f"/api/auth/links/{spare}", headers=SAME, cookie=session)
check("a link nobody has opened can be cancelled", status, 200)
status, _, _ = ask("POST", "/api/auth/redeem", {"token": body["path"].split("#", 1)[1]}, headers=SAME)
check("  and then it does not work", status, 401)

status, _, _ = ask("DELETE", f"/api/auth/users/{alice['id']}", headers=SAME, cookie=session)
check("you cannot remove yourself", status, 400)
status, _, _ = ask("DELETE", f"/api/auth/users/{bob_id}", headers=SAME, cookie=session)
check("but you can remove somebody else", status, 200)
status, _, _ = ask("GET", "/api/library", cookie=bob_session)
check("  and every browser they were in is out at once", status, 401)
status, _, body = ask("GET", "/", headers=NAVIGATE, cookie=bob_session)
check("  and gets the gate", "/gate.js" in body)

# ---------------------------------------------------------- the kept copy

status, headers, body = ask("POST", "/api/auth/resume", {"token": session}, headers=SAME)
check("a kept session puts back a lost cookie", (status, cookie_of(headers)), (200, session))
status, _, _ = ask("POST", "/api/auth/resume", {"token": bob_session}, headers=SAME)
check("  but not one that was removed", status, 401)
status, _, body = ask("POST", "/api/auth/resume", {}, headers=SAME, cookie=session)
check("  and a live cookie answers for itself", (status, body.get("name")), (200, "Alice"))

# -------------------------------------------------------- the lapsed link

stale = auth.ACCOUNTS.link(alice["id"])
path = pathlib.Path(DATA, "users.json")
data = json.loads(path.read_text())
for link in data["links"].values():
    link["expiresAt"] = "2000-01-01T00:00:00Z"
path.write_text(json.dumps(data))
status, _, _ = ask("POST", "/api/auth/redeem", {"token": stale["token"]}, headers=SAME)
check("a link left unopened too long has lapsed", status, 401)
check("  and is tidied away", json.loads(path.read_text())["links"], {})

# ----------------------------------------------------------- the shell

run = subprocess.run([sys.executable, str(ROOT / "server" / "auth.py"), "link", "Carol"],
                     capture_output=True, text=True, env=os.environ, timeout=60)
line = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
check("the shell makes a link, adding the name", (run.returncode, line.startswith("/login#")),
      (0, True))
status, _, body = ask("POST", "/api/auth/redeem", {"token": line.split("#", 1)[1]}, headers=SAME)
check("  and the running server takes it at once", (status, body.get("name")), (200, "Carol"))
check("  without losing anyone it already had",
      sorted(p["name"] for p in auth.ACCOUNTS.users()), ["Alice", "Carol"])
run = subprocess.run([sys.executable, str(ROOT / "server" / "auth.py"), "link", "carol"],
                     capture_output=True, text=True, env=os.environ, timeout=60)
check("a second link for a known name is for that person, not a new one",
      [p["name"] for p in auth.ACCOUNTS.users()], ["Alice", "Carol"])

# -------------------------------------------------------------- API keys

auth.THROTTLE.fails.clear()


def bearer(key, extra=None):
    return {"Authorization": f"Bearer {key}", **(extra or {})}


status, _, body = ask("POST", f"/api/auth/users/{alice['id']}/keys", {"label": "claude bot"},
                      headers=SAME, cookie=session)
check("anyone signed in can make an API key for someone",
      (status, body.get("access"), body.get("label"), body.get("name")),
      (201, "full", "claude bot", "Alice"))
key, key_id = body["key"], body["id"]
check("  it says what it is", key.startswith("mt_") and len(key) > 40)
check("  and the file never holds it", key in pathlib.Path(DATA, "users.json").read_text(), False)
status, _, _ = ask("POST", f"/api/auth/users/{alice['id']}/keys", {"access": "admin"},
                   headers=SAME, cookie=session)
check("  a key is full or read, nothing else", status, 400)

status, headers, body = ask("GET", "/api/library", headers=bearer(key))
check("a key reads the library", (status, "items" in body), (200, True))
check("  and is given no cookie", "Set-Cookie" in headers, False)
status, _, body = ask("GET", "/api/auth/me", headers=bearer(key))
check("  it is the person it was made for, and says which key it is",
      (body.get("name"), body.get("key", {}).get("label"), body.get("key", {}).get("access")),
      ("Alice", "claude bot", "full"))

status, _, body = ask("POST", "/api/library/items",
                      {"title": "The Lady Eve", "year": 1941, "type": "movie"}, headers=bearer(key))
check("a full key adds a title", (status, body.get("title")), (201, "The Lady Eve"))
eve = body["id"]
status, _, body = ask("PATCH", f"/api/library/items/{eve}", {"status": "watched"},
                      headers=bearer(key))
check("  ticks it watched, and the date comes with it",
      (status, body.get("status"), bool(body.get("watchedAt"))), (200, "watched", True))
status, _, body = ask("PATCH", f"/api/library/items/{eve}", {"status": "queue"},
                      headers=bearer(key))
check("  and back, and the date goes", (body.get("status"), body.get("watchedAt")),
      ("queue", None))

rev = ask("GET", "/api/health", headers=bearer(key))[2]["rev"]
status, _, body = ask("POST", "/api/library/items", {"items": [
    {"title": "Ninotchka", "year": 1939}, {"title": "Ball of Fire"}, {"year": 1950}]},
    headers=bearer(key))
check("a batch of titles goes in, in one write, leaving out one with no title",
      (status, [i["title"] for i in body.get("added", [])], body.get("rev")),
      (201, ["Ninotchka", "Ball of Fire"], rev + 1))
ids = [i["id"] for i in body["added"]]
status, _, body = ask("PATCH", "/api/library/items", {
    ids[0]: {"order": 0, "status": "watched"}, ids[1]: {"deleted": True}, "nope": {"order": 1}},
    headers=bearer(key))
check("a batch of changes goes in, in one write, naming what it could not find",
      (status, body.get("changed"), body.get("missing"), body.get("rev")),
      (200, 2, ["nope"], rev + 2))
items = {i["id"]: i for i in ask("GET", "/api/library", headers=bearer(key))[2]["items"]}
check("  reordered, ticked with a date, and put away",
      (items[ids[0]]["order"], bool(items[ids[0]]["watchedAt"]), items[ids[1]]["deleted"]),
      (0, True, True))
status, _, _ = ask("PATCH", "/api/library/items", [1, 2], headers=bearer(key))
check("  and a batch that is not one is refused", status, 400)
status, _, _ = ask("DELETE", f"/api/library/items/{eve}", headers=bearer(key))
check("a full key deletes", status, 200)

status, _, _ = ask("GET", "/api/auth/users", headers=bearer(key))
check("a key cannot see the people", status, 403)
status, _, _ = ask("POST", "/api/auth/users", {"name": "Mallory"}, headers=bearer(key))
check("  nor add anyone", status, 403)
status, _, _ = ask("POST", f"/api/auth/users/{alice['id']}/link", headers=bearer(key))
check("  nor make a login link", status, 403)
status, _, _ = ask("POST", f"/api/auth/users/{alice['id']}/keys", {}, headers=bearer(key))
check("  nor another key", status, 403)
status, _, _ = ask("DELETE", f"/api/auth/keys/{key_id}", headers=bearer(key))
check("  nor revoke one", status, 403)
status, _, _ = ask("POST", "/api/auth/logout", headers=bearer(key))
check("  nor sign anybody out", status, 403)
status, headers, body = ask("GET", "/", headers=bearer(key, NAVIGATE))
check("  nor fetch the app", (status, "Set-Cookie" in headers, "app.js" in str(body)),
      (404, False, False))
status, _, _ = ask("POST", "/api/library/items", {"title": "x"},
                   headers=bearer(key, {"Sec-Fetch-Site": "cross-site"}))
check("  and a write from another site is refused, key or not", status, 403)

fake = "mt_" + "z" * 43
status, headers, _ = ask("GET", "/api/library", headers=bearer(fake, NAVIGATE), cookie=session)
check("a key that is no key is refused plainly, whatever cookie comes with it",
      (status, headers.get("Location")), (401, None))
status, _, _ = ask("GET", "/api/library", headers={"Authorization": "Basic YTpi"}, cookie=session)
check("  another kind of Authorization is not a key, and is left alone", status, 200)

status, _, body = ask("POST", f"/api/auth/users/{alice['id']}/keys",
                      {"label": "reader", "access": "read"}, headers=SAME, cookie=session)
reader = body["key"]
check("a read-only key", (status, body.get("access")), (201, "read"))
status, _, _ = ask("GET", "/api/library", headers=bearer(reader))
check("  reads", status, 200)
codes = [ask(method, path, payload, headers=bearer(reader))[0] for method, path, payload in (
    ("POST", "/api/library/items", {"title": "x"}),
    ("PATCH", "/api/library/items", {ids[0]: {"order": 3}}),
    ("PATCH", f"/api/library/items/{ids[0]}", {"order": 3}),
    ("DELETE", f"/api/library/items/{ids[0]}", None),
    ("PUT", "/api/library", {"items": []}),
    ("POST", "/api/enrich", {"action": "start"}),
    ("POST", "/api/verdicts", {"key": "x", "verdict": "skip"}))]
check("  and every write is refused", codes, [403] * 7)
status, _, _ = ask("POST", "/api/resolve", {"text": "the lady eve"}, headers=bearer(reader))
check("  but a lookup sent as a POST is still a lookup", status, 200)

status, _, body = ask("GET", "/api/auth/users", cookie=session)
mine = next(p for p in body["users"] if p["name"] == "Alice")["keys"]
check("the people list shows each person's keys, and when they were last used",
      ([k["label"] for k in mine], [k["access"] for k in mine], bool(mine[0]["usedAt"]),
       mine[1]["hint"] == reader[:7]),
      (["claude bot", "reader"], ["full", "read"], True, True))
check("  but never a key itself", key in json.dumps(body) or reader in json.dumps(body), False)

status, _, _ = ask("DELETE", f"/api/auth/keys/{key_id}", headers=SAME, cookie=session)
check("a key can be revoked", status, 200)
status, _, _ = ask("GET", "/api/library", headers=bearer(key))
check("  and stops working at once", status, 401)
status, _, _ = ask("GET", "/api/library", headers=bearer(reader))
check("  the others go on working", status, 200)

run = subprocess.run([sys.executable, str(ROOT / "server" / "auth.py"),
                      "key", "--read", "--label", "nightly", "Carol"],
                     capture_output=True, text=True, env=os.environ, timeout=60)
carol_key = run.stdout.strip().splitlines()[-1] if run.stdout.strip() else ""
check("the shell makes a key", (run.returncode, carol_key.startswith("mt_")), (0, True))
status, _, body = ask("GET", "/api/auth/me", headers=bearer(carol_key))
check("  and the running server takes it at once",
      (status, body.get("name"), body.get("key", {}).get("access"),
       body.get("key", {}).get("label")), (200, "Carol", "read", "nightly"))
status, _, _ = ask("DELETE", f"/api/auth/users/{auth.ACCOUNTS.find('Carol')}",
                   headers=SAME, cookie=session)
status, _, _ = ask("GET", "/api/library", headers=bearer(carol_key))
check("removing someone stops their keys too", status, 401)

auth.THROTTLE.fails.clear()
codes = [ask("GET", "/api/library", headers=bearer(fake))[0] for _ in range(32)]
check("guessing at keys is slowed down", (codes[0], codes[-1]), (401, 429))
status, _, _ = ask("GET", "/api/library", headers=bearer(reader))
check("  and so, from the same address, is a good key", status, 429)
auth.THROTTLE.fails.clear()

# ------------------------------------------------------------ signing out

status, headers, _ = ask("POST", "/api/auth/logout", headers=SAME, cookie=session)
check("signing out clears the cookie", (status, "Max-Age=0" in headers.get("Set-Cookie", "")),
      (200, True))
status, _, _ = ask("GET", "/api/library", cookie=session)
check("  and the session is over", status, 401)
status, _, _ = ask("GET", "/api/library", cookie=tunnel_session)
check("  on that browser only", status, 200)

# --------------------------------------------------------------- throttle

auth.THROTTLE.fails.clear()
codes = [ask("POST", "/api/auth/resume", {"token": "y" * 43}, headers=SAME)[0] for _ in range(32)]
check("hammering the door is slowed down", (codes[0], codes[-1]), (401, 429))

server.shutdown()
shutil.rmtree(DATA, ignore_errors=True)
print(f"\n{'all passed' if not failures else f'{failures} FAILED'}")
sys.exit(1 if failures else 0)
