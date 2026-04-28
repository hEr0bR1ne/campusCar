#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ $# -lt 2 ]; then
    echo "Usage: $0 PROFILE ISOLATION [options] [-- command...]" >&2
    exit 2
fi

ROBOT_PROFILE_VALUE="$1"
CHASSIS_ISOLATION="$2"
shift 2

if [ "$ROBOT_PROFILE_VALUE" = "campus_car" ] || [ "$CHASSIS_ISOLATION" = "old_chassis" ]; then
    echo "This branch no longer supports the old campus_car chassis profile." >&2
    exit 2
fi

IMAGE="${CAMPUSCAR_DOCKER_IMAGE:-campuscar:humble}"
CONTAINER_NAME="campuscar-${CHASSIS_ISOLATION//_/-}"
BUILD_FIRST=0
NO_GUI=0
NO_DEVICES=0
DRY_RUN=0
COMMAND=()
EXTRA_DOCKER_ARGS=()
DOCKER_CMD=(docker)
if [ "${CAMPUSCAR_DOCKER_SUDO:-0}" = "1" ]; then
    DOCKER_CMD=(sudo docker)
fi

usage() {
    cat <<EOF
Usage: $0 ${ROBOT_PROFILE_VALUE} ${CHASSIS_ISOLATION} [options] [-- command...]

Run campusCar-new-chassis inside the Docker runtime with a fixed hardware profile.

Options:
  --build               Build the image before running
  --image NAME          Docker image tag, default: campuscar:humble
  --name NAME           Container name, default: ${CONTAINER_NAME}
  --no-gui              Do not mount X11 display
  --no-devices          Do not pass host /dev into the container
  --docker-arg ARG      Append one raw docker run argument
  --dry-run             Print docker command only
  -h, --help            Show this help

Examples:
  $0 ${ROBOT_PROFILE_VALUE} ${CHASSIS_ISOLATION}
  $0 ${ROBOT_PROFILE_VALUE} ${CHASSIS_ISOLATION} -- ./scripts/check_all.sh --profile ${ROBOT_PROFILE_VALUE}
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --build)
            BUILD_FIRST=1
            shift
            ;;
        --image)
            [ $# -ge 2 ] || { echo "--image requires a value" >&2; exit 2; }
            IMAGE="$2"
            shift 2
            ;;
        --name)
            [ $# -ge 2 ] || { echo "--name requires a value" >&2; exit 2; }
            CONTAINER_NAME="$2"
            shift 2
            ;;
        --no-gui)
            NO_GUI=1
            shift
            ;;
        --no-devices)
            NO_DEVICES=1
            shift
            ;;
        --docker-arg)
            [ $# -ge 2 ] || { echo "--docker-arg requires a value" >&2; exit 2; }
            EXTRA_DOCKER_ARGS+=("$2")
            shift 2
            ;;
        --dry-run)
            DRY_RUN=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        --)
            shift
            COMMAND=("$@")
            break
            ;;
        *)
            COMMAND=("$@")
            break
            ;;
    esac
done

if [ "${#COMMAND[@]}" -eq 0 ]; then
    COMMAND=(bash)
fi

if [ "$DRY_RUN" = "0" ]; then
    command -v "${DOCKER_CMD[0]}" >/dev/null 2>&1 || { echo "${DOCKER_CMD[0]} not found" >&2; exit 1; }
fi

if [ "$BUILD_FIRST" = "1" ] && [ "$DRY_RUN" = "0" ]; then
    "${PROJECT_ROOT}/scripts/docker_build.sh" --image "$IMAGE"
elif [ "$DRY_RUN" = "0" ] && ! "${DOCKER_CMD[@]}" image inspect "$IMAGE" >/dev/null 2>&1; then
    echo "Docker image not found: $IMAGE" >&2
    echo "Run: ./scripts/docker_build.sh --image $IMAGE" >&2
    exit 1
fi

tty_args=(-i)
if [ -t 0 ] && [ -t 1 ]; then
    tty_args+=(-t)
fi

docker_args=(
    run
    --rm
    "${tty_args[@]}"
    --name "$CONTAINER_NAME"
    --network host
    --ipc host
    --workdir /workspace/campusCar-new-chassis
    --env "ROBOT_PROFILE=${ROBOT_PROFILE_VALUE}"
    --env "CAMPUSCAR_CHASSIS_ISOLATION=${CHASSIS_ISOLATION}"
    --env "CAMPUSCAR_ROOT=/workspace/campusCar-new-chassis"
    --env "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}"
    --env "RMW_IMPLEMENTATION=${RMW_IMPLEMENTATION:-rmw_fastrtps_cpp}"
    --volume "${PROJECT_ROOT}:/workspace/campusCar-new-chassis"
)

if [ "$NO_DEVICES" = "0" ]; then
    docker_args+=(--privileged --volume /dev:/dev)
fi

if [ "$NO_GUI" = "0" ] && [ -n "${DISPLAY:-}" ]; then
    docker_args+=(
        --env "DISPLAY=${DISPLAY}"
        --env "QT_X11_NO_MITSHM=1"
        --volume /tmp/.X11-unix:/tmp/.X11-unix:rw
    )
    if [ -n "${XAUTHORITY:-}" ] && [ -f "$XAUTHORITY" ]; then
        docker_args+=(
            --env XAUTHORITY=/tmp/.campuscar.xauthority
            --volume "${XAUTHORITY}:/tmp/.campuscar.xauthority:ro"
        )
    fi
fi

for arg in "${EXTRA_DOCKER_ARGS[@]}"; do
    docker_args+=("$arg")
done

docker_args+=("$IMAGE" "${COMMAND[@]}")

if [ "$DRY_RUN" = "1" ]; then
    printf '%q ' "${DOCKER_CMD[@]}" "${docker_args[@]}"
    printf '\n'
    exit 0
fi

exec "${DOCKER_CMD[@]}" "${docker_args[@]}"
