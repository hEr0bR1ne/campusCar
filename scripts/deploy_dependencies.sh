#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${PROJECT_ROOT}/config/robot.env"

for arg_index in "$@"; do
    if [[ "${_EXPECT_PROFILE_VALUE:-0}" -eq 1 ]]; then
        export ROBOT_PROFILE="$arg_index"
        _EXPECT_PROFILE_VALUE=0
        continue
    fi
    if [[ "$arg_index" == "--profile" ]]; then
        _EXPECT_PROFILE_VALUE=1
    fi
done
unset _EXPECT_PROFILE_VALUE

if [[ -f "$ENV_FILE" ]]; then
    # shellcheck disable=SC1090
    source "$ENV_FILE"
fi

ROS_DISTRO="${ROS_DISTRO:-humble}"
ROS_SETUP="${ROS_SETUP:-/opt/ros/${ROS_DISTRO}/setup.bash}"
ROSBRIDGE_WS="${ROSBRIDGE_WS:-${PROJECT_ROOT}/src/rtk_tools/rosbridge_ts}"
ROSBRIDGE_SETUP="${ROSBRIDGE_SETUP:-${ROSBRIDGE_WS}/install/setup.bash}"
HOVERBOARD_WS="${HOVERBOARD_WS:-${PROJECT_ROOT}/hoverboard_ws}"
HOVERBOARD_SRC="${HOVERBOARD_SRC:-${PROJECT_ROOT}/hardware/hoverboard_driver}"
HOVERBOARD_SETUP="${HOVERBOARD_SETUP:-${HOVERBOARD_WS}/install/setup.bash}"
MEDIAMTX_VERSION="${MEDIAMTX_VERSION:-v1.9.0}"

SKIP_APT=0
SKIP_MEDIAMTX=0
SKIP_ROSDEP=0
SKIP_HOVERBOARD_BUILD=0
REBUILD_HOVERBOARD=0

usage() {
    cat <<'EOF'
Usage: ./scripts/deploy_dependencies.sh [options]

Install the new STM32/Hikrobot runtime dependencies and project workspaces.

Options:
  --profile NAME          Robot hardware profile, default: stm32_hoverboard_4wd
  --ros-distro NAME       ROS 2 distro name, default: humble
  --skip-apt              Do not run apt-get update/install
  --skip-mediamtx         Do not auto-install mediamtx if missing
  --skip-rosdep           Do not run rosdep
  --skip-hoverboard-build Do not build campusCar/hoverboard_ws
  --rebuild-hoverboard    Remove Hoverboard build/install/log and rebuild
  -h, --help              Show this help
EOF
}

log() { printf '[deploy] %s\n' "$*"; }
warn() { printf '[deploy][warn] %s\n' "$*" >&2; }
die() { printf '[deploy][error] %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --profile)
            [[ $# -ge 2 ]] || die "--profile requires a value"
            export ROBOT_PROFILE="$2"
            shift 2
            ;;
        --ros-distro)
            [[ $# -ge 2 ]] || die "--ros-distro requires a value"
            ROS_DISTRO="$2"
            ROS_SETUP="/opt/ros/${ROS_DISTRO}/setup.bash"
            shift 2
            ;;
        --skip-apt)
            SKIP_APT=1
            shift
            ;;
        --skip-mediamtx)
            SKIP_MEDIAMTX=1
            shift
            ;;
        --skip-rosdep)
            SKIP_ROSDEP=1
            shift
            ;;
        --skip-hoverboard-build)
            SKIP_HOVERBOARD_BUILD=1
            shift
            ;;
        --rebuild-hoverboard)
            REBUILD_HOVERBOARD=1
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            die "Unknown option: $1"
            ;;
    esac
done

APT_PACKAGES=(
    build-essential
    ca-certificates
    cmake
    curl
    ffmpeg
    git
    libdw-dev
    libeigen3-dev
    libgflags-dev
    libgl1
    libgoogle-glog-dev
    libopencv-dev
    libssl-dev
    libyaml-cpp-dev
    mesa-utils
    nlohmann-json3-dev
    pkg-config
    python3-argcomplete
    python3-colcon-common-extensions
    python3-numpy
    python3-opencv
    python3-pil
    python3-pil.imagetk
    python3-pip
    python3-pynput
    python3-rosdep
    python3-tk
    sshpass
    usbutils
    v4l-utils
    aravis-tools
    aravis-tools-cli
    "ros-${ROS_DISTRO}-ament-lint-auto"
    "ros-${ROS_DISTRO}-ament-lint-common"
    "ros-${ROS_DISTRO}-backward-ros"
    "ros-${ROS_DISTRO}-camera-aravis2"
    "ros-${ROS_DISTRO}-camera-calibration-parsers"
    "ros-${ROS_DISTRO}-camera-info-manager"
    "ros-${ROS_DISTRO}-control-toolbox"
    "ros-${ROS_DISTRO}-controller-manager"
    "ros-${ROS_DISTRO}-compressed-image-transport"
    "ros-${ROS_DISTRO}-cv-bridge"
    "ros-${ROS_DISTRO}-diagnostic-msgs"
    "ros-${ROS_DISTRO}-diagnostic-updater"
    "ros-${ROS_DISTRO}-diff-drive-controller"
    "ros-${ROS_DISTRO}-hardware-interface"
    "ros-${ROS_DISTRO}-image-publisher"
    "ros-${ROS_DISTRO}-image-transport"
    "ros-${ROS_DISTRO}-image-transport-plugins"
    "ros-${ROS_DISTRO}-joint-state-broadcaster"
    "ros-${ROS_DISTRO}-nmea-navsat-driver"
    "ros-${ROS_DISTRO}-rclcpp-components"
    "ros-${ROS_DISTRO}-realtime-tools"
    "ros-${ROS_DISTRO}-robot-state-publisher"
    "ros-${ROS_DISTRO}-ros2-control"
    "ros-${ROS_DISTRO}-ros2-controllers"
    "ros-${ROS_DISTRO}-ros2controlcli"
    "ros-${ROS_DISTRO}-rosbridge-suite"
    "ros-${ROS_DISTRO}-statistics-msgs"
    "ros-${ROS_DISTRO}-tf2-msgs"
    "ros-${ROS_DISTRO}-tf2-ros"
    "ros-${ROS_DISTRO}-tf2-sensor-msgs"
    "ros-${ROS_DISTRO}-xacro"
)

