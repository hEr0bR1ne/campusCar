"""Connection monitoring utility - centralized, reusable connection checking"""
import socket
import time
import datetime

class ConnectionMonitor:
    """Unified connection monitor for the rosbridge port"""

    def __init__(self, host="127.0.0.1", port=9090):
        self.host = host
        self.port = port
        self.last_cmd_time = None

    def record_activity(self):
        """Record that activity (command) was received"""
        self.last_cmd_time = time.time()

    def get_status(self):
        """
        Get current connection status.
        Returns: (status_text, color_code)
        """
        if not self._can_connect():
            return "❌ 无法连接 (rosbridge未运行)", "\033[91m"

        current_time = time.time()

        if self.last_cmd_time is None:
            return "⏳ 等待UE数据", "\033[94m"

        elapsed = current_time - self.last_cmd_time

        if elapsed < 30:
            return "✓ 已连接 (活跃)", "\033[92m"
        elif elapsed < 60:
            return "✓ 已连接 (空闲)", "\033[93m"
        elif elapsed < 300:
            return "✗ 连接超时 - UE无响应", "\033[91m"
        else:
            return "✗ 长时间无数据", "\033[91m"

    def print_status(self):
        """Print formatted connection status"""
        status_text, color = self.get_status()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        status_line = f"[{timestamp}] UE连接状态: {color}{status_text}\033[0m"
        print(status_line, flush=True)

    def _can_connect(self):
        """Check if can establish a socket connection to rosbridge"""
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(2)
            sock.connect((self.host, self.port))
            sock.close()
            return True
        except Exception:
            return False

    def print_error(self, msg: str):
        """Print error message"""
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        print(f"\033[91m[{timestamp}] ❌ {msg}\033[0m", flush=True)


__all__ = ['ConnectionMonitor']
