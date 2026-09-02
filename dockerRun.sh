#!/usr/bin/env bash
#
# Media Tracker — build / run helper.
#
#   ./dockerRun.sh            build and (re)start the container
#   ./dockerRun.sh build      rebuild the image only
#   ./dockerRun.sh stop       stop and remove the container
#   ./dockerRun.sh restart    restart the running container
#   ./dockerRun.sh logs       follow the logs
#   ./dockerRun.sh status     show container state + health
#   ./dockerRun.sh backup     snapshot data/library.json into data/backups/
#
# Settings can go in a .env file next to this script instead of on the command
# line; anything already in the environment wins over it.
#
# Environment overrides:
#   PORT=8674          host port
#   BIND=0.0.0.0       host interface (use 127.0.0.1 to keep it local-only)
#   DATA_DIR=./data    where library.json lives
#   OFFLINE=1          run with --network none (no metadata lookups)
#   MT_TOKEN=secret   require ?k=secret once, then a cookie, for every request
#   TMDB_API_KEY=...   optional, upgrades metadata lookups
#   OMDB_API_KEY=...   optional
#   ENV_FILE=path      read settings from somewhere other than ./.env
#
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

c_g=$'\033[32m'; c_y=$'\033[33m'; c_b=$'\033[36m'; c_d=$'\033[2m'; c_0=$'\033[0m'
say() { printf '%s==>%s %s\n' "$c_b" "$c_0" "$*"; }
warn() { printf '%s!!%s %s\n' "$c_y" "$c_0" "$*" >&2; }

