#!/usr/bin/env bash
# 单独打开小车控制台 GUI

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

while [ $# -gt 0 ]; do
    case "$1" in
        --profile)
            [ $# -ge 2 ] || { echo "--profile requires a value" >&2; exit 2; }
            export ROBOT_PROFILE="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: ./scripts/open_car_gui.sh [--profile NAME]"
            exit 0
            ;;
        *)
            echo "Unknown option: $1" >&2
            exit 2
            ;;
    esac
done

source "$PROJECT_ROOT/config/robot.env"
source "$ROS_SETUP"
for setup_file in "${CAMERA_SETUP_FILES[@]}"; do
    [ -f "$setup_file" ] && source "$setup_file"
done
[ -f "$ROSBRIDGE_SETUP" ] && source "$ROSBRIDGE_SETUP"

exec python3 "$PROJECT_ROOT/src/car_gui.py"
