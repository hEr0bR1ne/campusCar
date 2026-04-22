import rclpy
from rclpy.node import Node
from geometry_msgs.msg import Twist
import time

class MoveNode(Node):
    def __init__(self):
        super().__init__('move_node')
        self.pub = self.create_publisher(Twist, '/cmd_vel', 10)

    def move(self, linear=0.0, angular=0.0):
        msg = Twist()
        msg.linear.x = linear
        msg.angular.z = angular
        self.pub.publish(msg)

    def stop(self):
        self.move(0.0, 0.0)

def main():
    rclpy.init()
    node = MoveNode()

    # 前进 2 秒
    node.move(linear=0.3)
    time.sleep(2)

    # 停止
    node.stop()
    time.sleep(0.5)

    node.destroy_node()
    rclpy.shutdown()

if __name__ == '__main__':
    main()
