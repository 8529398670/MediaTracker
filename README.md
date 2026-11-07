# Media Tracker

The family watch list: one shared library of films, TV, audiobooks, radio
drama and whatever else, with each person's own Up next, watched, ratings and
hearts on top. Built on the python-webserver template (Starlette, one
encrypted SQLite file, link login, invite links, API keys, MCP, Docker).

## Run it

```bash
scripts/run.sh          # sets up .venv, starts the server, prints the URL
scripts/login.sh        # a one-time login link for the owner
```

For plain `http://localhost`, `server.secure_cookies` must be `false` in
`config/config.yaml` (it is in this checkout).

## Bring the old app's data across

```bash
scripts/run.sh manage import-legacy ../.old-MediaTracker/data --dry-run
scripts/run.sh manage import-legacy ../.old-MediaTracker/data
```

The import does four things:

- It recreates every old account by name. halo becomes the owner and admin; the rest are users.
- The old shared status, rating and heart become halo's own, and the old queue order becomes halo's "Up next" playlist.
- It copies the Discover catalogue, the age ratings, the IMDb table and the poster cache into `<app dir>/storage/`.
- It prints a fresh login link for each person.

Running it again changes nothing. Links expire after `auth.login_token_ttl_seconds`, but the Users screen can issue new ones at any time.

## Settings worth knowing

| Setting | What it does |
|---|---|
| `providers.tmdb_api_key` | Best film and TV matches and posters. Without it, lookups use Wikipedia, TVmaze, Open Library and iTunes. |
| `providers.network: false` | Keeps the app entirely offline. |
| `images.allow_hosts` | The only hosts posters are fetched from. Pages only ever load them from this server. |
| `library.restore_days` | How long a deleted title stays in Trash. |
| `jobs.*` | How often IMDb scores and Apple TV links refresh. |

## How the library screen works

- **The URL is the query.** For example: `#library/movie/queue?genre=all:Crime,Drama&year=1940..1959&sort=-imdb,title&group=decade:desc`.
  - Every scope (All, Movies, TV…) and list (Up next, Watched, Everything, Trash) remembers its own last query on your account.
  - So a filter set in Movies never empties TV.
- **Every active filter is a chip** with its own ×. Clear all resets filters, search, sort and grouping.
- **Sort is up to three keys**, each with its own direction. Missing values always sort last, and ties break by title.
  - Grouping is separate and off by default.
- **Cards show what you choose.** Customize sets the fields, the buttons, their order, the layout and the size, saved on your account.
  - Buttons are labelled. On narrow cards they fold to 44px icons.
- **Saved views** are one-tap pills holding a query plus a card layout.
- **Admins can switch "Showing" in the navbar** to look after someone else's lists.

## Tests

```bash
.venv/bin/python -m unittest discover app/tests
node tests/js/run.mjs        # or open tests/js/index.html in a browser
```

## Docker

```bash
docker/run.sh
scripts/login.sh --docker
```

The container keeps its state in `docker.data_dir` (`./data`). To import the
old data into the container's database, import into a local app directory
first and copy that directory to `./data`. You can also run the import inside
the container with the old data mounted read-only.
