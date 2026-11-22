#!/usr/bin/env bash
# Restart the running container, without rebuilding.
#
# The container is the one the last docker/run.sh started (load_last_deployment
# in docker/lib.sh). Use it to pick up a config.yaml an editor replaced rather
# than saved in place, or to clear a stuck process. To deploy new code, use
# docker/update.sh (pull, rebuild, replace) or docker/run.sh (rebuild, replace).
set -euo pipefail
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

if [ $# -gt 0 ]; then
  echo "usage: docker/restart.sh" >&2
  exit 1
fi

source docker/lib.sh
load_last_deployment

echo "Restarting ${docker_container}..."
docker restart "$docker_container" >/dev/null
wait_healthy
echo ""
echo "Ready: ${docker_url}"
