#!/usr/bin/env bash
set -e

source_if_readable() {
    local setup_file="$1"
    if [ -n "$setup_file" ] && [ -f "$setup_file" ]; then
        set +u
        # shellcheck disable=SC1090
        source "$setup_file"
        set -u
    fi
}

export ROS_DISTRO="${ROS_DISTRO:-humble}"
export CAMPUSCAR_ROOT="${CAMPUSCAR_ROOT:-/workspace/campusCar-new-chassis}"

source_if_readable "/opt/ros/${ROS_DISTRO}/setup.bash"

if [ -f "${CAMPUSCAR_ROOT}/config/robot.env" ]; then
    set +u
    # shellcheck disable=SC1090
    source "${CAMPUSCAR_ROOT}/config/robot.env"
    set -u
fi

source_if_readable "${ROSBRIDGE_SETUP:-}"
source_if_readable "${HOVERBOARD_SETUP:-}"

exec "$@"
