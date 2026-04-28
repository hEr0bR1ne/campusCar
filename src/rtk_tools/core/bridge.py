"""Core RTK to UE bridge logic"""
import math
import time
import datetime
import json
import os
from typing import Optional

import rclpy
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from nav_msgs.msg import Odometry
from std_msgs.msg import String
from sensor_msgs.msg import NavSatFix, Image, Imu

from config import (TOPIC_FIX_IN, TOPIC_POS_OUT, TOPIC_CMD_IN,
                    TOPIC_IMAGE_OUT, TOPIC_TEXT_OUT,
                    UE_PUBLISH_RATE, UE_INTERPOLATION_ENABLED,
                    RTK_RX_LOG_RATE, VEHICLE_HEADING_OFFSET_DEG,
                    RTK_POSITION_HOLD_ENABLED,
                    RTK_POSITION_HOLD_SPEED_THRESHOLD_MPS,
                    RTK_POSITION_HOLD_ODOM_TIMEOUT_SEC, ROOT_DIR)
from core.gnss import GNSSValidator
from core.connection import ConnectionMonitor


STATUS_MAP = {
    -1: "NO_FIX",
    0: "GPS_FIX",
    1: "DGPS_FIX",
    2: "PPS_FIX",
    4: "RTK_FIXED",
    5: "RTK_FLOAT",
}


def finite_float(value):
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) else None


def quaternion_to_yaw_rad(q) -> float:
    siny = 2.0 * (q.w * q.z + q.x * q.y)
    cosy = 1.0 - 2.0 * (q.y * q.y + q.z * q.z)
    return math.atan2(siny, cosy)


_HEADING_OFFSET_PATH = ROOT_DIR / "config" / "robot.env"
_heading_offset_mtime = None
_heading_offset_value = float(VEHICLE_HEADING_OFFSET_DEG)


def _parse_heading_offset_file() -> Optional[float]:
    try:
        for line in _HEADING_OFFSET_PATH.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if stripped.startswith("VEHICLE_HEADING_OFFSET_DEG="):
                return float(stripped.split("=", 1)[1].strip().strip("\"'"))
    except (OSError, ValueError):
        return None
    return None


def vehicle_heading_offset_deg() -> float:
    global _heading_offset_mtime, _heading_offset_value
    try:
        mtime = _HEADING_OFFSET_PATH.stat().st_mtime
    except OSError:
        return _heading_offset_value

    if mtime != _heading_offset_mtime:
        parsed = _parse_heading_offset_file()
        if parsed is not None:
            _heading_offset_value = parsed
        _heading_offset_mtime = mtime
    return _heading_offset_value


def apply_heading_offset_rad(yaw_rad: float) -> float:
    adjusted = yaw_rad + math.radians(vehicle_heading_offset_deg())
    return math.atan2(math.sin(adjusted), math.cos(adjusted))