require_command() {
    command -v "$1" >/dev/null 2>&1 || die "Missing command: $1"
}

source_ros() {
    [[ -f "$ROS_SETUP" ]] || die "ROS setup not found: $ROS_SETUP. Install ROS 2 ${ROS_DISTRO} first."
    # ROS setup scripts may read unset variables.
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    set -u
}

install_apt_packages() {
    if [[ "$SKIP_APT" -ne 0 ]]; then
        return 0
    fi
    log "Installing apt packages for ROS, rosbridge, Hikrobot/Aravis camera, STM32 hoverboard chassis, Python, and runtime tools"
    sudo apt-get update
    sudo apt-get install -y "${APT_PACKAGES[@]}"
}

install_mediamtx_if_missing() {
    if [[ "$SKIP_MEDIAMTX" -ne 0 ]]; then
        return 0
    fi

    if command -v mediamtx >/dev/null 2>&1; then
        log "mediamtx already installed: $(command -v mediamtx)"
        return
    fi

    require_command curl
    local machine asset_arch url tmpdir downloaded
    local asset_arch_candidates=()
    machine="$(uname -m)"

    case "$machine" in
        x86_64|amd64)
            asset_arch_candidates=("amd64")
            ;;
        aarch64|arm64)
            asset_arch_candidates=("arm64" "arm64v8")
            ;;
        armv7l|armv7*)
            asset_arch_candidates=("armv7")
            ;;
        *)
            warn "Unsupported mediamtx architecture: ${machine}. Install mediamtx manually into PATH."
            return
            ;;
    esac

    tmpdir="$(mktemp -d)"
    downloaded=0
    for asset_arch in "${asset_arch_candidates[@]}"; do
        url="https://github.com/bluenviron/mediamtx/releases/download/${MEDIAMTX_VERSION}/mediamtx_${MEDIAMTX_VERSION}_linux_${asset_arch}.tar.gz"
        log "Trying mediamtx ${MEDIAMTX_VERSION}: ${url}"
        if curl -fL "$url" -o "${tmpdir}/mediamtx.tar.gz"; then
            downloaded=1
            break
        fi
    done

    [[ "$downloaded" -eq 1 ]] || die "Failed to download mediamtx ${MEDIAMTX_VERSION}"
    tar -xzf "${tmpdir}/mediamtx.tar.gz" -C "$tmpdir" mediamtx
    sudo install -m 0755 "${tmpdir}/mediamtx" /usr/local/bin/mediamtx
    rm -rf "$tmpdir"
}

run_rosdep() {
    if [[ "$SKIP_ROSDEP" -ne 0 ]]; then
        return 0
    fi
    require_command rosdep

    if [[ ! -f /etc/ros/rosdep/sources.list.d/20-default.list ]]; then
        log "Initializing rosdep"
        sudo rosdep init || warn "rosdep init returned non-zero; continuing"
    fi

    log "Updating rosdep database"
    rosdep update || warn "rosdep update failed; apt packages may still be enough"

    if [[ "${CHASSIS_DEPENDENCY_MODE:-none}" == "hoverboard_ros2_control" && -d "${HOVERBOARD_SRC}" ]]; then
        log "Installing rosdep dependencies for hoverboard_driver"
        rosdep install --from-paths "${HOVERBOARD_SRC}" --ignore-src -r -y --rosdistro "$ROS_DISTRO" \
            || warn "rosdep install reported unresolved dependencies"
    fi
}

