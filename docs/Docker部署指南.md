# Docker 部署指南

## 目标

当前分支是新底盘专用分支。Docker 只负责隔离 ROS2 Humble、apt 依赖、Python 依赖和项目运行环境；宿主机仍负责真实硬件连接：

- STM32 前/后驱动器 USB/TTL 串口、`dialout` 权限、udev 规则
- Hikrobot GigE 相机网口、PoE/外部供电、同网段 IP
- RTK USB 串口
- 外部急停、供电和安全接线

本分支唯一默认 profile 是：

| 底盘 | Profile | 脚本 | Compose |
|------|---------|------|---------|
| STM32 双 UART 4WD / Hikrobot | `stm32_hoverboard_4wd` | `./scripts/docker_run_stm32.sh` | `docker/compose.stm32_hoverboard.yml` |

旧底盘入口、旧底盘 profile 和旧底盘 compose 已从这个分支移除。不要在这个分支里恢复 `campus_car` 或旧 Orbbec/Orange-Pi 路径。

## 构建镜像

如果宿主机还没有 Docker：

```bash
cd ~/campusCar-new-chassis
./scripts/install_docker.sh
```

这个脚本会通过 apt 安装 `docker.io`、Docker Buildx、Docker Compose v2，启动 Docker 服务，把当前用户加入 `docker` 组，并构建 `campuscar:humble` 镜像。当前 shell 如果还没有刷新组权限，先运行：

```bash
newgrp docker
```

如果 Docker 已经装好，只构建镜像：

```bash
./scripts/docker_build.sh
```

如果 Docker Hub 拉取 `ros:humble-ros-base-jammy` 失败，用当前已验证可用的镜像源：

```bash
./scripts/docker_build.sh \
  --base-image docker.m.daocloud.io/library/ros:humble-ros-base-jammy
```

镜像里已经安装 ROS2 Humble、rosbridge、RTK、视频、Aravis/Hikrobot、`ros2_control`、`diff_drive_controller`、`controller_manager`、`camera_aravis2` 和 `mediamtx`。源码工作区仍挂载当前仓库，所以 `hoverboard_ws/` 构建产物会落在项目目录下，并由 `.gitignore` 排除。

## 新底盘容器

打开新底盘隔离 shell：

```bash
./scripts/docker_run_stm32.sh
```

容器内默认就是：

```bash
ROBOT_PROFILE=stm32_hoverboard_4wd
CAMPUSCAR_CHASSIS_ISOLATION=stm32_hoverboard
```

首次进入后构建项目内 `hoverboard_driver`：

```bash
./scripts/deploy_dependencies.sh --skip-apt --skip-mediamtx
```

底盘到货后先探测，不要直接启动：

```bash
./scripts/stm32_hoverboard_probe.sh
```

如果两个 TTL 设备不是 `/dev/ttyUSB0` 和 `/dev/ttyUSB1`，在宿主机项目里写本地覆盖：

```bash
cat > config/profiles/stm32_hoverboard_4wd.local.env <<'EOF'
HOVERBOARD_FRONT_DEVICE="/dev/serial/by-id/<front-driver>"
HOVERBOARD_REAR_DEVICE="/dev/serial/by-id/<rear-driver>"
EOF
```

确认轮子架空、急停可用、串口对应关系正确后再启动：

```bash
./scripts/launch_all.sh
```

也可以从宿主机直接执行单条命令：

```bash
./scripts/docker_run_stm32.sh -- ./scripts/stm32_hoverboard_probe.sh
./scripts/docker_run_stm32.sh -- ./scripts/check_all.sh
```

## Compose 入口

```bash
docker compose -f docker/compose.stm32_hoverboard.yml run --rm campuscar-stm32-hoverboard
```

compose 文件和脚本默认都挂载 `/dev` 并使用 `--privileged`，这是为了兼容动态 USB 串口、RTK USB 和工业相机调试。需要做无硬件文档/代码检查时，用脚本的 `--no-devices`：

```bash
./scripts/docker_run_stm32.sh --no-devices -- ./scripts/stm32_hoverboard_probe.sh
```

## 常见问题

- 找不到 Docker 镜像：先运行 `./scripts/docker_build.sh`，或运行 wrapper 时加 `--build`。
- GUI 不显示：确认宿主机允许 X11 本地连接，必要时先执行 `xhost +local:docker`。
- 容器里找不到串口：先在宿主机确认 `/dev/ttyUSB*` 或 `/dev/serial/by-id/*` 存在，再确认 wrapper 没有使用 `--no-devices`。
- ROS2 topic 看不到：Docker 必须使用 host network；不要改成 bridge network。
- `launch_all.sh` 找不到串口会直接停止，这是新底盘专用分支的安全行为；无硬件检查用 `stm32_hoverboard_probe.sh`。
