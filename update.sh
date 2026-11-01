#!/usr/bin/env bash
#
# Media Tracker — put the code in this folder into the running container.
#
#   ./update.sh              rebuild the image, replace the container, check it took
#   ./update.sh --tests      run the UI suite first, and stop if anything fails
#   ./update.sh --no-verify  skip the check at the end
#
# Why this exists. `./dockerRun.sh build` rebuilds the *image* and stops there:
# the container carries on running the image it was started from, so an edit you
# have built is still an edit you cannot see. The front end is baked in at
# COPY time — only ./data is a mount — so nothing on screen changes until the
# container is replaced. That is the step this script never skips, and then it
# proves it rather than saying it: the container has to be running the image we
# just built, and that image has to hold the files that are on disk.
#
# Your library is safe: it lives in ./data, which is a bind mount and is not
# touched by a rebuild.
#
set -euo pipefail

cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

IMAGE="${IMAGE:-media-tracker:latest}"
NAME="${NAME:-media-tracker}"

c_g=$'\033[32m'; c_y=$'\033[33m'; c_r=$'\033[31m'; c_b=$'\033[36m'; c_d=$'\033[2m'; c_0=$'\033[0m'
say()  { printf '%s==>%s %s\n' "$c_b" "$c_0" "$*"; }
warn() { printf '%s!!%s %s\n' "$c_y" "$c_0" "$*" >&2; }
die()  { printf '%s!!%s %s\n' "$c_r" "$c_0" "$*" >&2; exit 1; }

tests=0
verify=1
for arg in "$@"; do
  case "$arg" in
    --tests)     tests=1 ;;
    --no-tests)  tests=0 ;;
    --no-verify) verify=0 ;;
    -h|--help)   sed -n '2,20p' "$0"; exit 0 ;;
    *)           die "unknown option: $arg  (try --help)" ;;
  esac
done

command -v docker >/dev/null 2>&1 || die "docker not found on PATH"
docker info >/dev/null 2>&1 || die "docker daemon is not reachable"

# The files that are actually served, as the Dockerfile copies them. Keep this
# in step with the COPY lines if they ever grow a third directory.
copied=(public server)

# ---------------------------------------------------------------- the tests

if [[ $tests -eq 1 ]]; then
  say "running the UI suite"
  bash tests/ui.sh || die "tests failed - nothing was deployed"
fi

# ------------------------------------------------- build, then replace it all

was="$(docker inspect "$NAME" --format '{{.Image}}' 2>/dev/null || true)"

# dockerRun.sh owns the build flags and every run flag - the hardening, the
# mount, the port, which MT_* settings travel in. Reuse it rather than keep a
# second copy of all that here and watch the two drift apart.
say "rebuilding and restarting via dockerRun.sh"
./dockerRun.sh rebuild

now="$(docker inspect "$NAME" --format '{{.Image}}')"
built="$(docker image inspect "$IMAGE" --format '{{.Id}}')"

# ------------------------------------------------------------------- the check

if [[ $verify -eq 0 ]]; then
  say "skipped the check (--no-verify)"
  exit 0
fi

# 1. Is the container running the image we just built, rather than the one it
#    happened to be started from? This is the exact thing `build` alone misses.
if [[ "$now" != "$built" ]]; then
  die "the container is still on ${now:7:12}, not the image just built (${built:7:12})"
fi

# 2. Does that image hold what is on disk? Hash the copied files here and the
#    same list inside the container, and compare the hashes only - the paths
#    differ by the /app prefix, the contents should not differ at all.
list="$(find "${copied[@]}" -type f ! -name '*.pyc' ! -path '*__pycache__*' | LC_ALL=C sort)"
[[ -n "$list" ]] || die "found no files to check under: ${copied[*]}"

disk="$(printf '%s\n' "$list" | xargs sha256sum | awk '{print $1}' | sha256sum | cut -d' ' -f1)"
live="$(printf '%s\n' "$list" \
  | docker exec -i "$NAME" sh -c 'cd /app && xargs sha256sum' \
  | awk '{print $1}' | sha256sum | cut -d' ' -f1)" \
  || die "could not read the files back out of the container"

if [[ "$disk" != "$live" ]]; then
  warn "the container is not serving the files in this folder"
  warn "the first ones that differ:"
  printf '%s\n' "$list" | while IFS= read -r f; do
    a="$(sha256sum "$f" | cut -d' ' -f1)"
    b="$(docker exec "$NAME" sha256sum "/app/$f" 2>/dev/null | cut -d' ' -f1 || echo missing)"
    [[ "$a" == "$b" ]] || printf '    %s%s%s\n' "$c_y" "$f" "$c_0"
  done | head -10
  die "check .dockerignore, and that the Dockerfile copies: ${copied[*]}"
fi

files="$(printf '%s\n' "$list" | wc -l | tr -d ' ')"
printf '\n  %sup to date%s  %s%s files, image %s%s\n' \
  "$c_g" "$c_0" "$c_d" "$files" "${built:7:12}" "$c_0"
if [[ -n "$was" && "$was" != "$now" ]]; then
  printf '  %swas on %s - hard-reload the browser (ctrl/cmd-shift-R) to drop the old JS and CSS%s\n' \
    "$c_d" "${was:7:12}" "$c_0"
fi
printf '\n'
