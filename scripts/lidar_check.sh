#!/usr/bin/env bash
# ============================================================
# lidar_check.sh - 激光雷达避障栈状态检查脚本
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# 加载 lidar profile
if [ -f "${PROJECT_ROOT}/config/profiles/old-orange-pi-orbbec-lidar.env" ]; then
    # shellcheck disable=SC1090
    source "${PROJECT_ROOT}/config/profiles/old-orange-pi-orbbec-lidar.env" 2>/dev/null || true
fi

# 加载 ROS2 环境
if command -v ros2 >/dev/null 2>&1; then
    :
elif [ -f /opt/ros/humble/setup.bash ]; then
    source /opt/ros/humble/setup.bash
fi

ok()   { echo "  [OK]   $*"; }
warn() { echo "  [WARN] $*"; }
err()  { echo "  [ERR]  $*"; }
info() { echo "  [INFO] $*"; }

echo "========================================"
echo "  激光雷达避障栈状态检查"
echo "========================================"

# ---- 1. Docker 容器状态 ----
echo ""
echo "[ Docker 容器 ]"
if docker ps --format '{{.Names}}\t{{.Status}}' 2>/dev/null | grep -q "^campuscar_lidar"; then
    STATUS=$(docker ps --format '{{.Status}}' --filter name=campuscar_lidar)
    ok "campuscar_lidar 容器运行中 ($STATUS)"
elif docker ps -a --format '{{.Names}}\t{{.Status}}' 2>/dev/null | grep -q "^campuscar_lidar"; then
    STATUS=$(docker ps -a --format '{{.Status}}' --filter name=campuscar_lidar)
    err "campuscar_lidar 容器已停止 ($STATUS)"
else
    err "campuscar_lidar 容器不存在（未启动）"
fi

# ---- 2. 避障仲裁节点状态 ----
echo ""
echo "[ 避障仲裁节点 ]"
if pgrep -f "obstacle_stopper.py" > /dev/null; then
    PID=$(pgrep -f "obstacle_stopper.py")
    ok "obstacle_stopper.py 运行中 (PID=$PID)"
else
    err "obstacle_stopper.py 未运行"
fi

# ---- 3. ROS2 话题检查 ----
echo ""
echo "[ ROS2 话题 ]"
if command -v ros2 >/dev/null 2>&1; then
    TOPICS=$(ros2 topic list 2>/dev/null)

    if echo "$TOPICS" | grep -q "^/livox/lidar$"; then
        FREQ=$(ros2 topic hz /livox/lidar --window 5 2>/dev/null | grep "average rate" | awk '{print $3}' || echo "?")
        ok "/livox/lidar 存在 (${FREQ} Hz)"
    else
        err "/livox/lidar 不存在（Livox 驱动未启动？）"
    fi

    if echo "$TOPICS" | grep -q "^/scan$"; then
        FREQ=$(ros2 topic hz /scan --window 5 2>/dev/null | grep "average rate" | awk '{print $3}' || echo "?")
        ok "/scan 存在 (${FREQ} Hz)"
    else
        err "/scan 不存在（pointcloud_to_laserscan 未启动？）"
    fi

    CMD_VEL_IN="${CMD_VEL_TOPIC:-/cmd_vel_input}"
    if echo "$TOPICS" | grep -q "^${CMD_VEL_IN}$"; then
        ok "${CMD_VEL_IN} 存在（控制节点正在发布）"
    else
        warn "${CMD_VEL_IN} 不存在（控制节点未发布，或 CMD_VEL_TOPIC 未覆盖）"
    fi

    if echo "$TOPICS" | grep -q "^/cmd_vel$"; then
        ok "/cmd_vel 存在（避障节点正在发布）"
    else
        warn "/cmd_vel 不存在（避障节点未发布，或底盘未连接）"
    fi
else
    warn "ROS2 未安装或未 source，跳过话题检查"
fi

# ---- 4. Mid360 网络连通性 ----
echo ""
echo "[ Mid360 网络 ]"
LIVOX_IP="${LIVOX_LIDAR_IP:-192.168.1.177}"
if ping -c 1 -W 1 "$LIVOX_IP" >/dev/null 2>&1; then
    ok "Mid360 ($LIVOX_IP) 网络可达"
else
    warn "Mid360 ($LIVOX_IP) 网络不可达（设备未连接或 IP 不对？）"
fi

# ---- 5. 日志最后几行 ----
echo ""
echo "[ 最近日志 ]"
LOGDIR="${PROJECT_ROOT}/data/logs"
if [ -f "$LOGDIR/obstacle_stopper.log" ]; then
    info "obstacle_stopper.log 最后 5 行："
    tail -5 "$LOGDIR/obstacle_stopper.log" | sed 's/^/    /'
else
    info "obstacle_stopper.log 不存在"
fi

echo ""
echo "========================================"
echo "  完整日志："
echo "    $LOGDIR/obstacle_stopper.log"
echo "    $LOGDIR/lidar_docker.log"
echo "  Docker 容器日志："
echo "    docker logs campuscar_lidar"
echo "========================================"
