#!/usr/bin/env python3
"""
MJPEG HTTP 推流服务
订阅 ROS2 相机话题，通过 HTTP 推送 MJPEG 视频流供 UE5 拉取

用法:
  source /opt/ros/humble/setup.bash
  python3 mjpeg_server.py
  python3 mjpeg_server.py --port 8080 --quality 80 --topic /camera/color/image_flipped
"""
import sys
import os
import threading
import time
import argparse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image, CompressedImage
import cv2
import numpy as np

DEFAULT_TOPIC   = "/camera/color/image_flipped"
DEFAULT_PORT    = 8080
DEFAULT_QUALITY = 80

# 全局最新帧（JPEG bytes）
_latest_jpeg: bytes = b""
_frame_lock = threading.Lock()
_frame_event = threading.Event()


class CameraNode(Node):
    def __init__(self, topic: str):
        super().__init__("mjpeg_server_node")
        self.create_subscription(Image, topic, self._on_image, 10)
        compressed = topic.rstrip("/") + "/compressed"
        self.create_subscription(CompressedImage, compressed, self._on_compressed, 10)
        self.get_logger().info(f"订阅话题: {topic}")

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
                img = cv2.cvtColor(data.reshape((msg.height, msg.width)), cv2.COLOR_GRAY2BGR)
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
        global _latest_jpeg
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, QUALITY])
        if ok:
            with _frame_lock:
                _latest_jpeg = buf.tobytes()
            _frame_event.set()


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class MJPEGHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # 静默 HTTP 日志

    def do_GET(self):
        if self.path == "/stream":
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace; boundary=frame")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    _frame_event.wait(timeout=2.0)
                    _frame_event.clear()
                    with _frame_lock:
                        jpeg = _latest_jpeg
                    if not jpeg:
                        continue
                    self.wfile.write(
                        b"--frame\r\n"
                        b"Content-Type: image/jpeg\r\n\r\n" +
                        jpeg + b"\r\n"
                    )
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError):
                pass
        elif self.path == "/":
            # 简单预览页
            html = b"""<!DOCTYPE html><html><body style="background:#000;margin:0">
<img src="/stream" style="max-width:100%;display:block;margin:auto">
</body></html>"""
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(html)
        else:
            self.send_response(404)
            self.end_headers()


def _spin_safe(node):
    from rclpy.executors import ExternalShutdownException
    try:
        rclpy.spin(node)
    except (ExternalShutdownException, Exception):
        pass


def main():
    global QUALITY
    parser = argparse.ArgumentParser()
    parser.add_argument("--topic",   default=DEFAULT_TOPIC)
    parser.add_argument("--port",    type=int, default=DEFAULT_PORT)
    parser.add_argument("--quality", type=int, default=DEFAULT_QUALITY)
    args = parser.parse_args()
    QUALITY = args.quality

    rclpy.init()
    node = CameraNode(args.topic)
    t = threading.Thread(target=_spin_safe, args=(node,), daemon=True)
    t.start()

    server = ThreadedHTTPServer(("0.0.0.0", args.port), MJPEGHandler)
    server.socket.setsockopt(1, 2, 1)  # SO_REUSEADDR
    print(f"[MJPEG] 推流地址: http://0.0.0.0:{args.port}/stream")
    print(f"[MJPEG] 浏览器预览: http://127.0.0.1:{args.port}/")
    print(f"[MJPEG] 话题: {args.topic}  质量: {args.quality}")
    print("[MJPEG] Ctrl+C 停止")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.shutdown()
        rclpy.shutdown()


if __name__ == "__main__":
    main()
