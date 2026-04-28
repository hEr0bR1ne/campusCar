#!/usr/bin/env bash
# ============================================================
# Probe STM32 dual-UART 4WD chassis integration
# ============================================================

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

usage() {
    cat <<'EOF'
Usage: ./scripts/stm32_hoverboard_probe.sh [--profile NAME]

Check dependencies and serial device visibility for the STM32 hoverboard-style
4WD chassis.
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

"${PROJECT_ROOT}/scripts/bind_ch341_serial.sh" || true

if [ -f "$ROS_SETUP" ]; then
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    set -u
fi
if [ -f "$HOVERBOARD_SETUP" ]; then
    set +u
    # shellcheck disable=SC1090
    source "$HOVERBOARD_SETUP"
    set -u
fi

echo "========================================"
echo "  STM32 hoverboard chassis probe"
echo "========================================"
echo "ROBOT_PROFILE=${ROBOT_PROFILE:-stm32_hoverboard_4wd}"
echo "CHASSIS_ADAPTER=${CHASSIS_ADAPTER:-none}"
echo "HOVERBOARD_FRONT_DEVICE=${HOVERBOARD_FRONT_DEVICE:-}"
echo "HOVERBOARD_REAR_DEVICE=${HOVERBOARD_REAR_DEVICE:-}"
echo "HOVERBOARD_FEEDBACK_FORMAT=${HOVERBOARD_FEEDBACK_FORMAT:-compact}"
echo "HOVERBOARD_COMMAND_LIMIT_RPM=${HOVERBOARD_COMMAND_LIMIT_RPM:-50}"
echo ""

echo "【ROS2 依赖】"
for pkg in controller_manager diff_drive_controller joint_state_broadcaster robot_state_publisher hoverboard_driver; do
    if ros2 pkg prefix "$pkg" >/dev/null 2>&1; then
        echo "✅ $pkg: $(ros2 pkg prefix "$pkg")"
    else
        echo "❌ $pkg 未找到"
    fi
done

echo ""
echo "【串口设备】"
for label_dev in "front:$HOVERBOARD_FRONT_DEVICE" "rear:$HOVERBOARD_REAR_DEVICE"; do
    label="${label_dev%%:*}"
    dev="${label_dev#*:}"
    if [ -e "$dev" ]; then
        perms="$(ls -l "$dev" 2>/dev/null || true)"
        echo "✅ ${label}: ${dev}"
        [ -n "$perms" ] && echo "   $perms"
        if [ ! -r "$dev" ] || [ ! -w "$dev" ]; then
            echo "   ⚠️  当前用户可能没有该串口读写权限，请检查 dialout 组或 udev 规则"
        fi
        if command -v udevadm >/dev/null 2>&1; then
            id_path="$(udevadm info -q property -n "$dev" 2>/dev/null | grep -E '^(ID_SERIAL=|ID_PATH=)' || true)"
            [ -n "$id_path" ] && printf '%s\n' "$id_path" | sed 's/^/   /'
        fi
    else
        echo "❌ ${label}: ${dev} 不存在"
    fi
done
front_real="$(readlink -f "$HOVERBOARD_FRONT_DEVICE" 2>/dev/null || printf '%s' "$HOVERBOARD_FRONT_DEVICE")"
rear_real="$(readlink -f "$HOVERBOARD_REAR_DEVICE" 2>/dev/null || printf '%s' "$HOVERBOARD_REAR_DEVICE")"
if [ -n "$front_real" ] && [ "$front_real" = "$rear_real" ]; then
    echo "❌ front/rear 指向同一个串口设备：$front_real"
fi

echo ""
echo "【建议】"
echo "1. 首次上车前先架空轮子或断开电机负载。"
echo "2. 优先把串口改成 /dev/serial/by-path/... 写入 config/profiles/stm32_hoverboard_4wd.local.env；若转接器有唯一序列号，也可使用 /dev/serial/by-id/...。"
echo "3. 卖家协议 steer/speed 范围是 [-1000,1000] RPM；当前工程默认把串口命令限制在 ${HOVERBOARD_COMMAND_LIMIT_RPM:-50} RPM。"
echo "4. 低速测试命令："
echo "   ros2 topic pub -1 /cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.03}, angular: {z: 0.0}}'"
echo "5. 停车命令："
echo "   ros2 topic pub -1 /cmd_vel geometry_msgs/msg/Twist '{linear: {x: 0.0}, angular: {z: 0.0}}'"
