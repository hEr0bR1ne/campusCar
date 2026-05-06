#!/usr/bin/env bash
# ============================================================
# lidar_start.sh - 激光雷达避障栈独立启动脚本
#
# 功能：
#   1. 构建 Docker 镜像（如不存在）
#   2. 启动 campuscar_lidar 容器（Livox 驱动 + 点云转换）
#   3. 等待 /scan 话题出现
#   4. 启动宿主机避障仲裁节点 obstacle_stopper.py
#
# 前提：
#   - 全栈已通过 launch_all.sh 启动
#   - 使用 lidar profile（CAR_PROFILE=old-orange-pi-orbbec-lidar）
#     或手动确保 CMD_VEL_TOPIC=/cmd_vel_input
#
# 用法：
#   ./scripts/lidar_start.sh
#   OBSTACLE_ENABLED=0 ./scripts/lidar_start.sh   # 透传模式（调试用）
#   LIVOX_NET_IFACE=eth1 ./scripts/lidar_start.sh  # 指定网卡
# ============================================================

set -e
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOCKER_DIR="${PROJECT_ROOT}/docker/lidar"
SRC_DIR="${PROJECT_ROOT}/src"
LOGDIR="${PROJECT_ROOT}/data/logs"

# 加载 lidar profile（获取 LIVOX_* 和 OBSTACLE_* 参数）
if [ -f "${PROJECT_ROOT}/config/profiles/old-orange-pi-orbbec-lidar.env" ]; then
    # shellcheck disable=SC1090
    source "${PROJECT_ROOT}/config/profiles/old-orange-pi-orbbec-lidar.env"
fi

# 命令行参数覆盖
for arg in "$@"; do
    export "$arg"
done

mkdir -p "$LOGDIR"

log()  { echo "[$(date +'%H:%M:%S')] $*"; }
ok()   { echo "[$(date +'%H:%M:%S')] OK  $*"; }
warn() { echo "[$(date +'%H:%M:%S')] WARN $*"; }
err()  { echo "[$(date +'%H:%M:%S')] ERR  $*"; exit 1; }

echo "========================================"
echo "  campusCar 激光雷达避障栈启动"
echo "========================================"
log "项目根目录: $PROJECT_ROOT"
log "避障状态: ${OBSTACLE_ENABLED:-1}（1=启用 0=禁用/透传）"
log "刹停距离: ${OBSTACLE_STOP_DIST:-0.5}m  减速距离: ${OBSTACLE_WARN_DIST:-3.0}m"

# ---- 1. 检查 Docker ----
if ! command -v docker >/dev/null 2>&1; then
    err "Docker 未安装，请先安装 Docker"
fi

# ---- 2. 检查 ROS2 环境 ----
if ! command -v ros2 >/dev/null 2>&1; then
    if [ -f /opt/ros/humble/setup.bash ]; then
        source /opt/ros/humble/setup.bash
    else
        err "ROS2 Humble 未安装"
    fi
fi

# ---- 3. 停止旧容器（如果存在）----
if docker ps -a --format '{{.Names}}' | grep -q "^campuscar_lidar$"; then
    log "停止旧的 campuscar_lidar 容器..."
    docker rm -f campuscar_lidar >/dev/null 2>&1 || true
fi

# ---- 4. 构建镜像（如果不存在）----
if ! docker image inspect campuscar-lidar:latest >/dev/null 2>&1; then
    log "首次运行，构建激光雷达 Docker 镜像（需要几分钟，请耐心等待）..."
    log "构建日志: $LOGDIR/lidar_docker_build.log"
    docker build -t campuscar-lidar:latest "$DOCKER_DIR" \
        > "$LOGDIR/lidar_docker_build.log" 2>&1
    if [ $? -ne 0 ]; then
        err "镜像构建失败，请检查 $LOGDIR/lidar_docker_build.log"
    fi
    ok "镜像构建完成"
else
    ok "镜像 campuscar-lidar:latest 已存在，跳过构建"
fi

# ---- 5. 启动 Docker 容器 ----
log "启动激光雷达 Docker 容器..."
log "  Mid360 IP: ${LIVOX_LIDAR_IP:-192.168.1.177}"
log "  宿主机 IP: ${LIVOX_HOST_IP:-192.168.1.2}"
log "  网卡: ${LIVOX_NET_IFACE:-（未指定，需宿主机预先配置）}"

