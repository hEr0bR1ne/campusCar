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
ORBBEC_WS="${ORBBEC_WS:-${PROJECT_ROOT}/orbbec_ws}"
ORBBEC_SETUP="${ORBBEC_SETUP:-${ORBBEC_WS}/install/setup.bash}"
ROSBRIDGE_WS="${ROSBRIDGE_WS:-${PROJECT_ROOT}/src/rtk_tools/rosbridge_ts}"
ROSBRIDGE_SETUP="${ROSBRIDGE_SETUP:-${ROSBRIDGE_WS}/install/setup.bash}"
ORBBEC_REPO_URL="${ORBBEC_REPO_URL:-https://github.com/orbbec/OrbbecSDK_ROS2.git}"
ORBBEC_BRANCH="${ORBBEC_BRANCH:-v2-main}"
MEDIAMTX_VERSION="${MEDIAMTX_VERSION:-v1.9.0}"

SKIP_APT=0
SKIP_MEDIAMTX=0
SKIP_ROSDEP=0
SKIP_ORBBEC_BUILD=0
SKIP_UDEV=0
REBUILD_ORBBEC=0

usage() {
    cat <<'EOF'
Usage: ./scripts/deploy_dependencies.sh [options]

Install campusCar runtime dependencies, rosbridge, and profile camera support.

Options:
  --profile NAME          Robot hardware profile, default: campus_car
  --ros-distro NAME       ROS 2 distro name, default: humble
  --orbbec-repo URL       OrbbecSDK_ROS2 git URL if source is missing
  --orbbec-branch NAME    OrbbecSDK_ROS2 branch if source is missing
  --skip-apt              Do not run apt-get update/install
  --skip-mediamtx         Do not auto-install mediamtx if missing
  --skip-rosdep           Do not run rosdep
  --skip-orbbec-build     Do not build campusCar/orbbec_ws
  --skip-udev             Do not install Orbbec udev rules
  --rebuild-orbbec        Remove Orbbec build/install/log and rebuild
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
        --orbbec-repo)
            [[ $# -ge 2 ]] || die "--orbbec-repo requires a value"
            ORBBEC_REPO_URL="$2"
            shift 2
            ;;
        --orbbec-branch)
            [[ $# -ge 2 ]] || die "--orbbec-branch requires a value"
            ORBBEC_BRANCH="$2"
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
        --skip-orbbec-build)
            SKIP_ORBBEC_BUILD=1
            shift
            ;;
        --skip-udev)
            SKIP_UDEV=1
            shift
            ;;
        --rebuild-orbbec)
            REBUILD_ORBBEC=1
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
    "ros-${ROS_DISTRO}-ament-lint-auto"
    "ros-${ROS_DISTRO}-ament-lint-common"
    "ros-${ROS_DISTRO}-backward-ros"
    "ros-${ROS_DISTRO}-camera-calibration-parsers"
    "ros-${ROS_DISTRO}-camera-info-manager"
    "ros-${ROS_DISTRO}-compressed-image-transport"
    "ros-${ROS_DISTRO}-cv-bridge"
    "ros-${ROS_DISTRO}-diagnostic-msgs"
    "ros-${ROS_DISTRO}-diagnostic-updater"
    "ros-${ROS_DISTRO}-image-publisher"
    "ros-${ROS_DISTRO}-image-transport"
    "ros-${ROS_DISTRO}-image-transport-plugins"
    "ros-${ROS_DISTRO}-nmea-navsat-driver"
    "ros-${ROS_DISTRO}-rclcpp-components"
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
    log "Installing apt packages for ROS, rosbridge, Orbbec, Python, and runtime tools"
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

ensure_orbbec_source() {
    local orbbec_src="${ORBBEC_WS}/src/OrbbecSDK_ROS2"

    if [[ -d "${orbbec_src}/orbbec_camera" ]]; then
        log "Orbbec source found: ${orbbec_src}"
        return
    fi

    if [[ -e "$orbbec_src" ]]; then
        die "Orbbec source path exists but is incomplete: $orbbec_src"
    fi

    require_command git
    mkdir -p "${ORBBEC_WS}/src"
    log "Cloning OrbbecSDK_ROS2 ${ORBBEC_BRANCH} into ${orbbec_src}"
    git clone --branch "$ORBBEC_BRANCH" --depth 1 "$ORBBEC_REPO_URL" "$orbbec_src"
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

    if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "orbbec" && -d "${ORBBEC_WS}/src" ]]; then
        log "Installing rosdep dependencies for Orbbec workspace"
        rosdep install --from-paths "${ORBBEC_WS}/src" --ignore-src -r -y --rosdistro "$ROS_DISTRO" \
            || warn "rosdep install reported unresolved dependencies"
    fi
}

