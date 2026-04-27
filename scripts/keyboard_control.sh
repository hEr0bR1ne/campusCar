#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

PASSTHROUGH_ARGS=()
while [ $# -gt 0 ]; do
    case "$1" in
        --profile)
            [ $# -ge 2 ] || { echo "--profile requires a value" >&2; exit 2; }
            export ROBOT_PROFILE="$2"
            shift 2
            ;;
        *)
            PASSTHROUGH_ARGS+=("$1")
            shift
            ;;
    esac
done

source "${PROJECT_ROOT}/config/robot.env"

if [ ! -f "$ROS_SETUP" ]; then
    echo "ROS setup not found: $ROS_SETUP" >&2
    exit 1
fi

source "$ROS_SETUP"

exec python3 "${PROJECT_ROOT}/src/keyboard_control.py" \
    --topic "${CMD_VEL_TOPIC}" \
    --linear "${DEFAULT_LINEAR_SPEED}" \
    --angular "${DEFAULT_ANGULAR_SPEED}" \
    --max-linear "${MAX_LINEAR_SPEED}" \
    --max-angular "${MAX_ANGULAR_SPEED}" \
    "${PASSTHROUGH_ARGS[@]}"
