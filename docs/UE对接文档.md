# UE5 ↔ 小车 对接文档

> 面向 UE 负责人，说明视频流接入方式和指令格式。

---

## 一、视频流接入

### 推荐方式：HLS（稳定，UE Electra Player 首选）

| 用途 | 地址 |
|------|------|
| UE Electra Player | `http://192.168.100.1:8888/robot_cam/index.m3u8` |
| 浏览器预览验证 | `http://192.168.100.1:8888/robot_cam/` |
| MJPEG 备用预览 | `http://192.168.100.1:8080/` |

### 备用方式：RTSP（仅调试用）

```
rtsp://192.168.100.1:8554/robot_cam
```

> 注意：RTSP 在 Windows/UE 环境下兼容性差，不建议作为正式接入方式。
> 历史排查中曾误用 `8854` 端口，**正确端口是 `8554`**。

### 验证步骤

1. 用浏览器打开 `http://192.168.100.1:8888/robot_cam/`
2. 能看到画面说明服务正常
3. 再让 Electra Player 接 `index.m3u8`

---

## 二、指令控制接入

### 连接方式

- 协议：rosbridge TCP/BSON（兼容 UE 信息收发测试器）
- 地址：`tcp://192.168.100.1:9090`
- 发指令话题：`/U2RTopic_Command`（消息类型 `std_msgs/String`）
- 接收回复话题：`/R2UTopic_Text`（消息类型 `std_msgs/String`）

---

### 指令格式

所有指令统一为以下 JSON 结构：

```json
{
  "commandId": "010",
  "commandType": "move",
  "RobotId": "Robot",
  "RobotType": " ",
  "commandParams": {
    "destination": <见下方>,
    "speed": "30"
  }
}
```

`speed` 为字符串，范围 `"0"` ~ `"100"`，对应 0 ~ 1.0 m/s。

通过 rosbridge TCP/BSON 发布时，外层使用 rosbridge 的 `publish` 包装，内层 `msg.data` 放上面的指令 JSON 字符串：

```json
{
  "op": "publish",
  "topic": "/U2RTopic_Command",
  "msg": {
    "data": "{\"commandId\":\"010\",\"commandType\":\"move\",\"RobotId\":\"Robot\",\"RobotType\":\" \",\"commandParams\":{\"destination\":\"Forward\",\"speed\":\"30\"}}"
  }
}
```

---

### 方向控制

`destination` 为字符串：

| destination | 动作 |
|-------------|------|
| `"Forward"` | 前进 |
| `"TurnBackward"` | 后退 |
| `"TurnLeft"` | 左转 |
| `"TurnRight"` | 右转 |

示例：

```json
{"commandId":"010","commandType":"move","RobotId":"Robot","RobotType":" ","commandParams":{"destination":"Forward","speed":"30"}}
{"commandId":"010","commandType":"move","RobotId":"Robot","RobotType":" ","commandParams":{"destination":"TurnLeft","speed":"30"}}
{"commandId":"010","commandType":"move","RobotId":"Robot","RobotType":" ","commandParams":{"destination":"TurnRight","speed":"30"}}
{"commandId":"010","commandType":"move","RobotId":"Robot","RobotType":" ","commandParams":{"destination":"TurnBackward","speed":"30"}}
```

> 方向控制现在由 NUC 端桥接节点持续补发 `/cmd_vel`，UE 发一次指令后默认最多保持 `UE_DIRECTION_TIMEOUT_SEC=0.8` 秒。`TurnLeft`/`TurnRight` 会发送零线速度原地转向指令；行进中转向仍由 UE 连续发送前进/后退与转向组合逻辑实现。按键长按/连续动作时，UE 建议按 5~10Hz 重复发送同一个指令；松开时发送任意方向配合 `speed: "0"`，或发送 `destination: "Stop"` 停车。

---

### 坐标导航

`destination` 为坐标对象。UE JSON 格式不需要变，默认按 x=经度、y=纬度处理：

```json
{
  "commandId": "010",
  "commandType": "move",
  "RobotId": "Robot",
  "RobotType": " ",
  "commandParams": {
    "destination": {"x": 113.123456, "y": 22.654321},
    "speed": "30"
  }
}
```

小车到达目标点后，会向 `/R2UTopic_Text` 回复：

