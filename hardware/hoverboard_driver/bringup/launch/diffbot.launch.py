# Copyright 2020 ros2_control Development Team
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.substitutions import Command, FindExecutable, PathJoinSubstitution, LaunchConfiguration

from launch_ros.actions import Node
from launch_ros.substitutions import FindPackageShare


def generate_launch_description():
    # Declare arguments
    declared_arguments = [
        DeclareLaunchArgument(
            "gui",
            default_value="false",
            description="Start RViz2 automatically with this launch file.",
        ),
        DeclareLaunchArgument(
            "front_device",
            default_value="/dev/ttyUSB0",
            description="Front motor driver TTL serial device.",
        ),
        DeclareLaunchArgument(
            "rear_device",
            default_value="/dev/ttyUSB1",
            description="Rear motor driver TTL serial device.",
        ),
        DeclareLaunchArgument(
            "feedback_format",
            default_value="compact",
            description="Serial feedback format: compact for campusCar seller driver, full for hoverboard firmware feedback.",
        ),
        DeclareLaunchArgument(
            "wheel_radius",
            default_value="0.0825",
            description="Wheel radius in meters.",
        ),
        DeclareLaunchArgument(
            "max_velocity",
            default_value="1.0",
            description="Hardware max velocity parameter in m/s.",
        ),
        DeclareLaunchArgument(
            "command_limit_rpm",
            default_value="50",
            description="Clamp serial steer/speed commands to this absolute RPM value.",
        ),
    ]

    # Initialize Arguments
    front_device = LaunchConfiguration("front_device")
    rear_device = LaunchConfiguration("rear_device")
    feedback_format = LaunchConfiguration("feedback_format")
    wheel_radius = LaunchConfiguration("wheel_radius")
    max_velocity = LaunchConfiguration("max_velocity")
    command_limit_rpm = LaunchConfiguration("command_limit_rpm")

    # Get URDF via xacro
    robot_description_content = Command(
        [
            PathJoinSubstitution([FindExecutable(name="xacro")]),
            " ",
            PathJoinSubstitution(
                [FindPackageShare("hoverboard_driver"), "urdf", "diffbot.urdf.xacro"]
            ),
            " ",
            "front_device:=", front_device,
            " ",
            "rear_device:=", rear_device,
            " ",
            "feedback_format:=", feedback_format,
            " ",
            "wheel_radius:=", wheel_radius,
            " ",
            "max_velocity:=", max_velocity,
            " ",
            "command_limit_rpm:=", command_limit_rpm,
        ]
    )
    robot_description = {"robot_description": robot_description_content}

    robot_controllers = PathJoinSubstitution(
        [
            FindPackageShare("hoverboard_driver"),
            "config",
            "hoverboard_controllers.yaml",
        ]
    )
   # rviz_config_file = PathJoinSubstitution(
   #     [FindPackageShare("ros2_control_demo_description"), "diffbot/rviz", "diffbot.rviz"]
   # )

    control_node = Node(
        package="controller_manager",
        executable="ros2_control_node",
        parameters=[robot_description, robot_controllers],
        remappings=[
            ("/hoverboard_base_controller/cmd_vel_unstamped", "/cmd_vel"),
            ("/hoverboard_base_controller/odom", "/odom"),
        ],
        output="both",
    )
    robot_state_pub_node = Node(
        package="robot_state_publisher",
        executable="robot_state_publisher",
        output="both",
        parameters=[robot_description],
    )
    #rviz_node = Node(
    #    package="rviz2",
    #    executable="rviz2",
    #    name="rviz2",
    #    output="log",
    #    arguments=["-d", rviz_config_file],
    #    condition=IfCondition(gui),
    #)

    joint_state_broadcaster_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["joint_state_broadcaster", "--controller-manager", "/controller_manager"],
    )

    robot_controller_spawner = Node(
        package="controller_manager",
        executable="spawner",
        arguments=["hoverboard_base_controller", "--controller-manager", "/controller_manager"],
    )

    # Delay rviz start after `joint_state_broadcaster`
    #delay_rviz_after_joint_state_broadcaster_spawner = RegisterEventHandler(
    #    event_handler=OnProcessExit(
    #        target_action=joint_state_broadcaster_spawner,
    #        on_exit=[rviz_node],
    #    )
    #)

    # Delay start of robot_controller after `joint_state_broadcaster`
    delay_robot_controller_spawner_after_joint_state_broadcaster_spawner = RegisterEventHandler(
        event_handler=OnProcessExit(
            target_action=joint_state_broadcaster_spawner,
            on_exit=[robot_controller_spawner],
        )
    )

    nodes = [
        control_node,
        robot_state_pub_node,
        joint_state_broadcaster_spawner,
       # delay_rviz_after_joint_state_broadcaster_spawner,
        delay_robot_controller_spawner_after_joint_state_broadcaster_spawner,
    ]

    return LaunchDescription(declared_arguments + nodes)
