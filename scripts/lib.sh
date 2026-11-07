# Shared by scripts/run.sh and scripts/login.sh. Sourced, not run, from the
# project root.
#
# Nothing here parses config.yaml. read_server_config asks the app
# (`python -m app config shell server`), which resolves every path and the URL
# exactly the way the server will -- so what these scripts print is what will
# happen, not a guess at it. After it runs, every key listed in
# app/core/config_command.py under "server" is set: config_file, app_dir,
# database, url, port, ...

VENV="$( pwd )/.venv"
PYTHON="${VENV}/bin/python"
RUN_DIR="$( pwd )/.run"
PID_FILE="${RUN_DIR}/server.pid"
# Touched after a successful install. app/requirements.txt being newer than it is
# the signal to install again, so editing the file is all it takes.
STAMP="${VENV}/.requirements.stamp"

# The venv's own python is called by path rather than activating the venv:
# it finds its packages either way, and nothing here depends on PATH.
#
# A venv whose creation was interrupted has a python but no pip, and would
# fail every install from then on; --clear rebuilds it from scratch.
ensure_venv() {
  if ! command -v python3 >/dev/null 2>&1 && [ ! -x "$PYTHON" ]; then
    echo "ERROR: python3 is not on PATH. Install Python 3 and re-run." >&2
    exit 1
  fi
  if [ ! -x "$PYTHON" ] \
     || { [ ! -f "$STAMP" ] && ! "$PYTHON" -m pip --version >/dev/null 2>&1; }; then
    echo "Creating .venv with $( python3 --version 2>&1 )..."
    python3 -m venv --clear "$VENV"
  fi
  if [ ! -f "$STAMP" ] || [ app/requirements.txt -nt "$STAMP" ]; then
    echo "Installing app/requirements.txt into .venv..."
    if ! { "$PYTHON" -m pip install --quiet --upgrade pip \
           && "$PYTHON" -m pip install --quiet -r app/requirements.txt; }; then
      echo "" >&2
      echo "ERROR: installing app/requirements.txt failed (above). Nothing was stopped or started." >&2
      exit 1
    fi
    touch "$STAMP"
  fi
}

# Assigned before it is eval'd so that a config error stops the script:
# `eval "$( failing )"` would quietly eval nothing and carry on.
read_server_config() {
  local assignments
  if ! assignments="$( "$PYTHON" -m app config shell server )"; then
    echo "" >&2
    echo "ERROR: the config above does not validate. Fix it and re-run." >&2
    exit 1
  fi
  eval "$assignments"
}

# docker_container, docker_url, ... from the same config, for the scripts that
# need to know whether the container is the live deployment.
read_docker_config() {
  local assignments
  assignments="$( "$PYTHON" -m app config shell docker )" || exit 1
  eval "$assignments"
}

# Whether a pid is the server this checkout started. The command line alone
# cannot say so: on a macOS framework build, .venv/bin/python re-executes
# itself as Python.app/.../Python, so the venv path never shows up in ps.
# "-m app" running in this directory does.
is_ours() {
  local cwd
  case "$( ps -p "$1" -o command= 2>/dev/null )" in
    *" -m app") ;;
    *) return 1 ;;
  esac
  if [ -e "/proc/$1/cwd" ]; then
    cwd="$( readlink "/proc/$1/cwd" )"
  else
    cwd="$( lsof -a -p "$1" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' )"
  fi
  [ "$cwd" = "$( pwd -P )" ]
}

# The pid of the server this checkout started, if it is still that server. A
# pid left behind by a server that has since exited can belong to anything.
our_server_pid() {
  local pid
  [ -f "$PID_FILE" ] || return 0
  pid="$( cat "$PID_FILE" )"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null && is_ours "$pid"; then
    echo "$pid"
  fi
}

# "nginx (pid 812)" for whatever is listening on a TCP port, or nothing. The
# program's directory is dropped: "Python -m http.server 8000" says more in
# one line than a long install path does.
port_owner() {
  local port="$1" pid name
  command -v lsof >/dev/null 2>&1 || return 0
  # || true: lsof exits 1 when nothing listens, which pipefail would pass on.
  pid="$( lsof -nP -iTCP:"$port" -sTCP:LISTEN -t 2>/dev/null | head -n 1 || true )"
  [ -n "$pid" ] || return 0
  name="$( ps -p "$pid" -o command= 2>/dev/null | awk '{ n = split( $1 , part , "/" ); $1 = part[ n ]; print }' | cut -c1-100 )"
  echo "${name:-unknown} (pid ${pid})"
}

# Whether a server answers /api/health on server.port, via the app's own
# healthcheck so the port and path stay in one place.
server_answers() {
  "$PYTHON" -m app health >/dev/null 2>&1
}

# The line number of a key in config.yaml, for messages that say exactly
# which line to change.
config_line() {
  grep -n "^[[:space:]]*$1:" "$config_file" 2>/dev/null | head -n 1 | cut -d: -f1
}

# Whether a docker container with this exact name is running. Quiet and
# false when docker is missing or its daemon is not up.
container_running() {
  command -v docker >/dev/null 2>&1 || return 1
  [ -n "$( docker ps --filter "name=^${1}\$" --format '{{.Names}}' 2>/dev/null )" ]
}
