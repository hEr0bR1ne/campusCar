#!/usr/bin/env python3
"""
RTSP 推流服务（ROS2 版）
订阅 ROS2 相机话题，通过 ffmpeg 推送 H.264 RTSP 流供 UE5 拉取

用法:
  source /opt/ros/humble/setup.bash
  python3 rtsp_server.py
  python3 rtsp_server.py --topic /camera/color/image_raw --rtsp rtsp://127.0.0.1:8554/robot_cam
"""
import argparse
import os
import subprocess
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CompressedImage

DEFAULT_TOPIC = "/camera/color/image_raw"
DEFAULT_RTSP  = "rtsp://127.0.0.1:8554/robot_cam"
DEFAULT_FPS   = 30
DEFAULT_BITRATE = 1000  # kbps
DEFAULT_RESTART_INTERVAL = 1.0

_ffmpeg_proc = None
_ffmpeg_log_fp = None
_proc_lock   = threading.Lock()
_frame_w     = 0
_frame_h     = 0
_last_start_ts = 0.0
_last_error_log_ts = 0.0


def _default_ffmpeg_log() -> str:
    return str(Path(__file__).parent.parent / "data" / "logs" / "ffmpeg_rtsp.log")


def _open_ffmpeg_log(log_path: str):
    directory = os.path.dirname(log_path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    fp = open(log_path, "ab", buffering=0)
    banner = (
        f"\n[{time.strftime('%F %T')}] start ffmpeg publisher\n".encode("utf-8")
    )
    fp.write(banner)
    return fp


def _start_ffmpeg(w: int, h: int, fps: int, bitrate: int, rtsp_url: str, log_path: str):
    log_fp = _open_ffmpeg_log(log_path)
    cmd = [
        "ffmpeg", "-loglevel", "warning", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-r", str(fps),
        "-i", "-",
        "-an",
        "-c:v", "libx264",
        "-preset", "ultrafast",
        "-tune", "zerolatency",
        "-profile:v", "baseline",
        "-pix_fmt", "yuv420p",
        "-g", str(fps),
        "-keyint_min", str(fps),
        "-sc_threshold", "0",
        "-bf", "0",
        "-b:v", f"{bitrate}k",
        "-maxrate", f"{bitrate}k",
        "-bufsize", f"{bitrate * 2}k",
        "-f", "rtsp",
        "-rtsp_transport", "tcp",
        rtsp_url,
    ]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=log_fp,
        stderr=log_fp,
    )
    return proc, log_fp


def _stop_ffmpeg():
    global _ffmpeg_proc, _ffmpeg_log_fp
    if _ffmpeg_proc is not None:
        try:
            if _ffmpeg_proc.stdin is not None:
                _ffmpeg_proc.stdin.close()
            _ffmpeg_proc.wait(timeout=2)
        except Exception:
            _ffmpeg_proc.kill()
        finally:
            _ffmpeg_proc = None
    if _ffmpeg_log_fp is not None:
        _ffmpeg_log_fp.close()
        _ffmpeg_log_fp = None


class RTSPNode(Node):
    def __init__(self, topic: str, rtsp_url: str, fps: int, bitrate: int, ffmpeg_log: str):
        super().__init__("rtsp_server_node")
        self._rtsp_url = rtsp_url
        self._fps      = fps
        self._bitrate  = bitrate
        self._ffmpeg_log = ffmpeg_log
        self.create_subscription(Image, topic, self._on_image, 10)
        compressed = topic.rstrip("/") + "/compressed"
        self.create_subscription(CompressedImage, compressed, self._on_compressed, 10)
        self.get_logger().info(f"订阅话题: {topic}")
        self.get_logger().info(f"推流地址: {rtsp_url}")
        self.get_logger().info(f"ffmpeg 日志: {ffmpeg_log}")

    def _on_image(self, msg: Image):
        enc = msg.encoding.lower()
        data = np.frombuffer(msg.data, dtype=np.uint8)
        try:
            if enc == "rgb8":
                img = data.reshape((msg.height, msg.width, 3))
                img = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
            elif enc == "bgr8":
                img = data.reshape((msg.height, msg.width, 3))
            elif enc == "mono8":
                img = cv2.cvtColor(
                    data.reshape((msg.height, msg.width)), cv2.COLOR_GRAY2BGR)
            else:
                img = data.reshape((msg.height, msg.width, -1))
        except Exception:
            return
        self._push(img)

    def _on_compressed(self, msg: CompressedImage):
        data = np.frombuffer(msg.data, dtype=np.uint8)
        img = cv2.imdecode(data, cv2.IMREAD_COLOR)
        if img is not None:
            self._push(img)

    def _push(self, img):
        global _ffmpeg_proc, _ffmpeg_log_fp, _frame_w, _frame_h, _last_start_ts, _last_error_log_ts
        h, w = img.shape[:2]
        with _proc_lock:
            needs_restart = (
                _ffmpeg_proc is None
                or _ffmpeg_proc.poll() is not None
                or w != _frame_w
                or h != _frame_h
            )
            if needs_restart:
                exit_code = None if _ffmpeg_proc is None else _ffmpeg_proc.poll()
                now = time.monotonic()
                if exit_code is not None and now - _last_error_log_ts >= DEFAULT_RESTART_INTERVAL:
                    self.get_logger().warning(
                        f"ffmpeg 已退出 (code={exit_code})，准备重连"
                    )
                    _last_error_log_ts = now
                if now - _last_start_ts < DEFAULT_RESTART_INTERVAL:
                    return
                _stop_ffmpeg()
                _frame_w, _frame_h = w, h
                _ffmpeg_proc, _ffmpeg_log_fp = _start_ffmpeg(
                    w,
                    h,
                    self._fps,
                    self._bitrate,
                    self._rtsp_url,
                    self._ffmpeg_log,
                )
                _last_start_ts = now
                self.get_logger().info(f"ffmpeg 已启动 ({w}x{h})")
            try:
                if _ffmpeg_proc is not None and _ffmpeg_proc.stdin is not None:
                    _ffmpeg_proc.stdin.write(img.tobytes())
            except (BrokenPipeError, OSError):
                now = time.monotonic()
                if now - _last_error_log_ts >= DEFAULT_RESTART_INTERVAL:
                    self.get_logger().warning("ffmpeg 管道写入失败，等待下一帧重连")
                    _last_error_log_ts = now
                _stop_ffmpeg()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic",   default=DEFAULT_TOPIC)
    parser.add_argument("--rtsp",    default=DEFAULT_RTSP)
    parser.add_argument("--fps",     type=int, default=DEFAULT_FPS)
    parser.add_argument("--bitrate", type=int, default=DEFAULT_BITRATE)
    parser.add_argument("--ffmpeg-log", default=_default_ffmpeg_log())
    args = parser.parse_args()

    rclpy.init()
    node = RTSPNode(args.topic, args.rtsp, args.fps, args.bitrate, args.ffmpeg_log)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        with _proc_lock:
            _stop_ffmpeg()
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
