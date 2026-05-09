#!/usr/bin/env bash
# ============================================================
# campusCar 激光雷达容器启动脚本
# 功能：
#   1. 配置 Mid360 所在网卡的静态 IP
#   2. 启动 livox_ros_driver2（发布 /livox/lidar）
#   3. 启动 pointcloud_to_laserscan（发布 /scan）
#   4. 发布激光雷达到 base_link 的静态 TF
# ============================================================
set -e

source /opt/ros/humble/setup.bash
[ -f /livox_ws/setup.bash ] && source /livox_ws/setup.bash

# ---- 配置参数（从环境变量读取，与 robot.env 风格一致）----
LIVOX_HOST_IP="${LIVOX_HOST_IP:-192.168.1.2}"
LIVOX_HOST_NETMASK="${LIVOX_HOST_NETMASK:-24}"
LIVOX_NET_IFACE="${LIVOX_NET_IFACE:-}"          # 留空则自动探测
LIVOX_PUBLISH_FREQ="${LIVOX_PUBLISH_FREQ:-10.0}"
SCAN_MIN_HEIGHT="${SCAN_MIN_HEIGHT:--0.3}"
SCAN_MAX_HEIGHT="${SCAN_MAX_HEIGHT:-0.3}"
SCAN_RANGE_MIN="${SCAN_RANGE_MIN:-0.1}"
SCAN_RANGE_MAX="${SCAN_RANGE_MAX:-50.0}"
# Mid360 安装位置相对于 base_link 的偏移（单位：米/弧度）
LIDAR_X="${LIDAR_X:-0.0}"
LIDAR_Y="${LIDAR_Y:-0.0}"
LIDAR_Z="${LIDAR_Z:-0.2}"
LIDAR_ROLL="${LIDAR_ROLL:-0.0}"
LIDAR_PITCH="${LIDAR_PITCH:-0.0}"
LIDAR_YAW="${LIDAR_YAW:-0.0}"

log()  { echo "[$(date +'%H:%M:%S')] [lidar-entrypoint] $*"; }
warn() { echo "[$(date +'%H:%M:%S')] [lidar-entrypoint] WARN $*"; }

log "===== campusCar 激光雷达容器启动 ====="
log "ROS_DOMAIN_ID=${ROS_DOMAIN_ID:-0}"
log "LIVOX_HOST_IP=$LIVOX_HOST_IP"
log "LIVOX_PUBLISH_FREQ=$LIVOX_PUBLISH_FREQ Hz"
log "扫描高度范围: [$SCAN_MIN_HEIGHT, $SCAN_MAX_HEIGHT] m"

# ---- 1. 配置网卡 IP（让容器能与 Mid360 通信）----
if [ -n "$LIVOX_NET_IFACE" ]; then
    log "配置网卡 $LIVOX_NET_IFACE IP: $LIVOX_HOST_IP/$LIVOX_HOST_NETMASK"
    ip addr add "${LIVOX_HOST_IP}/${LIVOX_HOST_NETMASK}" dev "$LIVOX_NET_IFACE" 2>/dev/null || \
        warn "IP 已存在或配置失败（可能已由宿主机配置）"
    ip link set "$LIVOX_NET_IFACE" up 2>/dev/null || true
else
    log "LIVOX_NET_IFACE 未设置，跳过网卡 IP 配置（假设宿主机已配置）"
fi

# ---- 2. 发布激光雷达到 base_link 的静态 TF ----
log "发布静态 TF: base_link -> livox_frame (x=$LIDAR_X y=$LIDAR_Y z=$LIDAR_Z)"
ros2 run tf2_ros static_transform_publisher \
    --x "$LIDAR_X" --y "$LIDAR_Y" --z "$LIDAR_Z" \
    --roll "$LIDAR_ROLL" --pitch "$LIDAR_PITCH" --yaw "$LIDAR_YAW" \
    --frame-id base_link --child-frame-id livox_frame &
TF_PID=$!

# ---- 3. 启动 livox_ros_driver2 ----
# msg_MID360_launch.py 硬编码了配置路径，命令行参数无效，直接覆盖默认配置文件
LIVOX_DEFAULT_CFG="/livox_ws/livox_ros_driver2/share/livox_ros_driver2/config/MID360_config.json"
if [ -f "$LIVOX_DEFAULT_CFG" ]; then
    cp /campuscar_lidar/config/mid360.json "$LIVOX_DEFAULT_CFG"
    log "已将 mid360.json 覆盖到 $LIVOX_DEFAULT_CFG"
fi
log "启动 livox_ros_driver2..."
ros2 launch livox_ros_driver2 msg_MID360_launch.py \
    xfer_format:=1 \
    publish_freq:="$LIVOX_PUBLISH_FREQ" &
LIVOX_PID=$!

# 等待驱动初始化
sleep 3
log "等待 /livox/lidar 话题..."
for i in $(seq 1 15); do
    if ros2 topic list 2>/dev/null | grep -q "/livox/lidar"; then
        log "/livox/lidar 话题已出现"
        break
    fi
    sleep 1
    if [ "$i" = "15" ]; then
        warn "/livox/lidar 话题未出现，继续启动转换节点（Mid360 可能还在初始化）"
    fi
done

# ---- 4. 启动 pointcloud_to_laserscan ----
log "启动 pointcloud_to_laserscan..."
ros2 run pointcloud_to_laserscan pointcloud_to_laserscan_node \
    --ros-args \
    -r cloud_in:=/livox/lidar \
    -r scan:=/scan \
    -p target_frame:=livox_frame \
    -p min_height:="$SCAN_MIN_HEIGHT" \
    -p max_height:="$SCAN_MAX_HEIGHT" \
    -p range_min:="$SCAN_RANGE_MIN" \
    -p range_max:="$SCAN_RANGE_MAX" \
    -p angle_min:=-3.14159 \
    -p angle_max:=3.14159 \
    -p use_inf:=true &
PC2SCAN_PID=$!

log "===== 所有节点已启动 ====="
log "  /livox/lidar  (PointCloud2, ${LIVOX_PUBLISH_FREQ}Hz)"
log "  /scan         (LaserScan, 转换自点云)"
log "  TF: base_link -> livox_frame"

# 等待任意子进程退出
wait -n $TF_PID $LIVOX_PID $PC2SCAN_PID 2>/dev/null || true
log "某个子进程已退出，容器即将停止"
kill $TF_PID $LIVOX_PID $PC2SCAN_PID 2>/dev/null || true
wait