build_hoverboard_workspace() {
    if [[ "$SKIP_HOVERBOARD_BUILD" -ne 0 ]]; then
        return 0
    fi
    if [[ ! -f "${HOVERBOARD_SRC}/package.xml" ]]; then
        die "hoverboard_driver source not found: ${HOVERBOARD_SRC}"
    fi

    source_ros
    require_command colcon

    if [[ "$REBUILD_HOVERBOARD" -eq 1 ]]; then
        log "Removing old Hoverboard build/install/log directories"
        rm -rf "${HOVERBOARD_WS}/build" "${HOVERBOARD_WS}/install" "${HOVERBOARD_WS}/log"
    elif [[ -f "$HOVERBOARD_SETUP" ]]; then
        log "Hoverboard workspace already built: $HOVERBOARD_SETUP"
        return
    fi

    mkdir -p "$HOVERBOARD_WS"
    log "Building hoverboard_driver from ${HOVERBOARD_SRC}"
    (
        cd "$HOVERBOARD_WS"
        colcon build \
            --base-paths "$HOVERBOARD_SRC" \
            --symlink-install \
            --cmake-args -DCMAKE_BUILD_TYPE=Release
    )
}

build_source_rosbridge_if_present() {
    if [[ ! -d "${ROSBRIDGE_WS}/src" ]]; then
        return
    fi

    source_ros
    require_command colcon

    if [[ -f "$ROSBRIDGE_SETUP" ]]; then
        log "Source rosbridge workspace already built: $ROSBRIDGE_SETUP"
        return
    fi

    log "Building source rosbridge workspace: ${ROSBRIDGE_WS}"
    (
        cd "$ROSBRIDGE_WS"
        colcon build --symlink-install
    )
}

verify_install() {
    source_ros

    if [[ -f "$ROSBRIDGE_SETUP" ]]; then
        set +u
        # shellcheck disable=SC1090
        source "$ROSBRIDGE_SETUP"
        set -u
    fi

    if [[ "${CHASSIS_DEPENDENCY_MODE:-none}" == "hoverboard_ros2_control" && -f "$HOVERBOARD_SETUP" ]]; then
        set +u
        # shellcheck disable=SC1090
        source "$HOVERBOARD_SETUP"
        set -u
    elif [[ "${CHASSIS_DEPENDENCY_MODE:-none}" == "hoverboard_ros2_control" ]]; then
        warn "Hoverboard setup file not found: $HOVERBOARD_SETUP"
    fi

    ros2 pkg prefix rosbridge_server >/dev/null 2>&1 \
        && log "rosbridge_server is available" \
        || warn "rosbridge_server is not available in the current ROS environment"

    if [[ "${CHASSIS_DEPENDENCY_MODE:-none}" == "hoverboard_ros2_control" ]]; then
        ros2 pkg prefix controller_manager >/dev/null 2>&1 \
            && log "controller_manager is available" \
            || warn "controller_manager is not available in the current ROS environment"
        ros2 pkg prefix diff_drive_controller >/dev/null 2>&1 \
            && log "diff_drive_controller is available" \
            || warn "diff_drive_controller is not available in the current ROS environment"
        ros2 pkg prefix hoverboard_driver >/dev/null 2>&1 \
            && log "hoverboard_driver is available" \
            || warn "hoverboard_driver is not available in the current ROS environment"
    fi

    if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "hikrobot_aravis" ]]; then
        ros2 pkg prefix camera_aravis2 >/dev/null 2>&1 \
            && log "camera_aravis2 is available" \
            || warn "camera_aravis2 is not available in the current ROS environment"
        command -v arv-tool-0.8 >/dev/null 2>&1 \
            && log "arv-tool-0.8 is available: $(command -v arv-tool-0.8)" \
            || warn "arv-tool-0.8 is not available; install aravis-tools-cli"
    else
        log "Camera dependency mode is ${CAMERA_DEPENDENCY_MODE:-none}; skipping camera package verification"
    fi

    if command -v mediamtx >/dev/null 2>&1; then
        log "mediamtx is available: $(command -v mediamtx)"
    else
        warn "mediamtx is not installed. launch_all.sh needs mediamtx in PATH for RTSP/HLS."
    fi
}

log "Project root: ${PROJECT_ROOT}"
log "Robot profile: ${ROBOT_PROFILE:-stm32_hoverboard_4wd}"
log "ROS distro: ${ROS_DISTRO}"
log "Chassis dependency mode: ${CHASSIS_DEPENDENCY_MODE:-none}"
log "Camera dependency mode: ${CAMERA_DEPENDENCY_MODE:-none}"
if [[ "${CHASSIS_DEPENDENCY_MODE:-none}" == "hoverboard_ros2_control" ]]; then
    log "Hoverboard source: ${HOVERBOARD_SRC}"
    log "Hoverboard workspace: ${HOVERBOARD_WS}"
fi

install_apt_packages
install_mediamtx_if_missing
run_rosdep
if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "hikrobot_aravis" ]]; then
    log "Hikrobot/Aravis camera uses apt packages; no source workspace build needed"
else
    log "Add custom camera dependency setup outside this script if needed"
fi
if [[ "${CHASSIS_DEPENDENCY_MODE:-none}" == "hoverboard_ros2_control" ]]; then
    build_hoverboard_workspace
fi
build_source_rosbridge_if_present
verify_install

log "Deployment dependency setup finished"
