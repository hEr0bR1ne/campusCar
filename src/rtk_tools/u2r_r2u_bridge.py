#!/usr/bin/env python3
"""
UE↔RTK Bridge - ROS2 Node Entry Point
Forwards GNSS data from /fix to /R2UTopic_Pos, listens for UE commands on /U2RTopic_Command
"""

import sys
import argparse
from pathlib import Path
import rclpy
from rclpy.executors import ExternalShutdownException

# Add parent dir to path for config imports
sys.path.insert(0, str(Path(__file__).parent))

from config import (TOPIC_FIX_IN, TOPIC_IMU_IN, TOPIC_ODOM_IN,
                    TOPIC_POS_OUT, TOPIC_CMD_IN, TOPIC_IMAGE_IN,
                    TOPIC_IMAGE_OUT, TOPIC_TEXT_OUT)
from core.bridge import RTKUEBridge


def main():
    parser = argparse.ArgumentParser(description="UE↔RTK Bridge Node")
    parser.add_argument("--fix-in", default=TOPIC_FIX_IN, help=f"Input fix topic (default: {TOPIC_FIX_IN})")
    parser.add_argument("--imu-in", default=TOPIC_IMU_IN, help=f"Input IMU topic (default: {TOPIC_IMU_IN})")
    parser.add_argument("--odom-in", default=TOPIC_ODOM_IN, help=f"Input odometry topic (default: {TOPIC_ODOM_IN})")
    parser.add_argument("--pos-out", default=TOPIC_POS_OUT, help=f"Output position topic (default: {TOPIC_POS_OUT})")
    parser.add_argument("--cmd-in", default=TOPIC_CMD_IN, help=f"Input command topic (default: {TOPIC_CMD_IN})")
    parser.add_argument("--image-in", default=TOPIC_IMAGE_IN, help=f"Input image topic (optional, default: {TOPIC_IMAGE_IN})")
    parser.add_argument("--image-out", default=TOPIC_IMAGE_OUT, help=f"Output image topic (default: {TOPIC_IMAGE_OUT})")
    parser.add_argument("--text-out", default=TOPIC_TEXT_OUT, help=f"Output text topic (default: {TOPIC_TEXT_OUT})")
    parser.add_argument("--logfile", default=None, help="Command log file (optional)")
    
    args = parser.parse_args()
    
    rclpy.init()
    
    bridge = RTKUEBridge(
        fix_in=args.fix_in,
        imu_in=args.imu_in,
        odom_in=args.odom_in,
        pos_out=args.pos_out,
        cmd_in=args.cmd_in,
        text_out=args.text_out,
        logfile=args.logfile,
        image_in=args.image_in,
        image_out=args.image_out
    )
    
    try:
        rclpy.spin(bridge)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        bridge.destroy_node()
        try:
            rclpy.shutdown()
        except Exception:
            pass


if __name__ == "__main__":
    main()
