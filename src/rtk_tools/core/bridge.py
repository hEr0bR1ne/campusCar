"""Core RTK to UE bridge logic"""
import math
import time
import datetime
import json
import os
from typing import Optional

import rclpy
from rclpy.node import Node
from std_msgs.msg import String
from sensor_msgs.msg import NavSatFix, Image

from config import (TOPIC_FIX_IN, TOPIC_POS_OUT, TOPIC_CMD_IN,
                    TOPIC_IMAGE_OUT, TOPIC_TEXT_OUT,
                    UE_PUBLISH_RATE, UE_INTERPOLATION_ENABLED,
                    RTK_RX_LOG_RATE)
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


class RTKUEBridge(Node):
    """Main RTK to UE bridge - forwards GNSS data and receives commands"""

    def __init__(self, fix_in: str, pos_out: str, cmd_in: str, text_out: str,
                 logfile: Optional[str], image_in: Optional[str], image_out: str):
        super().__init__("rtk_ue_bridge")

        self.logfile = logfile
        self.pos_out = pos_out
        self.last_fix = None
        self.prev_fix = None
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

        self.pub_pos  = self.create_publisher(String, pos_out, 20)
        self.pub_text = self.create_publisher(String, text_out, 10)

        self.sub_fix = self.create_subscription(NavSatFix, fix_in, self._on_fix, 10)
        self.sub_cmd = self.create_subscription(String, cmd_in, self._on_cmd, 10)

        self.pub_img = None
        self.sub_img = None
        if image_in:
            self.pub_img = self.create_publisher(Image, image_out, 10)
            self.sub_img = self.create_subscription(Image, image_in, self._on_img, 10)

        publish_interval = 1.0 / self.publish_rate
        self.position_timer = self.create_timer(publish_interval, self._publish_interpolated_position)

        self.get_logger().info(f"Forward NavSatFix: {fix_in} -> {pos_out} (as JSON String)")
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
        ]) + "}"

    def _publish_payload(self, payload, fix_age_sec=None):
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
        print(
            f"[R2U TX] seq={self.tx_count} {payload['status_name']} "
            f"{pos_text} {age_text} topic={self.pos_out}",
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
        self._publish_payload(self._make_payload(
            status_code=status_code,
            status_name=self._status_name(status_code),
            lat=lat,
            lon=lon,
            alt=alt,
            frame_id=self.last_fix.header.frame_id,
            timestamp=now,
        ), fix_age_sec=now - self.last_fix_time if self.last_fix_time is not None else None)

    def _publish_position(self, fix_msg: NavSatFix, publish_time: float):
        status_code = fix_msg.status.status
        self._publish_payload(self._make_payload(
            status_code=status_code,
            status_name=self._status_name(status_code),
            lat=fix_msg.latitude,
            lon=fix_msg.longitude,
            alt=fix_msg.altitude,
            frame_id=fix_msg.header.frame_id,
            timestamp=self._fix_timestamp(fix_msg),
        ), fix_age_sec=publish_time - self.last_fix_time if self.last_fix_time is not None else None)

    def _on_img(self, msg: Image):
        if self.pub_img is not None:
            self.pub_img.publish(msg)

    def _on_cmd(self, msg: String):
        self.conn_monitor.record_activity()
        self._last_conn_check = 0.0
        line = f"[{self._now_str()}] RX /U2RTopic_Command: {msg.data}"
        print(f"\n\033[92m{line}\033[0m", flush=True)
        self._append_log(line)
