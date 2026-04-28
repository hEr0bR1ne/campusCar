#!/usr/bin/env python3
"""
UE Bridge - 接收 UE 通过 rosbridge 发来的 JSON 指令，控制小车运动
支持：
  1. 方向控制：Forward / TurnLeft / TurnRight / TurnBackward
  2. 坐标导航：直线行驶到目标经纬度

运行：source /opt/ros/humble/setup.bash && python3 ue_bridge.py
"""
import math
import os
from pathlib import Path
import shlex
import threading
import time
import json

import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist, QuaternionStamped
from sensor_msgs.msg import NavSatFix
from std_msgs.msg import String
from motion_profile import shape_twist_for_base

# ── 配置 ──────────────────────────────────────────────────────────────────────

def load_project_env():
    env_file = Path(__file__).resolve().parents[1] / "config" / "robot.env"
    if not env_file.exists():
        return

    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        try:
            parts = shlex.split(line, comments=True, posix=True)
        except ValueError:
            continue
        if not parts or "=" not in parts[0]:
            continue

        key, value = parts[0].split("=", 1)
        if not key.replace("_", "").isalnum() or key[0].isdigit():
            continue
        if key in os.environ or "$(" in value or "${" in value:
            continue
        os.environ[key] = value


load_project_env()


def env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or value == "":
        return default
    try:
        return float(value)
    except ValueError:
        return default


def env_optional_float(name: str) -> float | None:
    value = os.getenv(name)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        return None


def env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return default if value is None or value == "" else value


MAX_LINEAR_SPEED  = env_float("MAX_LINEAR_SPEED", 1.0)   # m/s
MAX_ANGULAR_SPEED = env_float("MAX_ANGULAR_SPEED", 1.0)  # rad/s

CMD_TOPIC     = env_str("UE_COMMAND_TOPIC", "/U2RTopic_Command")  # rosbridge 收到 UE 指令的话题
REPLY_TOPIC   = env_str("RTK_TEXT_TOPIC", "/R2UTopic_Text")       # 回复 UE 的话题
FIX_TOPIC     = env_str("FIX_TOPIC", "/fix")
HEADING_TOPIC = env_str("HEADING_TOPIC", "/heading")
CMD_VEL_TOPIC = env_str("CMD_VEL_TOPIC", "/cmd_vel")

# 导航参数
ARRIVE_THRESHOLD_M  = env_float("UE_ARRIVE_THRESHOLD_M", 0.5)   # 距目标小于此距离视为到达（米）
HEADING_KP          = env_float("UE_HEADING_KP", 1.2)           # 转向比例系数
HEADING_TOLERANCE   = env_float("UE_HEADING_TOLERANCE", 0.15)   # 朝向误差容忍（rad，约 8.6°）
NAV_RATE_HZ         = max(1.0, env_float("UE_NAV_RATE_HZ", 10.0))

# 方向指令会持续补发 /cmd_vel；超时用于防止 UE 掉线后车辆继续运动。
DIRECTION_RATE_HZ      = max(1.0, env_float("UE_DIRECTION_RATE_HZ", 10.0))
DIRECTION_TIMEOUT_SEC  = max(0.0, env_float("UE_DIRECTION_TIMEOUT_SEC", 0.8))

# UE 坐标模式：
# - gps/auto 且 x/y 落在经纬度范围内：x=longitude, y=latitude
# - local/auto 且 x/y 不是经纬度：按 UE 本地坐标转换为 WGS84
UE_COORD_MODE          = env_str("UE_COORD_MODE", "auto").strip().lower()
UE_LOCAL_ORIGIN_LAT    = env_optional_float("UE_LOCAL_ORIGIN_LAT")
UE_LOCAL_ORIGIN_LON    = env_optional_float("UE_LOCAL_ORIGIN_LON")
UE_LOCAL_ORIGIN_X      = env_float("UE_LOCAL_ORIGIN_X", 0.0)
UE_LOCAL_ORIGIN_Y      = env_float("UE_LOCAL_ORIGIN_Y", 0.0)
UE_UNITS_PER_METER     = max(0.000001, abs(env_float("UE_UNITS_PER_METER", 100.0)))
UE_LOCAL_ROTATION_DEG  = env_float("UE_LOCAL_ROTATION_DEG", 0.0)
UE_LOCAL_X_SIGN        = 1.0 if env_float("UE_LOCAL_X_SIGN", 1.0) >= 0 else -1.0
UE_LOCAL_Y_SIGN        = 1.0 if env_float("UE_LOCAL_Y_SIGN", 1.0) >= 0 else -1.0