class RTKUEBridge(Node):
    """Main RTK to UE bridge - forwards GNSS data and receives commands"""

    def __init__(self, fix_in: str, imu_in: str, odom_in: str,
                 pos_out: str, cmd_in: str, text_out: str,
                 logfile: Optional[str], image_in: Optional[str], image_out: str):
        super().__init__("rtk_ue_bridge")

        self.logfile = logfile
        self.pos_out = pos_out
        self.last_fix = None
        self.prev_fix = None
        self.last_imu_state = None
        self.last_odom_state = None
        self.fix_count = 0
        self.tx_count = 0
        self.conn_monitor = ConnectionMonitor()
        self._last_conn_check = 0.0
        self._ue_status_cache = ("⏳ 等待UE数据", "\033[94m")

        self.interpolation_enabled = UE_INTERPOLATION_ENABLED
        self.publish_rate = max(float(UE_PUBLISH_RATE), 0.1)
        self.rx_log_rate = max(float(RTK_RX_LOG_RATE), 0.0)
        self.last_fix_time = None
        self.prev_fix_time = None
        self._last_rx_log_time = 0.0
        self.position_hold_enabled = bool(RTK_POSITION_HOLD_ENABLED)
        self.position_hold_speed_threshold = max(float(RTK_POSITION_HOLD_SPEED_THRESHOLD_MPS), 0.0)
        self.position_hold_odom_timeout = max(float(RTK_POSITION_HOLD_ODOM_TIMEOUT_SEC), 0.1)
        self.position_cache = None
        self.position_cache_updated_at = None

        self.pub_pos  = self.create_publisher(String, pos_out, 20)
        self.pub_text = self.create_publisher(String, text_out, 10)

        self.sub_fix = self.create_subscription(NavSatFix, fix_in, self._on_fix, 10)
        self.sub_imu = self.create_subscription(Imu, imu_in, self._on_imu, qos_profile_sensor_data)
        self.sub_odom = self.create_subscription(Odometry, odom_in, self._on_odom, qos_profile_sensor_data)
        self.sub_cmd = self.create_subscription(String, cmd_in, self._on_cmd, 10)

        self.pub_img = None
        self.sub_img = None
        if image_in:
            self.pub_img = self.create_publisher(Image, image_out, 10)
            self.sub_img = self.create_subscription(Image, image_in, self._on_img, 10)

        publish_interval = 1.0 / self.publish_rate
        self.position_timer = self.create_timer(publish_interval, self._publish_interpolated_position)

        self.get_logger().info(f"Forward NavSatFix: {fix_in} -> {pos_out} (as JSON String)")
        self.get_logger().info(f"Attach vehicle state: IMU {imu_in}, odom {odom_in}")
        self.get_logger().info(f"Publish text: {text_out}")
        self.get_logger().info(f"Listen commands: {cmd_in}")
        if image_in:
            self.get_logger().info(f"Forward images: {image_in} -> {image_out}")
        if logfile:
            self.get_logger().info(f"Command log: {logfile}")
        self.get_logger().info(
            f"UE5 position publish rate: {self.publish_rate}Hz "
            f"(interpolation: {self.interpolation_enabled})"
        )
        if self.position_hold_enabled:
            self.get_logger().info(
                "RTK position hold enabled: update UE coordinate cache only when "
                f"/odom speed > {self.position_hold_speed_threshold:.3f}m/s; "
                f"odom timeout {self.position_hold_odom_timeout:.1f}s"
            )
        if self.rx_log_rate <= 0.0:
            self.get_logger().info("Raw /fix RX console log disabled; use RTK_RX_LOG_RATE>0 to enable")

    def _get_ue_status(self):
        now = time.time()
        if now - self._last_conn_check >= 5.0:
            self._last_conn_check = now
            self._ue_status_cache = self.conn_monitor.get_status()
        return self._ue_status_cache

    def _now_str(self):
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    def _append_log(self, line: str):
        if not self.logfile:
            return
        os.makedirs(os.path.dirname(self.logfile), exist_ok=True)
        with open(self.logfile, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def _status_name(self, status_code: int):
        return STATUS_MAP.get(status_code, "UNKNOWN")

    def _fix_timestamp(self, fix_msg: Optional[NavSatFix]):
        if fix_msg is None:
            return None
        return fix_msg.header.stamp.sec + fix_msg.header.stamp.nanosec / 1e9

    def _header_timestamp(self, msg):
        if msg is None:
            return None
        stamp = msg.header.stamp
        value = stamp.sec + stamp.nanosec / 1e9
        return value if value > 0 else None

    def _make_payload(self, *, status_code: int, status_name: str, lat, lon, alt,
                      frame_id: str, timestamp: float):
        return {
            "status": status_code,
            "status_name": status_name,
            "latitude": float(lat) if lat is not None and math.isfinite(lat) else None,
            "longitude": float(lon) if lon is not None and math.isfinite(lon) else None,
            "altitude": float(alt) if alt is not None and math.isfinite(alt) else None,
            "timestamp": timestamp,
            "frame_id": frame_id,
            "vehicle": self._make_vehicle_payload(),
        }

    def _format_coordinate(self, value):
        if value is None:
            return "null"
        return f"{float(value):.8f}"

    def _payload_to_json(self, payload):
        return "{" + ", ".join([
            f"\"status\": {json.dumps(payload['status'])}",
            f"\"status_name\": {json.dumps(payload['status_name'])}",
            f"\"latitude\": {self._format_coordinate(payload['latitude'])}",
            f"\"longitude\": {self._format_coordinate(payload['longitude'])}",
            f"\"altitude\": {json.dumps(payload['altitude'], allow_nan=False)}",
            f"\"timestamp\": {json.dumps(payload['timestamp'], allow_nan=False)}",
            f"\"frame_id\": {json.dumps(payload['frame_id'])}",
            f"\"vehicle\": {json.dumps(payload.get('vehicle'), ensure_ascii=False, allow_nan=False)}",
        ]) + "}"

    def _make_vehicle_payload(self):
        now = time.time()
        imu = self.last_imu_state
        odom = self.last_odom_state

        heading_source = None
        yaw_rad = yaw_deg = None
        if imu is not None and now - imu["received_at"] <= 3.0:
            heading_source = "imu"
            yaw_rad = imu["yaw_rad"]
            yaw_deg = imu["yaw_deg"]
        elif odom is not None and now - odom["received_at"] <= 3.0:
            heading_source = "odom"
            yaw_rad = odom["yaw_rad"]
            yaw_deg = odom["yaw_deg"]

        angular_velocity = None
        linear_acceleration = None
        if imu is not None:
            angular_velocity = imu["angular_velocity"]
            linear_acceleration = imu["linear_acceleration"]
        elif odom is not None:
            angular_velocity = odom["angular_velocity"]

        return {
            "heading_source": heading_source,
            "yaw_rad": finite_float(yaw_rad),
            "yaw_deg": finite_float(yaw_deg),
            "heading_offset_deg": finite_float(vehicle_heading_offset_deg()),
            "speed_mps": finite_float(odom["speed_mps"]) if odom is not None else None,
            "linear_velocity": odom["linear_velocity"] if odom is not None else None,
            "angular_velocity": angular_velocity,
            "linear_acceleration": linear_acceleration,
            "imu_age_sec": finite_float(now - imu["received_at"]) if imu is not None else None,
            "odom_age_sec": finite_float(now - odom["received_at"]) if odom is not None else None,
            "imu_frame_id": imu["frame_id"] if imu is not None else None,
            "odom_frame_id": odom["frame_id"] if odom is not None else None,
            "odom_child_frame_id": odom["child_frame_id"] if odom is not None else None,
            "imu_timestamp": imu["timestamp"] if imu is not None else None,
            "odom_timestamp": odom["timestamp"] if odom is not None else None,
        }

    def _publish_payload(self, payload, fix_age_sec=None, hold_state=None):
        self.tx_count += 1

        msg = String()
        msg.data = self._payload_to_json(payload)
        self.pub_pos.publish(msg)

        lat = payload["latitude"]
        lon = payload["longitude"]
        alt = payload["altitude"]
        if lat is None or lon is None:
            pos_text = "Lat: null, Lon: null"
        else:
            alt_text = f", Alt: {alt:.1f}m" if alt is not None else ""
            pos_text = f"Lat: {lat:.8f}, Lon: {lon:.8f}{alt_text}"
        age_text = "no-fix" if fix_age_sec is None else f"age={fix_age_sec:.2f}s"
        vehicle = payload.get("vehicle") or {}
        vehicle_text = ""
        if vehicle.get("yaw_deg") is not None or vehicle.get("speed_mps") is not None:
            yaw_text = "--" if vehicle.get("yaw_deg") is None else f"{vehicle['yaw_deg']:.1f}deg"
            speed_text = "--" if vehicle.get("speed_mps") is None else f"{vehicle['speed_mps']:.2f}m/s"
            source_text = vehicle.get("heading_source") or "none"
            vehicle_text = f" yaw={yaw_text}({source_text}) speed={speed_text}"
        hold_text = f" hold={hold_state}" if hold_state else ""
        print(
            f"[R2U TX] seq={self.tx_count} {payload['status_name']} "
            f"{pos_text}{vehicle_text} {age_text}{hold_text} topic={self.pos_out}",
            flush=True,
        )

    def _log_raw_fix(self, msg: NavSatFix, status_name: str):
        if self.rx_log_rate <= 0.0:
            return

        now = time.time()
        if now - self._last_rx_log_time < 1.0 / self.rx_log_rate:
            return
        self._last_rx_log_time = now

        ue_text, ue_color = self._get_ue_status()
        ue_str = f"{ue_color}[UE: {ue_text}]\033[0m"
        if msg.status.status < 0:
            print(f"[GPS RX] NO_FIX | {ue_str}", flush=True)
        elif GNSSValidator.is_valid(msg.latitude, msg.longitude):
            print(
                f"[GPS RX] {status_name} "
                f"Lat: {msg.latitude:.6f}, Lon: {msg.longitude:.6f}, "
                f"Alt: {msg.altitude:.1f}m | {ue_str}",
                flush=True,
            )
        else:
            print(f"[GPS RX] {status_name} (坐标无效) | {ue_str}", flush=True)

    def _on_fix(self, msg: NavSatFix):
        self.prev_fix = self.last_fix
        self.prev_fix_time = self.last_fix_time
        self.last_fix = msg
        self.last_fix_time = time.time()
        self.fix_count += 1

        self._log_raw_fix(msg, self._status_name(msg.status.status))

    def _on_imu(self, msg: Imu):
        yaw_rad = apply_heading_offset_rad(quaternion_to_yaw_rad(msg.orientation))
        self.last_imu_state = {
            "received_at": time.time(),
            "timestamp": self._header_timestamp(msg),
            "frame_id": msg.header.frame_id,
            "yaw_rad": finite_float(yaw_rad),
            "yaw_deg": finite_float(math.degrees(yaw_rad) % 360.0),
            "angular_velocity": {
                "x": finite_float(msg.angular_velocity.x),
                "y": finite_float(msg.angular_velocity.y),
                "z": finite_float(msg.angular_velocity.z),
            },
            "linear_acceleration": {
                "x": finite_float(msg.linear_acceleration.x),
                "y": finite_float(msg.linear_acceleration.y),
                "z": finite_float(msg.linear_acceleration.z),
            },
        }

    def _on_odom(self, msg: Odometry):
        yaw_rad = apply_heading_offset_rad(quaternion_to_yaw_rad(msg.pose.pose.orientation))
        vx = finite_float(msg.twist.twist.linear.x)
        vy = finite_float(msg.twist.twist.linear.y)
        vz = finite_float(msg.twist.twist.linear.z)
        speed = math.hypot(vx, vy) if vx is not None and vy is not None else None
        self.last_odom_state = {
            "received_at": time.time(),
            "timestamp": self._header_timestamp(msg),
            "frame_id": msg.header.frame_id,
            "child_frame_id": msg.child_frame_id,
            "yaw_rad": finite_float(yaw_rad),
            "yaw_deg": finite_float(math.degrees(yaw_rad) % 360.0),
            "speed_mps": finite_float(speed),
            "linear_velocity": {
                "x": vx,
                "y": vy,
                "z": vz,
            },
            "angular_velocity": {
                "x": finite_float(msg.twist.twist.angular.x),
                "y": finite_float(msg.twist.twist.angular.y),
                "z": finite_float(msg.twist.twist.angular.z),
            },
        }

    def _make_position_sample(self, *, status_code: int, lat, lon, alt,
                              frame_id: str, timestamp: float, fix_time):
        return {
            "status_code": status_code,
            "status_name": self._status_name(status_code),
            "lat": lat,
            "lon": lon,
            "alt": alt,
            "frame_id": frame_id,
            "timestamp": timestamp,
            "fix_time": fix_time,
        }

    def _current_speed_state(self, now: float):
        odom = self.last_odom_state
        if odom is None:
            return None, None, "no-odom"
        age = now - odom["received_at"]
        if age > self.position_hold_odom_timeout:
            return None, age, "odom-stale"
        return odom.get("speed_mps"), age, "odom"

    def _sample_is_valid(self, sample) -> bool:
        return (
            sample is not None
            and GNSSValidator.is_valid(sample.get("lat"), sample.get("lon"))
        )

    def _cache_position_sample(self, sample, now: float):
        if self._sample_is_valid(sample):
            self.position_cache = dict(sample)
            self.position_cache_updated_at = now

    def _apply_position_hold(self, live_sample, now: float):
        if not self.position_hold_enabled:
            return live_sample, "off"

        speed, speed_age, speed_source = self._current_speed_state(now)
        if self.position_cache is None:
            self._cache_position_sample(live_sample, now)
            return live_sample, "init"

        if speed is None:
            self._cache_position_sample(live_sample, now)
            return live_sample, speed_source

        if speed > self.position_hold_speed_threshold:
            self._cache_position_sample(live_sample, now)
            return live_sample, f"moving:{speed:.2f}m/s"

        cached = dict(self.position_cache)
        cached["timestamp"] = now
        return cached, f"stopped:{speed:.2f}m/s"

    def _publish_position_sample(self, sample, now: float):
        sample, hold_state = self._apply_position_hold(sample, now)
        fix_time = sample.get("fix_time")
        fix_age_sec = now - fix_time if fix_time is not None else None
        self._publish_payload(self._make_payload(
            status_code=sample["status_code"],
            status_name=sample["status_name"],
            lat=sample["lat"],
            lon=sample["lon"],
            alt=sample["alt"],
            frame_id=sample["frame_id"],
            timestamp=sample["timestamp"],
        ), fix_age_sec=fix_age_sec, hold_state=hold_state)

    def _publish_interpolated_position(self):
        now = time.time()
        if self.last_fix is None:
            return

        if not self.interpolation_enabled or self.prev_fix is None or self.prev_fix_time is None:
            self._publish_position(self.last_fix, now)
            return

        if not GNSSValidator.is_valid(self.last_fix.latitude, self.last_fix.longitude):
            self._publish_position(self.last_fix, now)
            return

        if not GNSSValidator.is_valid(self.prev_fix.latitude, self.prev_fix.longitude):
            self._publish_position(self.last_fix, now)
            return

        time_since_last   = now - self.last_fix_time
        time_between_fixes = self.last_fix_time - self.prev_fix_time

        if time_between_fixes <= 0.001:
            self._publish_position(self.last_fix, now)
            return

        alpha = (time_since_last + time_between_fixes) / time_between_fixes
        max_alpha = 1.0 + (0.5 / time_between_fixes)
        alpha = min(alpha, max_alpha)

        lat = self.prev_fix.latitude  + alpha * (self.last_fix.latitude  - self.prev_fix.latitude)
        lon = self.prev_fix.longitude + alpha * (self.last_fix.longitude - self.prev_fix.longitude)
        alt = self.prev_fix.altitude  + alpha * (self.last_fix.altitude  - self.prev_fix.altitude)

        status_code = self.last_fix.status.status
        self._publish_position_sample(self._make_position_sample(
            status_code=status_code,
            lat=lat,
            lon=lon,
            alt=alt,
            frame_id=self.last_fix.header.frame_id,
            timestamp=now,
            fix_time=self.last_fix_time,
        ), now)

    def _publish_position(self, fix_msg: NavSatFix, publish_time: float):
        status_code = fix_msg.status.status
        self._publish_position_sample(self._make_position_sample(
            status_code=status_code,
            lat=fix_msg.latitude,
            lon=fix_msg.longitude,
            alt=fix_msg.altitude,
            frame_id=fix_msg.header.frame_id,
            timestamp=self._fix_timestamp(fix_msg),
            fix_time=self.last_fix_time,
        ), publish_time)

    def _on_img(self, msg: Image):
        if self.pub_img is not None:
            self.pub_img.publish(msg)

    def _on_cmd(self, msg: String):
        self.conn_monitor.record_activity()
        self._last_conn_check = 0.0
        line = f"[{self._now_str()}] RX /U2RTopic_Command: {msg.data}"
        print(f"\n\033[92m{line}\033[0m", flush=True)
        self._append_log(line)
