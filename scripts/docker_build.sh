#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE="${CAMPUSCAR_DOCKER_IMAGE:-campuscar:humble}"
BASE_IMAGE="${CAMPUSCAR_DOCKER_BASE_IMAGE:-ros:humble-ros-base-jammy}"
NO_CACHE=0
INSTALL_MEDIAMTX="${INSTALL_MEDIAMTX:-1}"
DOCKER_CMD=(docker)
if [ "${CAMPUSCAR_DOCKER_SUDO:-0}" = "1" ]; then
    DOCKER_CMD=(sudo docker)
fi

usage() {
    cat <<'EOF'
Usage: ./scripts/docker_build.sh [options]

Build the campusCar ROS2 Humble runtime image.

Options:
  --image NAME           Docker image tag, default: campuscar:humble
  --base-image NAME      Base image, default: ros:humble-ros-base-jammy
  --no-cache            Build without Docker layer cache
  --no-mediamtx         Do not install mediamtx into the image
  -h, --help            Show this help
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
        --no-cache)
            NO_CACHE=1
            shift
            ;;
        --no-mediamtx)
            INSTALL_MEDIAMTX=0
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

command -v "${DOCKER_CMD[0]}" >/dev/null 2>&1 || { echo "${DOCKER_CMD[0]} not found" >&2; exit 1; }

build_args=(
    --file "${PROJECT_ROOT}/docker/Dockerfile.humble"
    --tag "$IMAGE"
    --build-arg "USER_UID=$(id -u)"
    --build-arg "USER_GID=$(id -g)"
    --build-arg "BASE_IMAGE=${BASE_IMAGE}"
    --build-arg "INSTALL_MEDIAMTX=${INSTALL_MEDIAMTX}"
)

if [ "$NO_CACHE" = "1" ]; then
    build_args+=(--no-cache)
fi

echo "[docker-build] image: $IMAGE"
echo "[docker-build] base image: $BASE_IMAGE"
"${DOCKER_CMD[@]}" build "${build_args[@]}" "$PROJECT_ROOT"
