#!/usr/bin/env python3
"""
GPS 航点导航节点 - 阿克曼底盘闭环控制 (Stanley Controller)

用法:
  python3 gps_navigator.py --waypoints ../../data/recorded_paths/path_xxx.json
  python3 gps_navigator.py --waypoints path.json --loop       # 循环执行
  python3 gps_navigator.py --waypoints path.json --speed 0.4  # 自定义速度
  python3 gps_navigator.py --waypoints path.json --reverse    # 反向行驶

控制器: Stanley Controller
  δ = ψ_e + arctan(k * e / max(v, v_min))
  - ψ_e : 航向误差 (车头朝向 vs 路径方向)
  - e   : 横向偏差 (前轴到路径的有符号垂直距离)
  - k   : 横向增益
  - v   : 当前速度

反馈来源:
  - /fix  (NavSatFix) → 位置 + GPS航向
  - /imu  (Imu)       → 航向辅助 (可选)
"""

import sys
import math
import json
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import NavSatFix, Imu
from geometry_msgs.msg import Twist
from std_msgs.msg import String

from config import TOPIC_FIX_IN, ROOT_DIR
from core.gnss import GNSSValidator

# ---------------------------------------------------------------------------
# 坐标转换
# ---------------------------------------------------------------------------

def gps_to_enu(lat, lon, alt, lat0, lon0, alt0):
    """GPS 经纬度 → ENU 局部坐标 (米)，以 (lat0,lon0,alt0) 为原点"""
    R = 6378137.0
    d_lat = math.radians(lat - lat0)
    d_lon = math.radians(lon - lon0)
    lat_r = math.radians(lat0)
    east  = R * d_lon * math.cos(lat_r)
    north = R * d_lat
    up    = alt - alt0
    return east, north, up


def quat_to_yaw(x, y, z, w):
    """四元数 → 偏航角 (rad)，ENU 坐标系，东方向为 0，逆时针为正"""
    siny_cosp = 2.0 * (w * z + x * y)
    cosy_cosp = 1.0 - 2.0 * (y * y + z * z)
    return math.atan2(siny_cosp, cosy_cosp)


def angle_diff(a, b):
    """计算两个角度之差，结果在 [-π, π]"""
    d = a - b
    while d >  math.pi: d -= 2 * math.pi
    while d < -math.pi: d += 2 * math.pi
    return d

# ---------------------------------------------------------------------------
# Stanley 控制器
# ---------------------------------------------------------------------------

class StanleyController:
    """
    Stanley 前轮转向控制器。
    参考: Thrun et al., "Stanley: The Robot that Won the DARPA Grand Challenge"
    """

    def __init__(self, k=1.2, k_soft=0.5, max_steer=0.55, wheelbase=0.25):
        """
        k        : 横向误差增益 (越大纠偏越激进)
        k_soft   : 低速软化系数，防止低速时转向过猛
        max_steer: 最大转向角 (rad)，Panda 约 ±0.55 rad (~31°)
        wheelbase: 轴距 (m)，Panda 约 0.25m
        """
        self.k         = k
        self.k_soft    = k_soft
        self.max_steer = max_steer
        self.wheelbase = wheelbase

    def compute(self, vehicle_yaw, vehicle_x, vehicle_y, speed,
                path_x, path_y, path_yaw):
        """
        计算转向角 δ 和对应的 angular.z。

        vehicle_yaw : 车辆当前航向 (rad, ENU)
        vehicle_x/y : 后轴中心 ENU 坐标 (m)
        speed       : 当前速度 (m/s)
        path_x/y    : 路径上最近点坐标 (m)
        path_yaw    : 该路径段的航向 (rad)

        返回: (steering_angle_rad, angular_z_rad_per_s)
        """
        # 前轴位置
        fx = vehicle_x + self.wheelbase * math.cos(vehicle_yaw)
        fy = vehicle_y + self.wheelbase * math.sin(vehicle_yaw)

        # 横向误差 e：前轴到路径点的有符号距离
        dx = fx - path_x
        dy = fy - path_y
        # 路径法向量（左侧为正）
        cross = math.cos(path_yaw) * dy - math.sin(path_yaw) * dx
        e = cross  # 正值 = 车在路径左侧，需右转

        # 航向误差
        psi_e = angle_diff(path_yaw, vehicle_yaw)

        # Stanley 公式
        delta = psi_e + math.atan2(self.k * e, max(speed, self.k_soft))
        delta = max(-self.max_steer, min(self.max_steer, delta))

        # 转向角 → angular.z (阿克曼运动学)
        # angular.z = v * tan(δ) / L
        angular_z = speed * math.tan(delta) / self.wheelbase

        return delta, angular_z

# ---------------------------------------------------------------------------
# 导航节点
# ---------------------------------------------------------------------------

