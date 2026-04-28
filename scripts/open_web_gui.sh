#!/usr/bin/env bash
# 单独启动网页控制台（不启动相机/RTK/UE 全栈）

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

# shellcheck disable=SC1090
source "$PROJECT_ROOT/config/robot.env"
# shellcheck disable=SC1090
source "$ROS_SETUP"
[ -f "$ORBBEC_SETUP" ] && source "$ORBBEC_SETUP"
[ -f "$ROSBRIDGE_SETUP" ] && source "$ROSBRIDGE_SETUP"

exec python3 "$PROJECT_ROOT/src/car_web_gui.py" --port "${WEB_GUI_PORT:-8088}"
