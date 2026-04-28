#!/usr/bin/env bash
# ============================================================
# Start STM32 dual-UART 4WD chassis through hoverboard_driver
# ============================================================

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: ./scripts/stm32_hoverboard_start.sh [--profile NAME]

Start the STM32 hoverboard-style chassis driver. Default profile should be
stm32_hoverboard_4wd.
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --profile)
            [ $# -ge 2 ] || { echo "--profile requires a value" >&2; exit 2; }
            export ROBOT_PROFILE="$2"
            shift 2
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

source "${PROJECT_ROOT}/config/robot.env"

if [ ! -f "$ROS_SETUP" ]; then
    echo "ROS setup not found: $ROS_SETUP" >&2
    exit 1
fi
if [ ! -f "$HOVERBOARD_SETUP" ]; then
    echo "hoverboard_driver setup not found: $HOVERBOARD_SETUP" >&2
    echo "Run: ./scripts/deploy_dependencies.sh --profile ${ROBOT_PROFILE}" >&2
    exit 1
fi

for dev in "$HOVERBOARD_FRONT_DEVICE" "$HOVERBOARD_REAR_DEVICE"; do
    if [ ! -e "$dev" ]; then
        echo "Serial device not found: $dev" >&2
        echo "Set HOVERBOARD_FRONT_DEVICE/HOVERBOARD_REAR_DEVICE or use /dev/serial/by-id paths." >&2
        exit 1
    fi
done
if [ "$HOVERBOARD_FRONT_DEVICE" = "$HOVERBOARD_REAR_DEVICE" ]; then
    echo "Front and rear serial devices are the same: $HOVERBOARD_FRONT_DEVICE" >&2
    exit 1
fi

set +u
# shellcheck disable=SC1090
source "$ROS_SETUP"
# shellcheck disable=SC1090
source "$HOVERBOARD_SETUP"
set -u

exec ros2 launch hoverboard_driver diffbot.launch.py \
    front_device:="$HOVERBOARD_FRONT_DEVICE" \
    rear_device:="$HOVERBOARD_REAR_DEVICE" \
    feedback_format:="$HOVERBOARD_FEEDBACK_FORMAT" \
    wheel_radius:="$HOVERBOARD_WHEEL_RADIUS" \
    max_velocity:="$HOVERBOARD_MAX_VELOCITY" \
    command_limit_rpm:="$HOVERBOARD_COMMAND_LIMIT_RPM"