EARTH_RADIUS_M = 6378137.0


# ── 工具函数 ──────────────────────────────────────────────────────────────────

def quaternion_to_yaw(q) -> float:
    """四元数转 yaw（弧度，ENU 坐标系，北=π/2）"""
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


def haversine(lat1, lon1, lat2, lon2) -> float:
    """返回两点间距离（米）"""
    R = 6371000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing(lat1, lon1, lat2, lon2) -> float:
    """从点1到点2的方位角（弧度，ENU：东=0，北=π/2）"""
    mid_lat = math.radians((lat1 + lat2) * 0.5)
    east = math.radians(lon2 - lon1) * EARTH_RADIUS_M * math.cos(mid_lat)
    north = math.radians(lat2 - lat1) * EARTH_RADIUS_M
    return math.atan2(north, east)


def angle_diff(a, b) -> float:
    """a - b，结果归一化到 [-π, π]"""
    d = a - b
    while d > math.pi:
        d -= 2 * math.pi
    while d < -math.pi:
        d += 2 * math.pi
    return d


def speed_pct_to_ratio(pct_str: str) -> float:
    try:
        pct = float(pct_str)
    except (ValueError, TypeError):
        pct = 30.0
    return max(0.0, min(100.0, pct)) / 100.0


def speed_pct_to_ms(pct_str: str) -> float:
    """'30' -> 0.3 m/s"""
    return MAX_LINEAR_SPEED * speed_pct_to_ratio(pct_str)


def speed_pct_to_rad(pct_str: str) -> float:
    return MAX_ANGULAR_SPEED * speed_pct_to_ratio(pct_str)


def is_valid_lon_lat(lon: float, lat: float) -> bool:
    return -180.0 <= lon <= 180.0 and -90.0 <= lat <= 90.0


def enu_to_wgs84(origin_lat: float, origin_lon: float, east_m: float, north_m: float):
    lat = origin_lat + math.degrees(north_m / EARTH_RADIUS_M)
    cos_lat = math.cos(math.radians(origin_lat))
    if abs(cos_lat) < 1e-9:
        raise ValueError("origin latitude is too close to pole")
    lon = origin_lon + math.degrees(east_m / (EARTH_RADIUS_M * cos_lat))
    return lat, lon


def ue_local_to_wgs84(x: float, y: float):
    if UE_LOCAL_ORIGIN_LAT is None or UE_LOCAL_ORIGIN_LON is None:
        raise ValueError("UE_LOCAL_ORIGIN_LAT/UE_LOCAL_ORIGIN_LON 未配置")

    local_x_m = UE_LOCAL_X_SIGN * (x - UE_LOCAL_ORIGIN_X) / UE_UNITS_PER_METER
    local_y_m = UE_LOCAL_Y_SIGN * (y - UE_LOCAL_ORIGIN_Y) / UE_UNITS_PER_METER
    theta = math.radians(UE_LOCAL_ROTATION_DEG)

    east_m = local_x_m * math.cos(theta) - local_y_m * math.sin(theta)
    north_m = local_x_m * math.sin(theta) + local_y_m * math.cos(theta)
    return enu_to_wgs84(UE_LOCAL_ORIGIN_LAT, UE_LOCAL_ORIGIN_LON, east_m, north_m)


# ── ROS2 节点 ─────────────────────────────────────────────────────────────────

