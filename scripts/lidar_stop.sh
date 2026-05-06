#!/usr/bin/env bash
# ============================================================
# lidar_stop.sh - 激光雷达避障栈停止脚本
# ============================================================

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log()  { echo "[$(date +'%H:%M:%S')] $*"; }
ok()   { echo "[$(date +'%H:%M:%S')] OK  $*"; }

echo "========================================"
echo "  停止激光雷达避障栈"
echo "========================================"

# ---- 1. 停止避障仲裁节点 ----
if pgrep -f "obstacle_stopper.py" > /dev/null; then
    log "停止 obstacle_stopper.py..."
    pkill -f "obstacle_stopper.py" 2>/dev/null || true
    sleep 1
    ok "obstacle_stopper.py 已停止"
else
    log "obstacle_stopper.py 未运行"
fi

# ---- 2. 停止 Docker 容器 ----
if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^campuscar_lidar$"; then
    log "停止 campuscar_lidar 容器..."
    docker stop campuscar_lidar >/dev/null 2>&1 || true
    docker rm campuscar_lidar >/dev/null 2>&1 || true
    ok "campuscar_lidar 容器已停止"
elif docker ps -a --format '{{.Names}}' 2>/dev/null | grep -q "^campuscar_lidar$"; then
    log "移除已停止的 campuscar_lidar 容器..."
    docker rm campuscar_lidar >/dev/null 2>&1 || true
    ok "campuscar_lidar 容器已移除"
else
    log "campuscar_lidar 容器未运行"
fi

echo ""
echo "  激光雷达避障栈已停止"
echo "  注意：底盘控制已恢复为直接接收 /cmd_vel（如果全栈仍在运行）"
echo "========================================"
