#!/usr/bin/env python3
import argparse
import select
import sys
import termios
import time
import tty

import rclpy
from geometry_msgs.msg import Twist
from rclpy.node import Node


KEYMAP = {
    "w": (1.0, 0.0),
    "s": (-1.0, 0.0),
    "a": (0.0, 1.0),
    "d": (0.0, -1.0),
    "UP": (1.0, 0.0),
    "DOWN": (-1.0, 0.0),
    "LEFT": (0.0, 1.0),
    "RIGHT": (0.0, -1.0),
}


class KeyboardControl(Node):
    def __init__(self, topic: str):
        super().__init__("keyboard_control")
        self.pub = self.create_publisher(Twist, topic, 10)

    def publish_cmd(self, linear: float, angular: float):
        msg = Twist()
        msg.linear.x = float(linear)
        msg.angular.z = float(angular)
        self.pub.publish(msg)


def read_key(timeout: float):
    ready, _, _ = select.select([sys.stdin], [], [], timeout)
    if not ready:
        return None

    ch = sys.stdin.read(1)
    if ch == "\x1b":
        ready, _, _ = select.select([sys.stdin], [], [], 0.02)
        if not ready:
            return "ESC"
        suffix = sys.stdin.read(2)
        return {
            "[A": "UP",
            "[B": "DOWN",
            "[C": "RIGHT",
            "[D": "LEFT",
        }.get(suffix, "ESC")
    return ch


def print_help(topic: str, linear: float, angular: float, deadman: float):
    print("")
    print("campusCar keyboard control")
    print(f"topic: {topic}")
    print("")
    print("  w / ↑     forward")
    print("  s / ↓     backward")
    print("  a / ←     turn left")
    print("  d / →     turn right")
    print("  space/x   stop")
    print("  r/f       linear speed up/down")
    print("  t/g       angular speed up/down")
    print("  q         quit")
    print("")
    print(f"hold a motion key to keep moving; timeout stop: {deadman:.1f}s")
    print(f"linear={linear:.2f} m/s angular={angular:.2f} rad/s")
    print("")


def main():
    parser = argparse.ArgumentParser(description="Terminal keyboard control for campusCar")
    parser.add_argument("--topic", default="/cmd_vel")
    parser.add_argument("--linear", type=float, default=0.3)
    parser.add_argument("--angular", type=float, default=0.5)
    parser.add_argument("--linear-step", type=float, default=0.05)
    parser.add_argument("--angular-step", type=float, default=0.05)
    parser.add_argument("--max-linear", type=float, default=1.0)
    parser.add_argument("--max-angular", type=float, default=1.0)
    parser.add_argument("--rate", type=float, default=10.0)
    parser.add_argument("--deadman", type=float, default=0.45)
    args = parser.parse_args()

    if not sys.stdin.isatty():
        raise SystemExit("keyboard_control.py must run in an interactive terminal")

    rclpy.init()
    node = KeyboardControl(args.topic)

    linear_speed = max(0.0, min(args.max_linear, args.linear))
    angular_speed = max(0.0, min(args.max_angular, args.angular))
    linear = 0.0
    angular = 0.0
    last_motion_key = 0.0
    period = 1.0 / max(args.rate, 1.0)

    settings = termios.tcgetattr(sys.stdin)
    print_help(args.topic, linear_speed, angular_speed, args.deadman)

    try:
        tty.setcbreak(sys.stdin.fileno())
        while rclpy.ok():
            key = read_key(period)
            now = time.monotonic()

            if key:
                key = key.lower() if len(key) == 1 else key
                if key == "q":
                    break
                if key in (" ", "x"):
                    linear = 0.0
                    angular = 0.0
                    last_motion_key = 0.0
                elif key == "r":
                    linear_speed = min(args.max_linear, linear_speed + args.linear_step)
                elif key == "f":
                    linear_speed = max(0.0, linear_speed - args.linear_step)
                elif key == "t":
                    angular_speed = min(args.max_angular, angular_speed + args.angular_step)
                elif key == "g":
                    angular_speed = max(0.0, angular_speed - args.angular_step)
                elif key in KEYMAP:
                    lin_scale, ang_scale = KEYMAP[key]
                    linear = lin_scale * linear_speed
                    angular = ang_scale * angular_speed
                    last_motion_key = now

            if last_motion_key and now - last_motion_key > args.deadman:
                linear = 0.0
                angular = 0.0

            node.publish_cmd(linear, angular)
            print(
                f"\rlinear={linear:+.2f} angular={angular:+.2f} "
                f"base=({linear_speed:.2f}, {angular_speed:.2f})   ",
                end="",
                flush=True,
            )
    except KeyboardInterrupt:
        pass
    finally:
        termios.tcsetattr(sys.stdin, termios.TCSADRAIN, settings)
        for _ in range(5):
            node.publish_cmd(0.0, 0.0)
            time.sleep(0.03)
        node.destroy_node()
        rclpy.shutdown()
        print("\nkeyboard control stopped")


if __name__ == "__main__":
    main()