class UEBridgeNode(Node):
    def __init__(self):
        super().__init__("ue_bridge_node")

        self.pub_cmd   = self.create_publisher(Twist, CMD_VEL_TOPIC, 10)
        self.pub_reply = self.create_publisher(String, REPLY_TOPIC, 10)

        self.create_subscription(String,             CMD_TOPIC,     self._on_command, 10)
        self.create_subscription(NavSatFix,          FIX_TOPIC,     self._on_fix,     10)
        self.create_subscription(QuaternionStamped,  HEADING_TOPIC, self._on_heading, 10)

        self._lock    = threading.Lock()
        self.lat      = None
        self.lon      = None
        self.yaw      = None   # 当前朝向（rad，ENU）

        # 导航任务状态
        self._nav_thread: threading.Thread | None = None
        self._nav_stop   = threading.Event()

        # UE 方向指令状态。用定时器持续补发，避免单次 Twist 被底盘看门狗吞掉。
        self._direction_lock = threading.Lock()
        self._direction_active = False
        self._direction_linear = 0.0
        self._direction_angular = 0.0
        self._direction_deadline = 0.0
        self.create_timer(1.0 / DIRECTION_RATE_HZ, self._direction_tick)

        self.get_logger().info("UE Bridge 已启动，监听 " + CMD_TOPIC)
        self.get_logger().info(
            f"UE 方向控制：{DIRECTION_RATE_HZ:.1f}Hz 补发，超时 {DIRECTION_TIMEOUT_SEC:.2f}s"
        )
        self.get_logger().info(f"UE 坐标模式：{UE_COORD_MODE}")

    # ── 传感器回调 ────────────────────────────────────────────────────────────

    def _on_fix(self, msg: NavSatFix):
        with self._lock:
            self.lat = msg.latitude
            self.lon = msg.longitude

    def _on_heading(self, msg: QuaternionStamped):
        with self._lock:
            self.yaw = quaternion_to_yaw(msg.quaternion)

    # ── 指令回调 ──────────────────────────────────────────────────────────────

    def _on_command(self, msg: String):
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            self.get_logger().warn("收到非法 JSON：" + msg.data)
            return

        if data.get("commandType") != "move":
            return

        params      = data.get("commandParams", {})
        destination = params.get("destination")
        speed_str   = params.get("speed", "30")
        cmd_id      = data.get("commandId", "")
        robot_id    = data.get("RobotId", "")

        if isinstance(destination, str):
            self._handle_direction(destination, speed_str)
        elif isinstance(destination, dict):
            self._handle_navigate(destination, speed_str, cmd_id, robot_id)
        else:
            self.get_logger().warn("未知 destination 格式")

    # ── 方向控制 ──────────────────────────────────────────────────────────────

    def _handle_direction(self, direction: str, speed_str: str):
        linear_spd  = speed_pct_to_ms(speed_str)
        angular_spd = speed_pct_to_rad(speed_str)

        d = direction.strip().lower()
        if d == "forward":
            linear = linear_spd
            angular = 0.0
        elif d == "turnbackward":
            linear = -linear_spd
            angular = 0.0
        elif d == "turnleft":
            linear = 0.0
            angular = angular_spd
        elif d == "turnright":
            linear = 0.0
            angular = -angular_spd
        elif d in ("stop", "halt", "brake"):
            linear = 0.0
            angular = 0.0
        else:
            self.get_logger().warn("未知方向指令：" + direction)
            return

        self._cancel_nav()
        if linear == 0.0 and angular == 0.0:
            self._stop_direction_motion()
            self.get_logger().info(f"方向指令：{direction}  停车")
            return

        self._set_direction_motion(linear, angular)
        self.get_logger().info(
            f"方向指令：{direction}  linear={linear:.2f} m/s  angular={angular:.2f} rad/s"
        )

    def _set_direction_motion(self, linear: float, angular: float):
        with self._direction_lock:
            self._direction_active = True
            self._direction_linear = linear
            self._direction_angular = angular
            self._direction_deadline = (
                time.monotonic() + DIRECTION_TIMEOUT_SEC
                if DIRECTION_TIMEOUT_SEC > 0.0
                else float("inf")
            )
        self._publish_twist(linear, angular)

    def _stop_direction_motion(self):
        with self._direction_lock:
            self._direction_active = False
            self._direction_linear = 0.0
            self._direction_angular = 0.0
            self._direction_deadline = 0.0
        self._publish_twist(0.0, 0.0)

    def _direction_tick(self):
        should_stop = False
        with self._direction_lock:
            if not self._direction_active:
                return

            if time.monotonic() > self._direction_deadline:
                self._direction_active = False
                self._direction_linear = 0.0
                self._direction_angular = 0.0
                self._direction_deadline = 0.0
                should_stop = True
                linear = 0.0
                angular = 0.0
            else:
                linear = self._direction_linear
                angular = self._direction_angular

        self._publish_twist(linear, angular)
        if should_stop:
            self.get_logger().warn("UE 方向指令超时，已自动停车")

    # ── 坐标导航 ──────────────────────────────────────────────────────────────

    def _handle_navigate(self, dest: dict, speed_str: str, cmd_id: str, robot_id: str):
        try:
            target_lat, target_lon, coord_source = self._resolve_destination(dest)
        except (KeyError, TypeError, ValueError) as exc:
            self.get_logger().error(f"坐标目标无效：{exc}")
            return

        linear_spd = speed_pct_to_ms(speed_str)
        if linear_spd <= 0.0:
            self._cancel_nav()
            self._stop_direction_motion()
            self.get_logger().info("收到 speed=0 的坐标导航指令，已停车")
            return

        with self._lock:
            if self.lat is None or self.lon is None:
                self.get_logger().error("GPS 未就绪，无法导航")
                return
            if self.yaw is None:
                self.get_logger().error("朝向未就绪，无法导航")
                return

        self.get_logger().info(
            f"导航目标({coord_source})：lat={target_lat:.8f}, lon={target_lon:.8f}  "
            f"速度：{linear_spd:.2f} m/s"
        )
        self._stop_direction_motion()
        self._cancel_nav()
        self._nav_stop.clear()
        self._nav_thread = threading.Thread(
            target=self._nav_loop,
            args=(target_lat, target_lon, linear_spd, cmd_id, robot_id),
            daemon=True,
        )
        self._nav_thread.start()

    def _resolve_destination(self, dest: dict):
        x = float(dest["x"])
        y = float(dest["y"])
        mode = UE_COORD_MODE if UE_COORD_MODE in ("auto", "gps", "local") else "auto"

        if mode in ("auto", "gps") and is_valid_lon_lat(x, y):
            return y, x, "wgs84"

        if mode == "gps":
            raise ValueError(f"x/y 不在经纬度范围内：x={x}, y={y}")

        target_lat, target_lon = ue_local_to_wgs84(x, y)
        return target_lat, target_lon, "ue-local"

    def _nav_loop(self, target_lat, target_lon, linear_spd, cmd_id, robot_id):
        """导航主循环：先对准方向，再直行，到达后停止"""
        rate_hz = NAV_RATE_HZ
        dt = 1.0 / rate_hz

        while not self._nav_stop.is_set():
            with self._lock:
                cur_lat = self.lat
                cur_lon = self.lon
                cur_yaw = self.yaw

            if cur_lat is None or cur_yaw is None:
                time.sleep(dt)
                continue

            dist = haversine(cur_lat, cur_lon, target_lat, target_lon)
            if dist < ARRIVE_THRESHOLD_M:
                self._publish_twist(0.0, 0.0)
                self.get_logger().info("已到达目标点")
                self._reply(cmd_id, robot_id, "arrived")
                return

            target_bearing = bearing(cur_lat, cur_lon, target_lat, target_lon)
            err = angle_diff(target_bearing, cur_yaw)

            if abs(err) > HEADING_TOLERANCE:
                # 先原地转向对准目标
                angular = max(-MAX_ANGULAR_SPEED,
                              min(MAX_ANGULAR_SPEED, HEADING_KP * err))
                self._publish_twist(0.0, angular)
            else:
                # 朝向对准后直行，并保留小角度修正，避免长距离漂移。
                angular = max(-MAX_ANGULAR_SPEED,
                              min(MAX_ANGULAR_SPEED, HEADING_KP * err * 0.5))
                self._publish_twist(linear_spd, angular)

            time.sleep(dt)

        # 被取消时停车
        self._publish_twist(0.0, 0.0)

    def _cancel_nav(self):
        if self._nav_thread and self._nav_thread.is_alive():
            self._nav_stop.set()
            self._nav_thread.join(timeout=1.0)

    # ── 工具 ──────────────────────────────────────────────────────────────────

    def _publish_twist(self, linear: float, angular: float):
        linear, angular = shape_twist_for_base(linear, angular)
        t = Twist()
        t.linear.x  = linear
        t.angular.z = angular
        self.pub_cmd.publish(t)

    def _reply(self, cmd_id: str, robot_id: str, status: str):
        payload = json.dumps({
            "commandId": cmd_id,
            "RobotId":   robot_id,
            "status":    status,
        })
        msg = String()
        msg.data = payload
        self.pub_reply.publish(msg)


# ── 入口 ──────────────────────────────────────────────────────────────────────

def main():
    rclpy.init()
    node = UEBridgeNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node._cancel_nav()
        node._stop_direction_motion()
        node._publish_twist(0.0, 0.0)
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
