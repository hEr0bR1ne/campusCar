#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${CAMPUSCAR_DOCKER_IMAGE:-campuscar:humble}"
BASE_IMAGE="${CAMPUSCAR_DOCKER_BASE_IMAGE:-ros:humble-ros-base-jammy}"
SKIP_BUILD=0
SKIP_HELLO=0

usage() {
    cat <<'EOF'
Usage: ./scripts/install_docker.sh [options]

Install Docker from Ubuntu 22.04 apt packages, enable the service, add the
current user to the docker group, and optionally build the campusCar image.

Options:
  --image NAME       Docker image tag to build, default: campuscar:humble
  --base-image NAME  Docker base image, default: ros:humble-ros-base-jammy
  --skip-build       Install Docker only
  --skip-hello       Skip hello-world smoke test
  -h, --help         Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --image)
            [ $# -ge 2 ] || { echo "--image requires a value" >&2; exit 2; }
            IMAGE="$2"
            shift 2
            ;;
        --base-image)
            [ $# -ge 2 ] || { echo "--base-image requires a value" >&2; exit 2; }
            BASE_IMAGE="$2"
            shift 2
            ;;
        --skip-build)
            SKIP_BUILD=1
            shift
            ;;
        --skip-hello)
            SKIP_HELLO=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            usage >&2
            exit 2
            ;;
    esac
done

set +u
# shellcheck disable=SC1090
[ -f "${PROJECT_ROOT}/config/robot.env" ] && source "${PROJECT_ROOT}/config/robot.env" >/dev/null 2>&1 || true
set -u

sudo_run() {
    if [ "$(id -u)" -eq 0 ]; then
        "$@"
    elif [ -n "${SUDO_PASS:-}" ]; then
        printf '%s\n' "$SUDO_PASS" | sudo -S "$@"
    else
        sudo "$@"
    fi
}

log() { printf '[docker-install] %s\n' "$*"; }

log "Installing Docker apt packages"
sudo_run apt-get update
sudo_run apt-get install -y docker.io docker-buildx docker-compose-v2

if getent group docker >/dev/null 2>&1; then
    log "Adding ${USER:-$(id -un)} to docker group"
    sudo_run usermod -aG docker "${USER:-$(id -un)}"
fi

log "Enabling and starting Docker service"
sudo_run systemctl enable --now docker

log "Docker version"
sudo_run docker --version
sudo_run docker compose version

if [ "$SKIP_HELLO" = "0" ]; then
    log "Running Docker hello-world smoke test"
    sudo_run docker run --rm hello-world
fi

if [ "$SKIP_BUILD" = "0" ]; then
    log "Building campusCar image: $IMAGE"
    if sg docker -c 'docker ps >/dev/null 2>&1'; then
        sg docker -c "cd '${PROJECT_ROOT}' && ./scripts/docker_build.sh --image '${IMAGE}' --base-image '${BASE_IMAGE}'"
    else
        CAMPUSCAR_DOCKER_SUDO=1 "${PROJECT_ROOT}/scripts/docker_build.sh" --image "$IMAGE" --base-image "$BASE_IMAGE"
    fi
fi

cat <<'EOF'
[docker-install] Done.
[docker-install] The user was added to the docker group. For non-sudo docker
[docker-install] commands, log out and log back in, or start a new shell with:
[docker-install]   newgrp docker
EOF