docker run -d \
    --name campuscar_lidar \
    --network host \
    --cap-add NET_ADMIN \
    -e ROS_DOMAIN_ID="${ROS_DOMAIN_ID:-0}" \
    -e ROS_LOCALHOST_ONLY=0 \
    -e LIVOX_HOST_IP="${LIVOX_HOST_IP:-192.168.1.2}" \
    -e LIVOX_HOST_NETMASK="${LIVOX_HOST_NETMASK:-24}" \
    -e LIVOX_NET_IFACE="${LIVOX_NET_IFACE:-}" \
    -e LIVOX_PUBLISH_FREQ="${LIVOX_PUBLISH_FREQ:-10.0}" \
    -e SCAN_MIN_HEIGHT="${SCAN_MIN_HEIGHT:--0.3}" \
    -e SCAN_MAX_HEIGHT="${SCAN_MAX_HEIGHT:-0.3}" \
    -e SCAN_RANGE_MIN="${SCAN_RANGE_MIN:-0.1}" \
    -e SCAN_RANGE_MAX="${SCAN_RANGE_MAX:-50.0}" \
    -e LIDAR_X="${LIDAR_X:-0.0}" \
    -e LIDAR_Y="${LIDAR_Y:-0.0}" \
    -e LIDAR_Z="${LIDAR_Z:-0.2}" \
    -e LIDAR_ROLL="${LIDAR_ROLL:-0.0}" \
    -e LIDAR_PITCH="${LIDAR_PITCH:-0.0}" \
    -e LIDAR_YAW="${LIDAR_YAW:-0.0}" \
    -v "${DOCKER_DIR}/config:/campuscar_lidar/config:ro" \
    campuscar-lidar:latest \
    >> "$LOGDIR/lidar_docker.log" 2>&1

sleep 2
if ! docker ps --format '{{.Names}}' | grep -q "^campuscar_lidar$"; then
    err "容器启动失败，请检查 $LOGDIR/lidar_docker.log\n$(docker logs campuscar_lidar 2>&1 | tail -20)"
fi
ok "激光雷达容器已启动（campuscar_lidar）"

# ---- 6. 等待 /scan 话题出现 ----
log "等待 /scan 话题（最多 20s）..."
for i in $(seq 1 20); do
    if ros2 topic list 2>/dev/null | grep -q "^/scan$"; then
        ok "/scan 话题已出现（${i}s）"
        break
    fi
    sleep 1
    if [ "$i" = "20" ]; then
        warn "/scan 话题未出现，继续启动避障节点（Mid360 可能还在初始化，约需 5-10s）"
    fi
done

# ---- 7. 停止旧的避障节点（如果存在）----
if pgrep -f "obstacle_stopper.py" > /dev/null; then
    log "停止旧的 obstacle_stopper 进程..."
    pkill -f "obstacle_stopper.py" 2>/dev/null || true
    sleep 1
fi

# ---- 8. 启动宿主机避障仲裁节点 ----
log "启动避障仲裁节点 (obstacle_stopper.py)..."
log "  输入话题: ${CMD_VEL_TOPIC:-/cmd_vel_input} + /scan"
log "  输出话题: /cmd_vel"

nohup env \
    PYTHONUNBUFFERED=1 \
    CMD_VEL_INPUT_TOPIC="${CMD_VEL_TOPIC:-/cmd_vel_input}" \
    CMD_VEL_OUTPUT_TOPIC="/cmd_vel" \
    SCAN_TOPIC="/scan" \
    OBSTACLE_STOP_DIST="${OBSTACLE_STOP_DIST:-0.5}" \
    OBSTACLE_WARN_DIST="${OBSTACLE_WARN_DIST:-3.0}" \
    OBSTACLE_FRONT_ANGLE_DEG="${OBSTACLE_FRONT_ANGLE_DEG:-30}" \
    OBSTACLE_ENABLED="${OBSTACLE_ENABLED:-1}" \
    OBSTACLE_SCAN_TIMEOUT="${OBSTACLE_SCAN_TIMEOUT:-2.0}" \
    OBSTACLE_PUBLISH_RATE_HZ="${OBSTACLE_PUBLISH_RATE_HZ:-20.0}" \
    python3 "${SRC_DIR}/obstacle_stopper.py" \
    >> "$LOGDIR/obstacle_stopper.log" 2>&1 &

sleep 2
if pgrep -f "obstacle_stopper.py" > /dev/null; then
    ok "避障仲裁节点已启动"
    ok "日志: $LOGDIR/obstacle_stopper.log"
else
    err "避障仲裁节点启动失败，请检查 $LOGDIR/obstacle_stopper.log"
fi

echo ""
echo "========================================"
echo "  激光雷达避障栈启动完成"
echo ""
echo "  话题流："
echo "    ${CMD_VEL_TOPIC:-/cmd_vel_input} (控制节点)"
echo "    /scan (Docker 容器 Livox 驱动)"
echo "         ↓"
echo "    obstacle_stopper.py (宿主机仲裁)"
echo "         ↓"
echo "    /cmd_vel (底盘)"
echo ""
echo "  日志："
echo "    $LOGDIR/obstacle_stopper.log"
echo "    $LOGDIR/lidar_docker.log"
echo ""
echo "  检查状态: ./scripts/lidar_check.sh"
echo "  停止:     ./scripts/lidar_stop.sh"
echo "========================================"
