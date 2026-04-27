#!/usr/bin/env bash
# 单独打开小车控制台 GUI

set -e

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

source "$PROJECT_ROOT/config/robot.env"
source "$ROS_SETUP"
[ -f "$ORBBEC_SETUP" ] && source "$ORBBEC_SETUP"
[ -f "$ROSBRIDGE_SETUP" ] && source "$ROSBRIDGE_SETUP"

exec python3 "$PROJECT_ROOT/src/car_gui.py"
