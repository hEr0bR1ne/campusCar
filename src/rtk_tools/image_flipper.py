#!/usr/bin/env python3
"""
图像翻转节点
将 /camera/color/image_raw 180度翻转后发布到 /camera/color/image_flipped
"""
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import Image
import numpy as np


class ImageFlipper(Node):
    def __init__(self):
        super().__init__('image_flipper')
        self.pub = self.create_publisher(Image, '/camera/color/image_flipped', 10)
        self.sub = self.create_subscription(Image, '/camera/color/image_raw', self.cb, 10)
        self.get_logger().info('图像翻转节点已启动')
        self.get_logger().info('  输入: /camera/color/image_raw')
        self.get_logger().info('  输出: /camera/color/image_flipped')

    def cb(self, msg):
        arr = np.frombuffer(msg.data, np.uint8).reshape(msg.height, msg.width, -1).copy()
        msg.data = arr.tobytes()
        self.pub.publish(msg)


def main():
    rclpy.init()
    node = ImageFlipper()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == '__main__':
    main()
