# Shared by the docker/*.sh scripts. Sourced, not run, from the
# project root -- which is also the build context.
#
# build_image builds the image and then reads config.yaml *through it*: the
# app inside is the YAML parser, so these scripts get exactly the defaults and
# validation the server uses, and the host needs nothing but Docker -- not
# even Python. That ordering is also why the image name -- which lives in
# config.yaml like everything else -- is applied as a tag after the build
# rather than passed to it.
#
# Afterwards these are set: IMAGE_ID, CONFIG_FILE, SECRET_FILE, VERSION,
# DOCKER_SETTINGS (the assignments below, as text), and every docker_* /
# server_* value printed by `config shell docker` (see
# app/core/config_command.py for the list), including docker_url.

CONFIG_FILE="$( pwd )/config/config.yaml"
SECRET_FILE="$( pwd )/config/secret.key"
DOCKERFILE="docker/Dockerfile"

# The container sees them here (app/core/layout_container.py): config.yaml
# writable, so the owner's Settings screen can save it; secret.key read-only.
CONTAINER_CONFIG="/app/config/config.yaml"
CONTAINER_SECRET="/app/config/secret.key"

# config_dir_run runs the app with the project's config/ folder mounted at
# /work, as the invoking user: for the commands that create or rewrite files
# there (init, secret, migrate). Mounting the folder rather than single files
# is what lets them create a file, and replace config.yaml by renaming a new
# copy over it, so a failure half way leaves the old file whole.
config_dir_run() {
  docker run --rm --network none --read-only --cap-drop ALL \
    --user "$( id -u ):$( id -g )" \
    -v "$( dirname "$CONFIG_FILE" ):/work" \
    "$IMAGE_ID" config "$@"
}

# config_run runs the freshly built image in a throwaway container that can do
# nothing but read config.yaml: no network, read-only, no capabilities. It runs
# as the invoking user, so a 0600 config.yaml owned by that user is readable on
# Linux as well as macOS.
#
# The file is only mounted when it exists. Mounting a missing file makes Docker
# create an empty *directory* in its place, which then breaks every later run.
config_run() {
  local mount=()
  if [ -f "$CONFIG_FILE" ]; then
    mount=( -v "${CONFIG_FILE}:${CONTAINER_CONFIG}:ro" )
  fi
  docker run --rm --network none --read-only --cap-drop ALL \
    --user "$( id -u ):$( id -g )" \
    ${mount[@]+"${mount[@]}"} \
    "$IMAGE_ID" config "$@"
}

# build_image [extra-tag]
build_image() {
  local extra_tag="${1:-}"
  local commit build_date id_file assignments

  if ! command -v docker >/dev/null 2>&1; then
    echo "ERROR: docker is not on PATH. Install Docker (or colima) and re-run." >&2
    exit 1
  fi
  if ! docker info >/dev/null 2>&1; then
    echo "ERROR: docker is installed but its daemon is not answering (docker info failed)." >&2
    echo "       Start Docker Desktop, or \`colima start\`, and re-run." >&2
    exit 1
  fi

  local mounted
  for mounted in "$CONFIG_FILE" "$SECRET_FILE"; do
    if [ -d "$mounted" ]; then
      echo "ERROR: ${mounted} is a directory. Docker creates one when asked to" >&2
      echo "       mount a file that does not exist. Remove it and re-run." >&2
      exit 1
    fi
  done

  # Version metadata, stamped into the image so that
  # `docker exec <name> python -m app version` identifies the build.
  # The version is the UTC build time (2026.10.23-1412): it sorts, it says
  # when, and the commit hash is stamped separately alongside it.
  VERSION="$( date -u +%Y.%m.%d-%H%M )"
  commit="$( git rev-parse --short HEAD 2>/dev/null || echo "unknown" )"
  build_date="$( date -u +%Y-%m-%dT%H:%M:%SZ )"
  # The skill and commit this app was scaffolded from, for /api/me. Empty
  # without .skill-origin.yaml.
  skill="$( sed -n 's/^skill:[[:space:]]*//p' .skill-origin.yaml 2>/dev/null | head -n 1 | tr -d "\"' \r" )"
  skill_commit="$( sed -n 's/^commit:[[:space:]]*//p' .skill-origin.yaml 2>/dev/null | head -n 1 | tr -d "\"' \r" )"

  id_file="$( mktemp )"
  echo "Building the image from ${DOCKERFILE}, version ${VERSION} (commit ${commit})"
  if [ -f "$CONFIG_FILE" ]; then
    echo "  config  ${CONFIG_FILE}"
  else
    echo "  config  none yet at ${CONFIG_FILE} -- the image is named from the defaults"
  fi
  echo ""
  if ! docker build \
         --file "$DOCKERFILE" \
         --iidfile "$id_file" \
         --build-arg "VERSION=${VERSION}" \
         --build-arg "COMMIT=${commit}" \
         --build-arg "BUILD_DATE=${build_date}" \
         --build-arg "SKILL=${skill}" \
         --build-arg "SKILL_COMMIT=${skill_commit}" \
         .; then
    rm -f "$id_file"
    echo "" >&2
    echo "ERROR: docker build failed (above). Nothing was started or replaced." >&2
    exit 1
  fi
  IMAGE_ID="$( cat "$id_file" )"
  rm -f "$id_file"

  # With no config.yaml yet this reads the defaults, which is all a CI build
  # needs to name the image. docker/run.sh creates the real file before it
  # starts anything.
  #
  # Assigned before it is eval'd so that a validation error stops the script:
  # `eval "$( failing )"` would quietly eval nothing and carry on.
  assignments="$( config_run shell docker )"
  eval "$assignments"
  DOCKER_SETTINGS="$assignments"

  # Before anything acts on docker.*: the tag below, and whatever the calling
  # script does with the container name, data_dir and ports.
  confirm_docker_changes

  docker tag "$IMAGE_ID" "${docker_image}:latest"
  if [ -n "$extra_tag" ]; then
    docker tag "$IMAGE_ID" "${docker_image}:${extra_tag}"
    echo "Also tagged ${docker_image}:${extra_tag}"
  fi
  echo "Built ${docker_image}:latest (${VERSION}, image ${IMAGE_ID#sha256:})"
}

