#!/usr/bin/env bash
# Pull the latest code and redeploy: git pull, then docker/run.sh (rebuild,
# replace the container, wait until healthy).
#
#   docker/update.sh [--accept-docker-changes]
#
# Only on master or main, and only a fast-forward: a checkout with local
# commits or on another branch stops here, before anything is rebuilt.
# It always rebuilds, even when the pull brought nothing new.
set -euo pipefail
cd "$( dirname "${BASH_SOURCE[0]}" )/.."

BRANCH="$( git symbolic-ref --quiet --short HEAD 2>/dev/null || true )"
case "$BRANCH" in
  master|main) ;;
  *)
    echo "ERROR: this checkout is on ${BRANCH:-a detached HEAD}, not master or main." >&2
    echo "       Nothing was pulled or rebuilt." >&2
    exit 1
    ;;
esac

echo "Pulling origin ${BRANCH}..."
if ! git pull --ff-only origin "$BRANCH"; then
  echo "" >&2
  echo "ERROR: git pull failed (above). Nothing was rebuilt; the container is unchanged." >&2
  exit 1
fi
echo ""

exec docker/run.sh "$@"
