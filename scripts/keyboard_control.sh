#!/usr/bin/env bash
set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
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
    "$@"