# confirm_docker_changes stops when the docker: section differs from the one
# the last start used, until someone at the host says yes. config.yaml is
# mounted writable so the Settings screen can save it, which means code inside
# a compromised container could rewrite docker.* -- the container name this
# script `docker rm -f`s, the address it publishes on, the image tag, the
# limits. The copy that counts is .run/docker.last: written here on the host,
# never mounted into the container. No copy yet (a first start) means nothing
# to compare, so it carries on. ACCEPT_DOCKER_CHANGES=true (docker/run.sh
# --accept-docker-changes) says yes without asking. A yes is recorded at once.
confirm_docker_changes() {
  local last=".run/docker.last"
  [ -f "$last" ] || return 0
  [ "$( cat "$last" )" != "$DOCKER_SETTINGS" ] || return 0
  echo "docker: settings changed since the last run (config/config.yaml):"
  # diff exits 1 when its inputs differ, which they always do here. Under
  # pipefail that would end the script silently, so the notice is made unable
  # to fail.
  diff <( cat "$last" ) <( printf '%s\n' "$DOCKER_SETTINGS" ) \
    | sed -n 's/^< /  was  /p; s/^> /  now  /p' || true
  echo ""
  if [ "${ACCEPT_DOCKER_CHANGES:-false}" != "true" ]; then
    if [ ! -t 0 ]; then
      echo "ERROR: not applying changed docker: settings without a yes. config.yaml can" >&2
      echo "       be written from inside the container, so check them above, then run" >&2
      echo "       docker/run.sh --accept-docker-changes (or answer at a terminal)." >&2
      exit 1
    fi
    local answer=""
    read -r -p "Apply these docker: changes? [y/N] " answer || true
    case "$answer" in
      y|Y|yes|YES) ;;
      *)
        echo "Not applied. Nothing was started or replaced." >&2
        exit 1
        ;;
    esac
  fi
  mkdir -p .run
  printf '%s\n' "$DOCKER_SETTINGS" > "$last"
  echo ""
}

# resolve_data_dir sets DATA_DIR. docker.data_dir is relative to the project
# directory, like every docker: path.
resolve_data_dir() {
  case "$docker_data_dir" in
    /*) DATA_DIR="$docker_data_dir" ;;
    *)  DATA_DIR="$( pwd )/${docker_data_dir#./}" ;;
  esac
  DATA_DIR="${DATA_DIR%/}"
}

# create_config writes config.yaml from the image's defaults, and a
# secret.key with a fresh key beside it unless one is there. Both are created
# as the invoking user, mode 0600, and neither ever replaces an existing file.
create_config() {
  mkdir -p "$( dirname "$CONFIG_FILE" )"
  config_dir_run init --dir /work >/dev/null
}

# create_secret writes secret.key alone: for a config.yaml copied from
# config.example.yaml.
create_secret() {
  config_dir_run secret --file /work/secret.key >/dev/null
}

# migrate_config moves server.secret_key out of a config.yaml written before
# secret.key existed. It prints only when it did something.
migrate_config() {
  config_dir_run migrate --dir /work
}

# load_last_deployment sets the docker_* values (docker_container, docker_url,
# ...) of the last successful docker/run.sh, from .run/docker.last: written on
# the host, never mounted into the container, so -- unlike config.yaml, which
# the container can write -- it is safe to act on without a rebuild. For the
# scripts that work on the running deployment rather than build one
# (docker/restart.sh, docker/logs.sh).
load_last_deployment() {
  local last=".run/docker.last"
  if [ ! -f "$last" ]; then
    echo "ERROR: no deployment from this checkout yet (no ${last})." >&2
    echo "       Start one with docker/run.sh first." >&2
    exit 1
  fi
  eval "$( cat "$last" )"
  if [ -z "$( docker ps -a -q --filter "name=^${docker_container}\$" )" ]; then
    echo "ERROR: there is no ${docker_container} container. Start it with docker/run.sh." >&2
    exit 1
  fi
}

# wait_healthy waits up to 30 seconds for the container to pass the image's
# own healthcheck (python -m app health). If it stops or never answers, it
# says which, shows the last log lines, and exits 1 instead of announcing a
# success that is not there.
wait_healthy() {
  local status="starting" state
  echo "Waiting for it to answer (up to 30 seconds)..."
  for _ in $( seq 1 60 ); do
    sleep 0.5
    state="$( docker inspect -f '{{.State.Status}}' "$docker_container" 2>/dev/null || echo "gone" )"
    if [ "$state" != "running" ]; then
      status="$state"
      break
    fi
    if docker exec "$docker_container" python -m app health >/dev/null 2>&1; then
      status="healthy"
      break
    fi
  done

  if [ "$status" != "healthy" ]; then
    echo "" >&2
    if [ "$status" = "starting" ]; then
      echo "ERROR: ${docker_container} is running but not answering after 30 seconds." >&2
    else
      echo "ERROR: ${docker_container} stopped (status: ${status}, exit code $( docker inspect -f '{{.State.ExitCode}}' "$docker_container" 2>/dev/null || echo "?" ))." >&2
    fi
    echo "       Its last log lines:" >&2
    echo "" >&2
    docker logs --tail 40 "$docker_container" 2>&1 | sed 's/^/         /' >&2
    exit 1
  fi
}