class GPSNavigatorNode(Node):

    def __init__(self, waypoints_file, loop=False, max_speed=0.4,
                 arrival_radius=0.6, wheelbase=0.25, stanley_k=1.2,
                 reverse=False):
        super().__init__("gps_navigator")

        # --- 参数 ---
        self.loop           = loop
        self.max_speed      = max_speed
        self.min_speed      = 0.08          # 最低速度，防止停滞
        self.arrival_radius = arrival_radius
        self.decel_dist     = 2.0           # 开始减速的距离 (m)
        self.reverse        = reverse
        self.ctrl_hz        = 10.0          # 控制频率

        # --- 控制器 ---
        self.stanley = StanleyController(
            k=stanley_k,
            wheelbase=wheelbase,
            max_steer=0.55,
        )

        # --- 状态 ---
        self.origin      = None   # (lat0, lon0, alt0) ENU 原点
        self.pos_x       = None   # 当前 ENU x (east)
        self.pos_y       = None   # 当前 ENU y (north)
        self.heading     = None   # 当前航向 (rad)，GPS 推算
        self.speed       = 0.0    # 当前速度估计 (m/s)
        self.gps_ok      = False
        self.imu_yaw     = None   # IMU 提供的偏航（备用）

        self._prev_x     = None
        self._prev_y     = None
        self._prev_t     = None

        self.wp_index    = 0      # 当前目标航点索引
        self.running     = False
        self.finished    = False

        # --- 加载航点 ---
        self.waypoints = self._load_waypoints(waypoints_file)
        if not self.waypoints:
            self.get_logger().error("航点为空，退出")
            return

        if self.reverse:
            self.waypoints = list(reversed(self.waypoints))

        self.get_logger().info(
            f"已加载 {len(self.waypoints)} 个航点，"
            f"速度={max_speed}m/s，轴距={wheelbase}m，"
            f"到达半径={arrival_radius}m"
        )

        # --- ROS 接口 ---
        self.pub_cmd    = self.create_publisher(Twist, "/cmd_vel", 10)
        self.pub_status = self.create_publisher(String, "/nav_status", 10)

        self.sub_fix = self.create_subscription(
            NavSatFix, TOPIC_FIX_IN, self._on_fix, 10
        )
        self.sub_imu = self.create_subscription(
            Imu, "/imu", self._on_imu, 10
        )

        # 控制定时器
        self.create_timer(1.0 / self.ctrl_hz, self._control_loop)

        self.get_logger().info("等待 GPS 信号...")

    # ------------------------------------------------------------------
    # 航点加载
    # ------------------------------------------------------------------

    def _load_waypoints(self, filepath):
        """加载 path_recorder 保存的 JSON 文件，返回 [(lat,lon,alt), ...]"""
        p = Path(filepath).expanduser()
        if not p.exists():
            self.get_logger().error(f"文件不存在: {p}")
            return []
        with open(p) as f:
            data = json.load(f)

        wps = []
        for w in data.get("waypoints", []):
            wps.append((w["lat"], w["lon"], w.get("alt", 0.0)))

        # 保存原点（用于 ENU 转换）
        if "origin" in data:
            o = data["origin"]
            self.origin = (o["lat"], o["lon"], o.get("alt", 0.0))
        elif wps:
            self.origin = wps[0]

        return wps

    # ------------------------------------------------------------------
    # ROS 回调
    # ------------------------------------------------------------------

    def _on_fix(self, msg: NavSatFix):
        if msg.status.status < 0:
            self.gps_ok = False
            return
        if not GNSSValidator.is_valid(msg.latitude, msg.longitude):
            return

        self.gps_ok = True
        lat, lon, alt = msg.latitude, msg.longitude, msg.altitude

        # 设置 ENU 原点（首次收到信号时）
        if self.origin is None:
            self.origin = (lat, lon, alt)

        lat0, lon0, alt0 = self.origin
        x, y, _ = gps_to_enu(lat, lon, alt, lat0, lon0, alt0)

        now = self.get_clock().now().nanoseconds * 1e-9

        # 从连续 GPS 位置推算航向和速度
        if self._prev_x is not None and self._prev_t is not None:
            dx = x - self._prev_x
            dy = y - self._prev_y
            dt = now - self._prev_t
            dist = math.sqrt(dx*dx + dy*dy)

            if dist > 0.05 and dt > 0.0:  # 移动超过 5cm 才更新航向
                new_heading = math.atan2(dy, dx)  # ENU: 东=0, 北=π/2
                # 低通滤波平滑航向
                if self.heading is None:
                    self.heading = new_heading
                else:
                    alpha = 0.4
                    # 处理角度环绕
                    diff = angle_diff(new_heading, self.heading)
                    self.heading = self.heading + alpha * diff

                self.speed = dist / dt if dt > 0 else 0.0
                self.speed = min(self.speed, self.max_speed * 1.5)  # 限幅

        self._prev_x = x
        self._prev_y = y
        self._prev_t = now
        self.pos_x   = x
        self.pos_y   = y

        # 首次有位置就启动导航
        if not self.running and not self.finished:
            self.running = True
            self.get_logger().info(
                f"GPS 就绪，开始导航。目标航点数: {len(self.waypoints)}"
            )

    def _on_imu(self, msg: Imu):
        """IMU 航向备用（当 GPS 速度太低无法推算航向时使用）"""
        q = msg.orientation
        self.imu_yaw = quat_to_yaw(q.x, q.y, q.z, q.w)

    # ------------------------------------------------------------------
    # 控制主循环
    # ------------------------------------------------------------------

    def _control_loop(self):
        if self.finished or not self.running:
            return

        if not self.gps_ok or self.pos_x is None:
            return

        if self.wp_index >= len(self.waypoints):
            self._on_mission_complete()
            return

        # 当前目标航点 → ENU
        lat0, lon0, alt0 = self.origin
        wp_lat, wp_lon, wp_alt = self.waypoints[self.wp_index]
        wp_x, wp_y, _ = gps_to_enu(wp_lat, wp_lon, wp_alt, lat0, lon0, alt0)

        # 到目标距离
        dx = wp_x - self.pos_x
        dy = wp_y - self.pos_y
        dist = math.sqrt(dx*dx + dy*dy)

        # 到达判断
        if dist < self.arrival_radius:
            self.get_logger().info(
                f"到达航点 {self.wp_index + 1}/{len(self.waypoints)}  "
                f"(误差 {dist:.2f}m)"
            )
            self.wp_index += 1
            if self.wp_index >= len(self.waypoints):
                self._on_mission_complete()
            return

        # 航向：优先 GPS 推算，低速时用 IMU 补充
        heading = self.heading
        if heading is None:
            if self.imu_yaw is not None:
                heading = self.imu_yaw
            else:
                # 还没有航向，先原地转向目标
                heading = math.atan2(dy, dx)

        # 找路径段（当前点 → 目标点）
        path_yaw = math.atan2(dy, dx)

        # 速度控制：接近目标时减速
        if dist < self.decel_dist:
            ratio = dist / self.decel_dist
            target_speed = self.min_speed + (self.max_speed - self.min_speed) * ratio
        else:
            target_speed = self.max_speed

        # Stanley 控制
        _, angular_z = self.stanley.compute(
            vehicle_yaw=heading,
            vehicle_x=self.pos_x,
            vehicle_y=self.pos_y,
            speed=max(target_speed, self.stanley.k_soft),
            path_x=wp_x,
            path_y=wp_y,
            path_yaw=path_yaw,
        )

        # 大转向时适当降速
        steer_ratio = abs(angular_z) / (self.max_speed / self.stanley.wheelbase + 1e-6)
        steer_ratio = min(steer_ratio, 1.0)
        target_speed *= (1.0 - 0.5 * steer_ratio)
        target_speed = max(target_speed, self.min_speed)

        if self.reverse:
            target_speed = -target_speed

        # 发布速度指令
        cmd = Twist()
        cmd.linear.x  = float(target_speed)
        cmd.angular.z = float(angular_z)
        self.pub_cmd.publish(cmd)

        # 状态发布（10Hz 太频繁，每 5 次发一次）
        if not hasattr(self, '_status_cnt'):
            self._status_cnt = 0
        self._status_cnt += 1
        if self._status_cnt % 5 == 0:
            status = (
                f"WP {self.wp_index+1}/{len(self.waypoints)} | "
                f"dist={dist:.2f}m | "
                f"v={target_speed:.2f}m/s | "
                f"ω={angular_z:.2f}rad/s"
            )
            self.get_logger().info(status)
            msg = String()
            msg.data = status
            self.pub_status.publish(msg)

    # ------------------------------------------------------------------
    # 任务完成 / 停止
    # ------------------------------------------------------------------

    def _on_mission_complete(self):
        self._stop()
        if self.loop:
            self.wp_index = 0
            self.get_logger().info("循环模式：重新开始导航")
        else:
            self.finished = True
            self.running  = False
            self.get_logger().info("所有航点已完成，任务结束")

    def _stop(self):
        cmd = Twist()
        self.pub_cmd.publish(cmd)


# ---------------------------------------------------------------------------
# 入口
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="GPS 航点导航 (Stanley, 阿克曼)")
    parser.add_argument("--waypoints", required=True,
                        help="航点 JSON 文件路径 (path_recorder 格式)")
    parser.add_argument("--loop",   action="store_true", help="循环执行")
    parser.add_argument("--reverse",action="store_true", help="反向行驶")
    parser.add_argument("--speed",  type=float, default=0.4,  help="最大速度 m/s (默认 0.4)")
    parser.add_argument("--radius", type=float, default=0.6,  help="到达半径 m (默认 0.6)")
    parser.add_argument("--k",      type=float, default=1.2,  help="Stanley 横向增益 (默认 1.2)")
    parser.add_argument("--wheelbase", type=float, default=0.25,
                        help="轴距 m (默认 0.25，Panda 实测后调整)")
    args, _ = parser.parse_known_args()

    rclpy.init()
    node = GPSNavigatorNode(
        waypoints_file  = args.waypoints,
        loop            = args.loop,
        max_speed       = args.speed,
        arrival_radius  = args.radius,
        wheelbase       = args.wheelbase,
        stanley_k       = args.k,
        reverse         = args.reverse,
    )

    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._stop()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
