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

- 协议：rosbridge WebSocket
- 地址：`ws://192.168.100.1:9090`
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

> 方向控制为单次触发，持续运动需持续发送指令。发送 `speed: "0"` 可停车。

---

### 坐标导航

`destination` 为坐标对象，x 为经度，y 为纬度：

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

## 三、防火墙端口确认

确保以下端口对 UE 机器可达：

| 端口 | 用途 |
|------|------|
| `8554/tcp` | RTSP（调试） |
| `8888/tcp` | HLS（UE 接入） |
| `8080/tcp` | MJPEG 预览（可选） |
| `9090/tcp` | rosbridge WebSocket（指令控制） |
