# Livox Mid360 雷达避障开发日志

## 项目背景

campusCar 校园机器人车，在旧底盘（Orange Pi + Orbbec 深度相机）基础上，
新增 Livox Mid360 固态激光雷达，实现前向障碍物检测与自动刹停/减速。

**硬件连接**：Mid360 通过网线直连 NUC 的 USB 转网口 `enx00e04c681c71`。

**工作目录**：`~/campusCar-lidar`，分支 `feature/lidar-obstacle-avoidance`

---

## 技术框架

### 话题流

```
控制节点（web_gui / ue_bridge / car_gui）
    │ /cmd_vel_input
    ▼
obstacle_stopper.py  ←── /scan（LaserScan）
    │ /cmd_vel
    ▼
底盘驱动（base_control_ros2）
```

- 控制节点通过 `CMD_VEL_TOPIC=/cmd_vel_input` 零修改接入仲裁层
- `obstacle_stopper.py` 订阅 `/scan`，前方 ±30° 扇区内有障碍时刹停或减速
- `/scan` 由 Docker 容器内的 `pointcloud_to_laserscan` 从 `/livox/lidar` 转换而来

### Docker 隔离架构

```
宿主机 ROS2 Humble
    │ host network
    ▼
docker/lidar/ 容器（ROS2 Humble + livox_ros_driver2 + pointcloud_to_laserscan）
    ├── livox_ros_driver2  →  /livox/lidar（PointCloud2）
    └── pointcloud_to_laserscan  →  /scan（LaserScan）
```

容器使用 `network_mode: host`，话题直接共享到宿主机 ROS2 域。

### 避障仲裁逻辑（obstacle_stopper.py）

| 条件 | 行为 |
|------|------|
| 前方 ≤ `OBSTACLE_STOP_DIST`（0.5m） | 刹停，发布零速 |
| 前方 ≤ `OBSTACLE_WARN_DIST`（3.0m） | 线性减速 |
| 无障碍 / `/scan` 超时 | 透传原始指令 |
| `OBSTACLE_ENABLED=0` | 完全透传，不干预 |

---

## 网络配置

### 接口规划

| 接口 | NM 连接名 | IP | 用途 |
|------|-----------|-----|------|
| `enp86s0` | `direct-car` | 192.168.100.1/24 | 机器人底盘（不动） |
| `enx00e04c681c71` | `enx00e04c681c71` | 192.168.1.2/24 | **Mid360 雷达网口** |
| `wlo1` | `HKUSTGZ` | 10.12.171.184/22 | Wi-Fi（不动） |

Mid360 出厂 IP：`192.168.1.177`（**已被改为 `192.168.1.193`**，MAC: `88:29:85:49:26:65`）

### 配置命令（已执行，持久化）

```bash
sudo nmcli connection modify "enx00e04c681c71" \
    ipv4.addresses "192.168.1.2/24" \
    ipv4.gateway "" \
    ipv4.route-metric 200
sudo nmcli connection up "enx00e04c681c71"
```

---

## 开发日志

### 2026-05-09

**背景**：Mid360 出厂 IP `192.168.1.177`，雷达网口原 IP `192.168.100.1/24` 与底盘同网段但与雷达不通。

**操作**：
1. `git pull origin feature/lidar-obstacle-avoidance` — 同步远程 13 个新文件（docker/、scripts/lidar_*.sh、src/obstacle_stopper.py 等）
2. `nmcli connection modify "enx00e04c681c71" ipv4.addresses "192.168.1.2/24"` — 修改雷达网口 IP，持久化到 NetworkManager
3. `nmcli connection up "enx00e04c681c71"` — 激活配置
4. 验证：`ip addr show enx00e04c681c71` → `192.168.1.2/24` ✓；`ping 192.168.100.2` → 底盘仍通 ✓
5. `ping 192.168.1.177` → 不通；ping sweep 发现雷达实际 IP 为 `192.168.1.193`（MAC: `88:29:85:49:26:65`），IP 之前被改过
6. 更新 `docker/lidar/config/mid360.json` 和 `config/profiles/old-orange-pi-orbbec-lidar.env`，将雷达 IP 改为 `192.168.1.193`
7. `ping 192.168.1.193` → 全部通，延迟 < 1ms ✓

**待做**：
- [ ] 接上 Mid360 网线并上电，验证 `ping 192.168.1.177` 通
- [ ] 运行 `./scripts/lidar_start.sh` 启动 Docker 容器
- [ ] 检查 `/livox/lidar` 和 `/scan` 话题是否有数据
- [ ] 启动 `obstacle_stopper.py`，测试避障仲裁逻辑
- [ ] 调整 `OBSTACLE_STOP_DIST` / `OBSTACLE_WARN_DIST` 参数

---

*按日期追加，每次重要改动记录在此。*
