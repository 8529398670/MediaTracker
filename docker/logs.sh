#!/usr/bin/env bash
# Follow the container's log (docker logs -f).
#
#   docker/logs.sh                 the last 200 lines, then follow
#   docker/logs.sh --tail 1000     any docker logs flags instead
#   docker/logs.sh --since 1h
#
# The container is the one the last docker/run.sh started. Ctrl-C stops
# following; the container keeps running.
set -euo pipefail
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

source docker/lib.sh
load_last_deployment

if [ $# -eq 0 ]; then
  set -- --tail 200
fi
exec docker logs -f "$@" "$docker_container"
