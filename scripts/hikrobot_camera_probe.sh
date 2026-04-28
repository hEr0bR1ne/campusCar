#!/usr/bin/env bash
# ============================================================
# 海康 GigE 工业相机到货后的最小探测脚本
# 适用于 MV-CS016-10GC 等 GigE Vision / GenICam 相机
# ============================================================

set -u

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
source "${PROJECT_ROOT}/config/robot.env"

if [ -f "$ROS_SETUP" ]; then
    set +u
    # shellcheck disable=SC1090
    source "$ROS_SETUP"
    set -u
fi

echo "========================================"
echo "  Hikrobot GigE camera probe"
echo "========================================"
echo "ROBOT_PROFILE=${ROBOT_PROFILE:-stm32_hoverboard_4wd}"
echo "CAMERA_ADAPTER=${CAMERA_ADAPTER:-none}"
echo "CAMERA_START_MODE=${CAMERA_START_MODE:-skip}"
echo "HIKROBOT_CAMERA_GUID=${HIKROBOT_CAMERA_GUID:-<auto>}"
echo ""

echo "【依赖】"
if ros2 pkg prefix camera_aravis2 >/dev/null 2>&1; then
    echo "✅ camera_aravis2: $(ros2 pkg prefix camera_aravis2)"
else
    echo "❌ camera_aravis2 未安装"
    echo "   sudo apt install ros-${ROS_DISTRO}-camera-aravis2 aravis-tools aravis-tools-cli"
fi

if command -v arv-tool-0.8 >/dev/null 2>&1; then
    echo "✅ arv-tool-0.8: $(command -v arv-tool-0.8)"
else
    echo "❌ arv-tool-0.8 未安装"
fi

echo ""
echo "【Aravis 设备枚举】"
if command -v arv-tool-0.8 >/dev/null 2>&1; then
    arv-tool-0.8 || true
else
    echo "跳过：缺少 arv-tool-0.8"
fi

echo ""
echo "【ROS2 camera_finder】"
if ros2 pkg prefix camera_aravis2 >/dev/null 2>&1; then
    timeout 8s ros2 run camera_aravis2 camera_finder || true
else
    echo "跳过：缺少 camera_aravis2"
fi

echo ""
echo "下一步：如果上面能看到相机 GUID 或 IP，可运行："
echo "HIKROBOT_CAMERA_GUID=<GUID或IP> ./scripts/launch_all.sh"
