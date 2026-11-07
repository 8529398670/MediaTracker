#!/usr/bin/env bash
# Set up the venv and run the server from this checkout, outside Docker.
#
#   scripts/run.sh                    create/update .venv if needed, stop the
#                                     copy this checkout started last, start a
#                                     fresh one
#   scripts/run.sh manage <command>   run an admin command against it
#   scripts/run.sh <anything else>    same: passed straight to `python -m app`
#
# The server runs in the foreground: its log streams here and Ctrl-C stops it.
# Running scripts/run.sh again from another terminal stops this one and takes
# over, so "edit, scripts/run.sh, reload the page" is the whole loop.
#
# With arguments it is a one-off instead -- the same venv, then `python -m
# app` with those arguments -- and the running server is left alone. `manage`
# opens the database directly, which SQLite's WAL mode makes safe alongside
# the live server.
#
#   scripts/login.sh                                    owner's login link
#   scripts/run.sh manage list-users
#   scripts/run.sh manage create-login --name "Grace" --role user
#   scripts/run.sh manage create-invite --user-id 1 --label "Book club"
#   scripts/run.sh manage create-key --user-id 1 --name "CI"
#   scripts/run.sh manage paths                         where the state lives
#   scripts/run.sh config check
#   scripts/run.sh config shell server                  every resolved value
#   scripts/run.sh version
#
# This is for development and internal boxes. It is a plain process with your
# permissions -- none of docker/run.sh's read-only filesystem, dropped
# capabilities, or pid and memory limits apply -- so use Docker for anything
# long-lived or internet-facing.
set -euo pipefail
cd "$( dirname "${BASH_SOURCE[0]}" )/.."


source scripts/lib.sh

# This happens before anything is stopped, so a failed install leaves the
# server that was already running untouched.
ensure_venv

if [ $# -gt 0 ]; then
  exec "$PYTHON" -m app "$@"
fi

read_server_config

# First run on this checkout: config/config.yaml is gitignored, so a fresh
# clone has none. Without one here the app would quietly create
# ~/.config/media-tracker/config.yaml instead, which is not the file this
# checkout's docker/run.sh reads. Write it here and stop, like docker/run.sh,
# so it gets looked at before the first start.
if [ "$config_exists" != "true" ]; then
  "$PYTHON" -m app config init --file ./config/config.yaml >/dev/null
  read_server_config
  echo "First run: wrote ${config_file}"
  echo "  (mode 0600, with a new secret key -- back it up with the database; it is"
  echo "  the only thing that can read it)."
  echo ""
  echo "It will serve ${url}"
  echo "  (from ${url_source})."
  if [ "${url#http://}" != "$url" ] && [ "$secure_cookies" = "true" ]; then
    echo ""
    echo "server.secure_cookies is true. That is right behind HTTPS, but at ${url}"
    echo "the browser drops a Secure cookie and signing in silently does nothing."
    echo "For local use, change line $( config_line secure_cookies ) of ${config_file}:"
    echo ""
    echo "    secure_cookies: true   ->   secure_cookies: false"
  fi
  echo ""
  echo "Then run scripts/run.sh again."
  exit 0
fi

# Stop the copy this checkout started last.
OLD_PID="$( our_server_pid )"
if [ -n "$OLD_PID" ]; then
  echo "Stopping the server this checkout started (pid ${OLD_PID}, running since $( ps -p "$OLD_PID" -o lstart= 2>/dev/null | sed 's/  */ /g' ))..."
  kill -TERM "$OLD_PID" 2>/dev/null || true
  # uvicorn shuts down gracefully within 10 seconds (app/main.py). Past
  # that, something is stuck, and waiting longer will not unstick it.
  for _ in $( seq 1 60 ); do
    kill -0 "$OLD_PID" 2>/dev/null || break
    sleep 0.25
  done
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "It did not exit in 15 seconds; killing it."
    kill -KILL "$OLD_PID" 2>/dev/null || true
  fi
fi
rm -f "$PID_FILE"

# Anything still on the port is not ours, and uvicorn would only die on
# "address already in use" after printing a banner that says it started.
OWNER="$( port_owner "$port" )"
if [ -n "$OWNER" ] || server_answers; then
  echo "ERROR: port ${port} (server.port) is already in use${OWNER:+ by ${OWNER}}." >&2
  echo "" >&2
  echo "       It is not the server this checkout started. Stop it, or change line" >&2
  echo "       $( config_line port ) of ${config_file} to a free port, then re-run." >&2
  read_docker_config
  if container_running "$docker_container" && [ "$docker_host_port" = "$port" ]; then
    echo "" >&2
    echo "       The ${docker_container} docker container publishes port ${docker_host_port} --" >&2
    echo "       that is probably it (docker stop ${docker_container})." >&2
  fi
  exit 1
fi

if [ "${url#http://}" != "$url" ] && [ "$secure_cookies" = "true" ]; then
  echo "WARNING: server.secure_cookies is true but the URL is ${url}."
  echo "         The browser will drop the session cookie and signing in will silently"
  echo "         do nothing. Set it to false on line $( config_line secure_cookies ) of ${config_file}"
  echo "         for local use, or set server.public_url to the https:// address in front."
  echo ""
fi

if [ "$database_exists" = "true" ]; then
  DB_NOTE="existing"
else
  DB_NOTE="new -- the owner's first login link is printed below"
fi
if [ "$static_on_disk" = "true" ]; then
  STATIC_NOTE="${static_dir}  (from disk: frontend edits need only a reload)"
else
  STATIC_NOTE="the bundled copy  (no directory at ${static_dir})"
fi
if [ "$language_on_disk" = "true" ]; then
  LANGUAGE_NOTE="${language_file}  (from disk)"
else
  LANGUAGE_NOTE="the bundled copy  (no file at ${language_file})"
fi

cat <<NOTE
Starting media-tracker with $( "$PYTHON" --version 2>&1 ) from .venv
  url       ${url}
            from ${url_source}
  config    ${config_file}
  app dir   ${app_dir}
  database  ${database}  (${DB_NOTE})
  static    ${STATIC_NOTE}
  language  ${LANGUAGE_NOTE}
  code      Python changes need scripts/run.sh again; static/ edits only a reload

A login link for the owner any time: scripts/login.sh (from another terminal).

NOTE

mkdir -p "$RUN_DIR"

# Say when it is actually answering, not just launched. This runs beside the
# server and outlives the exec below; it gives up after 20 seconds.
(
  for _ in $( seq 1 40 ); do
    sleep 0.5
    if server_answers; then
      echo ""
      echo "Ready: ${url}"
      echo ""
      exit 0
    fi
  done
  echo ""
  echo "Not answering on port ${port} after 20 seconds -- see the log above."
) &

# exec keeps this shell's pid, so the one written here is the server's.
echo $$ > "$PID_FILE"
exec "$PYTHON" -m app