install_orbbec_udev() {
    if [[ "$SKIP_UDEV" -ne 0 ]]; then
        return 0
    fi
    local orbbec_src="${ORBBEC_WS}/src/OrbbecSDK_ROS2"
    local udev_script="${orbbec_src}/orbbec_camera/scripts/install_udev_rules.sh"
    local udev_rules="${orbbec_src}/orbbec_camera/scripts/99-obsensor-libusb.rules"

    if [[ -f "$udev_script" ]]; then
        log "Installing Orbbec udev rules with upstream script"
        sudo bash "$udev_script"
    elif [[ -f "$udev_rules" ]]; then
        log "Installing Orbbec udev rules"
        sudo install -m 0644 "$udev_rules" /etc/udev/rules.d/99-obsensor-libusb.rules
    else
        warn "Orbbec udev rules not found; camera permissions may fail"
        return
    fi

    sudo udevadm control --reload-rules
    sudo udevadm trigger
}

build_orbbec_workspace() {
    if [[ "$SKIP_ORBBEC_BUILD" -ne 0 ]]; then
        return 0
    fi
    ensure_orbbec_source
    source_ros
    require_command colcon

    local stale_prefix=0
    if [[ -d "${ORBBEC_WS}/install" ]]; then
        if grep -R -h -I "/orbbec_ws/install" "${ORBBEC_WS}/install" 2>/dev/null | grep -Fv "${ORBBEC_WS}/install" >/dev/null; then
            stale_prefix=1
        fi
    fi

    if [[ "$REBUILD_ORBBEC" -eq 1 ]]; then
        log "Removing old Orbbec build/install/log directories"
        rm -rf "${ORBBEC_WS}/build" "${ORBBEC_WS}/install" "${ORBBEC_WS}/log"
    elif [[ "$stale_prefix" -eq 1 ]]; then
        log "Orbbec install prefix points to another path; rebuilding"
        rm -rf "${ORBBEC_WS}/build" "${ORBBEC_WS}/install" "${ORBBEC_WS}/log"
    elif [[ -f "$ORBBEC_SETUP" ]]; then
        log "Orbbec workspace already built: $ORBBEC_SETUP"
        return
    fi

    log "Building Orbbec workspace: ${ORBBEC_WS}"
    (
        cd "$ORBBEC_WS"
        colcon build --event-handlers console_direct+ --cmake-args -DCMAKE_BUILD_TYPE=Release
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

    if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "orbbec" && -f "$ORBBEC_SETUP" ]]; then
        set +u
        # shellcheck disable=SC1090
        source "$ORBBEC_SETUP"
        set -u
    elif [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "orbbec" ]]; then
        warn "Orbbec setup file not found: $ORBBEC_SETUP"
    fi

    if [[ -f "$ROSBRIDGE_SETUP" ]]; then
        set +u
        # shellcheck disable=SC1090
        source "$ROSBRIDGE_SETUP"
        set -u
    fi

    ros2 pkg prefix rosbridge_server >/dev/null 2>&1 \
        && log "rosbridge_server is available" \
        || warn "rosbridge_server is not available in the current ROS environment"

    if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "orbbec" ]]; then
        ros2 pkg prefix orbbec_camera >/dev/null 2>&1 \
            && log "orbbec_camera is available" \
            || warn "orbbec_camera is not available in the current ROS environment"
    else
        log "Camera dependency mode is ${CAMERA_DEPENDENCY_MODE:-none}; skipping Orbbec verification"
    fi

    if command -v mediamtx >/dev/null 2>&1; then
        log "mediamtx is available: $(command -v mediamtx)"
    else
        warn "mediamtx is not installed. launch_all.sh needs mediamtx in PATH for RTSP/HLS."
    fi
}

log "Project root: ${PROJECT_ROOT}"
log "Robot profile: ${ROBOT_PROFILE:-campus_car}"
log "ROS distro: ${ROS_DISTRO}"
log "Camera dependency mode: ${CAMERA_DEPENDENCY_MODE:-none}"
if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "orbbec" ]]; then
    log "Orbbec workspace: ${ORBBEC_WS}"
fi

install_apt_packages
install_mediamtx_if_missing
if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "orbbec" ]]; then
    ensure_orbbec_source
else
    log "Skipping Orbbec source setup for camera dependency mode: ${CAMERA_DEPENDENCY_MODE:-none}"
fi
run_rosdep
if [[ "${CAMERA_DEPENDENCY_MODE:-none}" == "orbbec" ]]; then
    install_orbbec_udev
    build_orbbec_workspace
else
    log "Add custom camera dependency setup outside this script or set CAMERA_DEPENDENCY_MODE=orbbec"
fi
build_source_rosbridge_if_present
verify_install

log "Deployment dependency setup finished"