# Read KEY=VALUE lines out of .env.  Parsed rather than sourced: a settings
# file should not be able to run commands, and a stray backtick in an API key
# should not be able to surprise anyone.  A variable already in the
# environment wins, so `TMDB_API_KEY=... ./dockerRun.sh` still overrides.
load_env() {
  local file="${ENV_FILE:-$PWD/.env}"
  [[ -f "$file" ]] || return 0

  local line key value found=0
  while IFS= read -r line || [[ -n "$line" ]]; do
    line="${line#"${line%%[![:space:]]*}"}"          # drop leading space
    [[ -z "$line" || "$line" == "#"* ]] && continue
    [[ "$line" == "export "* ]] && line="${line#export }"
    [[ "$line" == *=* ]] || continue

    key="${line%%=*}"
    value="${line#*=}"
    key="${key%"${key##*[![:space:]]}"}"             # trim around the name
    [[ "$key" =~ ^[A-Za-z_][A-Za-z0-9_]*$ ]] || continue

    value="${value#"${value%%[![:space:]]*}"}"
    value="${value%"${value##*[![:space:]]}"}"
    if [[ ${#value} -ge 2 && "$value" == \"*\" ]]; then
      value="${value:1:${#value}-2}"
    elif [[ ${#value} -ge 2 && "$value" == \'*\' ]]; then
      value="${value:1:${#value}-2}"
    fi

    [[ -n "${!key+set}" ]] && continue               # the environment wins
    export "$key=$value"
    found=$((found + 1))
  done < "$file"

  [[ $found -gt 0 ]] && say "read $found setting(s) from ${file##*/}"
  return 0
}

load_env

IMAGE="${IMAGE:-media-tracker:latest}"
NAME="${NAME:-media-tracker}"
PORT="${PORT:-8674}"
BIND="${BIND:-0.0.0.0}"
DATA_DIR="${DATA_DIR:-$PWD/data}"
MEMORY="${MEMORY:-256m}"
CPUS="${CPUS:-1.0}"
PIDS="${PIDS:-128}"

need_docker() {
  command -v docker >/dev/null 2>&1 || { warn "docker not found on PATH"; exit 1; }
  docker info >/dev/null 2>&1 || { warn "docker daemon is not reachable"; exit 1; }
}

build() {
  say "building ${IMAGE}"
  if ! docker build --pull -t "$IMAGE" . ; then
    # BuildKit needs ~/.docker/buildx to be readable; fall back rather than fail.
    warn "buildkit failed - retrying with the legacy builder"
    DOCKER_BUILDKIT=0 docker build --pull -t "$IMAGE" .
  fi
}

stop() {
  if docker ps -aq -f "name=^${NAME}$" | grep -q .; then
    say "stopping ${NAME}"
    docker rm -f "$NAME" >/dev/null
  else
    say "${NAME} is not running"
  fi
}

is_vm_docker() {
  local endpoint
  endpoint="$(docker context inspect --format '{{range .Endpoints}}{{.Host}}{{end}}' 2>/dev/null || true)"
  [[ "$endpoint" == *".colima"* || "$endpoint" == *".lima"* ]]
}

lan_ip() {
  case "$(uname -s)" in
    Darwin) ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true ;;
    *) hostname -I 2>/dev/null | awk '{print $1}' ;;
  esac
}

run() {
  mkdir -p "$DATA_DIR" "$DATA_DIR/backups"
  stop

  # Hardening notes:
  #   --read-only              root filesystem is immutable; only the mounts below are writable
  #   --tmpfs /tmp             small, noexec scratch space
  #   --cap-drop ALL           the process needs no Linux capabilities at all
  #   --no-new-privileges      setuid binaries cannot escalate
  #   --user $(id -u):$(id -g) files written to ./data stay owned by you, not root
  #   --pids/--memory/--cpus   a runaway process cannot take the host down
  local args=(
    --name "$NAME"
    --detach
    --restart unless-stopped
    --read-only
    --tmpfs "/tmp:rw,noexec,nosuid,nodev,size=16m"
    --cap-drop ALL
    --security-opt no-new-privileges:true
    --pids-limit "$PIDS"
    --memory "$MEMORY" --memory-swap "$MEMORY"
    --cpus "$CPUS"
    --user "$(id -u):$(id -g)"
    --volume "$DATA_DIR:/data:rw"
    --publish "${BIND}:${PORT}:8080"
    --env MT_PORT=8080
  )

  # Every MT_* setting and every API key travels into the container. The
  # paths and the port are the container's own business and are left alone.
  local name
  for name in $(compgen -v); do
    case "$name" in
      MT_HOST|MT_PORT|MT_DATA_DIR|MT_PUBLIC_DIR|MT_SEED_DIR) continue ;;
      HMT_HOST|HMT_PORT|HMT_DATA_DIR|HMT_PUBLIC_DIR|HMT_SEED_DIR) continue ;;
      MT_*|HMT_*|*_API_KEY) ;;                 # HMT_ was the old prefix
      *) continue ;;
    esac
    [[ -n "${!name:-}" ]] || continue
    args+=(--env "$name=${!name}")
  done

  if [[ "${OFFLINE:-0}" == "1" ]]; then
    args+=(--network none --env MT_ENABLE_NET=0)
    say "offline mode: metadata lookups disabled"
  fi

  say "starting ${NAME}"
  docker run "${args[@]}" "$IMAGE" >/dev/null

  # Wait for it to actually answer before claiming it is up.
  local ready=""
  for _ in $(seq 1 40); do
    if curl -fsS -m 2 -o /dev/null "http://127.0.0.1:${PORT}/api/health" 2>/dev/null; then
      ready=1; break
    fi
    sleep 0.25
  done

  if [[ -z "$ready" ]]; then
    warn "the container started but nothing answers on 127.0.0.1:${PORT}"
    warn "check './dockerRun.sh logs' - the port may be taken by something else"
    return 1
  fi

  printf '\n  %sMedia Tracker is up%s\n' "$c_g" "$c_0"
  printf '    local   %shttp://localhost:%s%s\n' "$c_b" "$PORT" "$c_0"

  # Don't advertise a LAN address without proving it works. Docker inside a
  # Lima/Colima VM forwards published ports to loopback only, so the host's
  # own IP is unreachable no matter what `docker ps` claims the binding is.
  local ip; ip="$(lan_ip)"
  if [[ -n "$ip" && "$BIND" != "127.0.0.1" ]]; then
    if curl -fsS -m 2 -o /dev/null "http://${ip}:${PORT}/api/health" 2>/dev/null; then
      printf '    phone   %shttp://%s:%s%s\n' "$c_b" "$ip" "$PORT" "$c_0"
    else
      printf '    phone   %snot reachable at %s:%s%s\n' "$c_y" "$ip" "$PORT" "$c_0"
      if is_vm_docker; then
        printf '            %sColima/Lima forwards published ports to localhost only.%s\n' "$c_d" "$c_0"
        printf '            %sfor the LAN:  colima stop && colima start --network-address%s\n' "$c_d" "$c_0"
        printf '            %sor put a tunnel / reverse proxy in front of localhost:%s%s\n' "$c_d" "$PORT" "$c_0"
      else
        printf '            %scheck the host firewall, or use a tunnel in front of localhost:%s%s\n' "$c_d" "$PORT" "$c_0"
      fi
    fi
  fi

  printf '    data    %s%s%s\n' "$c_d" "$DATA_DIR/library.json" "$c_0"
  printf '    logs    %s./dockerRun.sh logs%s\n' "$c_d" "$c_0"

  if [[ -z "${MT_TOKEN:-}" ]]; then
    printf '\n  %sno MT_TOKEN set%s - anything that can reach this port can read and\n' "$c_y" "$c_0"
    printf '  edit the library. Fine on loopback; set one before exposing it publicly.\n'
  fi
  printf '\n'
}

backup() {
  local src="$DATA_DIR/library.json"
  [[ -f "$src" ]] || { warn "no library at $src"; exit 1; }
  mkdir -p "$DATA_DIR/backups"
  local dst="$DATA_DIR/backups/library-manual-$(date +%Y%m%d-%H%M%S).json"
  cp "$src" "$dst"
  say "saved $dst"
}

case "${1:-up}" in
  up|run|start)
    # Always build: the app is baked into the image, so an edit that was not
    # rebuilt is an edit you cannot see. Docker's layer cache makes the
    # no-change case a couple of seconds.
    need_docker
    build
    run
    ;;
  build)   need_docker; build ;;
  rebuild) need_docker; build; run ;;
  stop|down) need_docker; stop ;;
  restart) need_docker; docker restart "$NAME" >/dev/null && say "restarted" ;;
  logs)    need_docker; docker logs -f --tail 100 "$NAME" ;;
  status)
    need_docker
    docker ps -a -f "name=^${NAME}$" --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'
    ;;
  backup)  backup ;;
  *) warn "unknown command: $1"; sed -n '2,25p' "$0"; exit 2 ;;
esac