```json
{"commandId": "010", "RobotId": "Robot", "status": "arrived"}
```

> 新的导航指令会自动取消上一个未完成的导航任务。

---

### 小车状态回传

NUC 会在 `/R2UTopic_Pos` 上按 `UE_PUBLISH_RATE` 固定频率发送 `std_msgs/String` JSON。原有 RTK 字段保持不变，并额外追加 `vehicle` 对象，UE 可以和 RTK 位置一起读取车体朝向、速度、角速度、加速度：

```json
{
  "status": 2,
  "status_name": "PPS_FIX",
  "latitude": 22.65432100,
  "longitude": 113.12345600,
  "altitude": 12.3,
  "timestamp": 1777355686.91,
  "frame_id": "gps",
  "vehicle": {
    "heading_source": "imu",
    "yaw_rad": -1.82,
    "yaw_deg": 255.7,
    "speed_mps": 0.18,
    "linear_velocity": {"x": 0.18, "y": 0.0, "z": 0.0},
    "angular_velocity": {"x": 0.0, "y": -0.001, "z": -0.002},
    "linear_acceleration": {"x": 0.06, "y": 0.11, "z": 9.79},
    "imu_age_sec": 0.02,
    "odom_age_sec": 0.02,
    "imu_frame_id": "imu",
    "odom_frame_id": "odom",
    "odom_child_frame_id": "base_footprint",
    "imu_timestamp": 1777355686.91,
    "odom_timestamp": 1777355686.91
  }
}
```

字段说明：

| 字段 | 来源 | 说明 |
|------|------|------|
| `vehicle.heading_source` | `/imu` 或 `/odom` | 当前 yaw 优先取 IMU；IMU 不新鲜时回退 odom |
| `vehicle.yaw_deg` / `yaw_rad` | `/imu.orientation` 优先 | ENU 坐标系，0° 为东，90° 为北 |
| `vehicle.speed_mps` | `/odom.twist` | 底盘估计线速度模长 |
| `vehicle.linear_velocity` | `/odom.twist.twist.linear` | odom 线速度分量 |
| `vehicle.angular_velocity` | `/imu.angular_velocity` 优先 | 车体角速度，尤其 `z` 可看转向速率 |
| `vehicle.linear_acceleration` | `/imu.linear_acceleration` | 车体加速度，静止时 `z` 约为重力加速度 |
| `vehicle.imu_age_sec` / `odom_age_sec` | NUC 接收时间 | 数值越小表示数据越新 |

旧 UE 逻辑如果只解析 `latitude/longitude/altitude` 可以忽略 `vehicle`；新 UE 逻辑建议先判断字段是否为 `null`，再用于显示或动画。

如果 UE 发的是场景坐标，而不是 WGS84 经纬度，也保持同一个 JSON 格式，只在 NUC 的 `config/robot.env` 或当前 `config/profiles/<profile>.env` 配置坐标转换：

```bash
UE_COORD_MODE=local
UE_LOCAL_ORIGIN_LAT=22.00000000
UE_LOCAL_ORIGIN_LON=113.00000000
UE_LOCAL_ORIGIN_X=0
UE_LOCAL_ORIGIN_Y=0
UE_UNITS_PER_METER=100
UE_LOCAL_ROTATION_DEG=0
UE_LOCAL_X_SIGN=1
UE_LOCAL_Y_SIGN=1
```

含义：`UE_LOCAL_ORIGIN_X/Y` 是 UE 场景里的锚点，`UE_LOCAL_ORIGIN_LAT/LON` 是该锚点对应的真实 RTK 坐标；`UE_UNITS_PER_METER=100` 表示 UE 默认厘米单位；`UE_LOCAL_ROTATION_DEG` 表示 UE +X 轴相对真实正东的逆时针角度，轴方向相反时把对应 `SIGN` 改成 `-1`。

---

## 三、防火墙端口确认

确保以下端口对 UE 机器可达：

| 端口 | 用途 |
|------|------|
| `8554/tcp` | RTSP（调试） |
| `8888/tcp` | HLS（UE 接入） |
| `8080/tcp` | MJPEG 预览（可选） |
| `9090/tcp` | rosbridge TCP/BSON（指令控制） |
