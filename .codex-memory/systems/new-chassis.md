# New Chassis System / 新底盘系统

## Scope

- This file is the memory source for the planned new/direct chassis system and hardware-reuse work.
- Target architecture: NUC connects directly to the chassis controller over local UART links.
- Current known chassis controller: STM32-based UART control.
- Active branch for this work: `hardware/new-stm32-hikrobot`.
- Canonical local workspace: `~/campusCar-new-chassis`.
- Branch design: `config/robot.env` defaults to `stm32_hoverboard_4wd`; startup/check/stop/deploy/control scripts accept `--profile NAME` for STM32/Hikrobot variants, but the old chassis profile is removed.

## UART Chassis Facts

- Seller-provided package: `~/campusCar-new-chassis/_forks/hoverboard-driver-humble.zip`.
- Package type: ROS2 Humble `hoverboard_driver` using `ros2_control`, `diff_drive_controller`, and UART hoverboard-style protocol.
- Integrated package source now lives in `hardware/hoverboard_driver`; build output goes to ignored `hoverboard_ws/`.
- Runtime profile: `config/profiles/stm32_hoverboard_4wd.env`.
- Startup script: `scripts/stm32_hoverboard_start.sh`.
- Probe script: `scripts/stm32_hoverboard_probe.sh`.
- Docker isolation entry: `./scripts/docker_run_stm32.sh` or `docker/compose.stm32_hoverboard.yml`, both fixed to `ROBOT_PROFILE=stm32_hoverboard_4wd`.
- Confirmed command protocol from seller reply `~/campusCar-new-chassis/_forks/驱动器控制答疑回复(1).docx`:
  - frame start `0xABCD`
  - signed int16 `steer`
  - signed int16 `speed`
  - unsigned int16 XOR checksum
- Serial electrical/protocol details:
  - 115200 baud
  - 8N1
  - 5V TTL
  - RX/TX/GND
- Actual chassis has front and rear drivers, each controlling two motors.
- Expected serial ports match package defaults:
  - front driver: `/dev/ttyUSB0`
  - rear driver: `/dev/ttyUSB1`
- Seller says `speed` and `steer` are RPM-oriented values.
- Seller says `steer` and `speed` command range is `[-1000, 1000]`.
- Old ROS1 safe maximum was `50`; current driver firmware maximum is `900`.
- The integrated profile/driver defaults to `HOVERBOARD_COMMAND_LIMIT_RPM=50` and clamps serial `steer/speed` before writing.
- Current actual driver has no encoder data, although the TTL feedback reference includes measured right/left RPM, battery voltage, temperature, LED, and checksum every 10 ms.
- The integrated driver defaults to `HOVERBOARD_FEEDBACK_FORMAT=compact` for this no-encoder seller feedback frame. Full hoverboard-firmware-style feedback remains selectable with `HOVERBOARD_FEEDBACK_FORMAT=full`.
- `hoverboard_controllers.yaml` is set to `open_loop: true` and `position_feedback: false` for the no-encoder chassis.
- Compact feedback can still provide measured wheel speed through `speedR_meas` and `speedL_meas`; the driver converts those signed RPM values to rad/s and publishes them through hardware state interfaces and debug `hoverboard/*/velocity` topics.
- True motor encoder position feedback requires the full feedback frame fields `wheelR_cnt` and `wheelL_cnt`; the current seller-confirmed compact feedback does not include those counts.
- When full feedback is available, `hardware/hoverboard_driver/hardware/hoverboard_driver.cpp` calls `on_encoder_update()` with `wheelR_cnt/wheelL_cnt` and updates wheel positions. Until then, wheel position/encoder-based odometry should not be treated as real.
- Emergency stop is currently implemented by cutting/disconnecting the TTL communication/control line, not by a documented serial command.
- Seller did not provide a concrete communication timeout/auto-stop duration; software sends a zero command when the local driver shuts down, but hardware TTL cut/independent e-stop remains required.
- Seller can provide Arduino + PS4 direct TTL control sample; STM32 source is not currently available.

## ROS2 Runtime Dependencies

- Current NUC ROS environment was checked on 2026-04-28 and is missing required `ros2_control` runtime packages:
  - `controller_manager`
  - `diff_drive_controller`
  - `joint_state_broadcaster`
  - `ros2_control`
- Deployment for this system must install those packages before the seller driver can run.
- `scripts/deploy_dependencies.sh --profile stm32_hoverboard_4wd` installs the ROS2 control packages and builds `hardware/hoverboard_driver` into `hoverboard_ws/install`.
- Docker runtime `campuscar:humble` includes the ROS2 control packages, camera Aravis packages, rosbridge, mediamtx, and build tools needed for this profile.
- `hoverboard_driver` builds successfully inside the new STM32 Docker entry after the 2026-04-28 include fix in `hardware/hoverboard_driver/hardware/include/hoverboard_driver/pid.hpp`.
- Container validation command:

```bash
sg docker -c './scripts/docker_run_stm32.sh --no-gui --no-devices -- ./scripts/stm32_hoverboard_probe.sh --profile stm32_hoverboard_4wd'
```

- The probe currently passes all ROS2 dependency checks and finds `hoverboard_driver` at `hoverboard_ws/install/hoverboard_driver`; missing `/dev/ttyUSB0` and `/dev/ttyUSB1` are expected without attached serial adapters or when using `--no-devices`.

## Hardware-Reuse Package

- `~/campusCar-new-chassis` is the package intended to be installed/flashed onto other robot cars for future hardware reuse and migration.
- Treat `~/campusCar-new-chassis` as the canonical new-chassis source; do not put this package or seller materials back under the old `~/campusCar` project.

## New Camera Facts

- Selected camera: Hikrobot/Hikvision industrial camera `MV-CS016-10GC`.
- Camera facts researched on 2026-04-28:
  - color 1.6 MP GigE area-scan camera
  - 1440x1080
  - up to 65.2 fps
  - Sony IMX296 global shutter
  - GigE Vision V2.0 and GenICam compatible
  - powered by 9-24 VDC or PoE
- Vendor support said no ROS-specific materials are provided.
- Recommended ROS2 direction on Humble: try `camera_aravis2` first because the camera is GigE Vision/GenICam compatible.
- Fallback direction: wrap Hikrobot MVS SDK into a ROS2 image publisher if Aravis cannot configure the device reliably.

## Camera Integration

- Camera is integrated directly into the default `config/profiles/stm32_hoverboard_4wd.env` profile.
- Startup script: `scripts/hikrobot_camera_start.sh`.
- Probe script: `scripts/hikrobot_camera_probe.sh`.
- The default profile starts `camera_aravis2 camera_driver_gv` through `scripts/hikrobot_camera_start.sh`.
- The camera start script remaps `/hikrobot_camera/image_raw` to the project `IMAGE_TOPIC`.
- Generated Aravis params are written to `data/logs/hikrobot_aravis_params.yaml`.
- Installed local runtime packages on 2026-04-28:
  - `ros-humble-camera-aravis2`
  - `ros-humble-camera-aravis2-msgs`
  - `aravis-tools`
  - `aravis-tools-cli`
  - `libaravis-0.8-0`
- Probe script currently passes dependency checks and reports no camera connected.

## Open Questions

- Exact deployed STM32 UART behavior still needs on-hardware validation.
- Confirm serial device naming on the target NUC after both front and rear drivers are connected.
- Confirm speed/steer sign convention and safe RPM limits on blocks before moving under load.
- Confirm whether both new cars use the same Hikrobot camera/profile.
