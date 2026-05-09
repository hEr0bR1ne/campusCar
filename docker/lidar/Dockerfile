# ============================================================
# campusCar 激光雷达驱动容器
# 激光雷达型号：Livox Mid360（以太网 UDP 连接）
# 功能：运行 livox_ros_driver2 + pointcloud_to_laserscan
#       发布 /livox/lidar (PointCloud2) 和 /scan (LaserScan)
# ============================================================
FROM osrf/ros:humble-ros-base

# 安装构建工具和 Livox SDK2 依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    cmake \
    build-essential \
    git \
    wget \
    python3-colcon-common-extensions \
    && rm -rf /var/lib/apt/lists/*

# 安装 Livox SDK2（livox_ros_driver2 的底层依赖）
RUN git clone https://github.com/Livox-SDK/Livox-SDK2.git /tmp/Livox-SDK2 \
    && cd /tmp/Livox-SDK2 \
    && mkdir build && cd build \
    && cmake .. -DCMAKE_BUILD_TYPE=Release \
    && make -j$(nproc) \
    && make install \
    && ldconfig \
    && rm -rf /tmp/Livox-SDK2

# 安装 ROS2 驱动包和点云转换节点
RUN apt-get update && apt-get install -y --no-install-recommends \
    ros-humble-livox-ros-driver2 \
    ros-humble-pointcloud-to-laserscan \
    ros-humble-tf2-ros \
    ros-humble-tf2-geometry-msgs \
    && rm -rf /var/lib/apt/lists/*

# 创建工作目录
RUN mkdir -p /campuscar_lidar/config

# 复制配置文件
COPY config/ /campuscar_lidar/config/

# 复制并设置启动脚本
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

WORKDIR /campuscar_lidar

ENTRYPOINT ["/entrypoint.sh"]
