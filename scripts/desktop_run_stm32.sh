#!/usr/bin/env bash
# Desktop launcher wrapper for the STM32 chassis Docker runtime.

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROFILE="stm32_hoverboard_4wd"
MODE="${1:-fullstack}"

"${PROJECT_ROOT}/scripts/bind_ch341_serial.sh" || true

run_with_docker_group() {
    local cmd="$1"

    if docker ps >/dev/null 2>&1; then
        bash -lc "$cmd"
        return
    fi

    if getent group docker | grep -Eq "(^|[:,])$(id -un)(,|$)" \
        && sg docker -c 'docker ps >/dev/null 2>&1'; then
        sg docker -c "$cmd"
        return
    fi

    CAMPUSCAR_DOCKER_SUDO=1 bash -lc "$cmd"
}

case "$MODE" in
    fullstack)
        run_with_docker_group "cd '$PROJECT_ROOT' && ./scripts/docker_run_stm32.sh -- ./scripts/launch_all.sh --profile '$PROFILE'"
        ;;
    gui)
        run_with_docker_group "cd '$PROJECT_ROOT' && ./scripts/docker_run_stm32.sh --name campuscar-stm32-gui -- ./scripts/open_car_gui.sh --profile '$PROFILE'"
        ;;
    *)
        echo "Usage: $0 [fullstack|gui]" >&2
        exit 2
        ;;
esac
