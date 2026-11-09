# 大肥鱼：从 ESP32-WROOM-32 迁移到 ESP32-S3-N16R8

> 状态：迁移设计与 Codex 交接说明 v0.1；不是已编译、已烧录或已实机验收的 S3 固件。  
> 基线：仓库 main 分支现有 WROOM-32 语音工作台。  
> 目标：先争取单 ESP32-S3 完成摄像头、音频收发和双轮运动控制；如果实测 GPIO 或实时任务确实不够，再拆成双板。

## 1. 现有系统：必须保留的已验证成果

当前仓库已经实现并经过真实硬件对话验证：

- ESP32-WROOM-32 + INMP441 + MAX98357A + 喇叭。
- ESP32 通过 Wi-Fi 自动发现电脑，连接 WebSocket /audio。
- 电脑端 FastAPI、React/TypeScript、SQLite。
- Paraformer ASR、LLM、VoxCPM2 TTS。
- 麦克风上传协议：16 kHz、单声道、PCM16LE。
- TTS 下发协议：48 kHz、单声道、PCM16LE。
- 播放完成后设备回传 played，后端才恢复收音。

关键代码位置：
- firmware/main/audio_io.c
- firmware/main/network.c
- firmware/main/diagnostics.c
- server/main.py
- server/protocol.py
- server/studio_app.py
- server/studio_runtime.py

现有音频引脚（仅 WROOM-32，不能照搬到 S3）：

| 外设 | 当前 GPIO |
|---|---|
| INMP441 SCK / WS / SD | 26 / 25 / 34 |
| MAX98357A BCLK / LRC / DIN | 27 / 14 / 22 |

当前固件使用 ESP-IDF 5.3.4、4 MB Flash。firmware/sdkconfig.defaults、scripts/build_firmware.py、scripts/flash_firmware.py 均以经典 ESP32 为目标。旧烧录脚本使用 --chip esp32 并只备份 4 MB。

## 2. 迁移原则

1. 不破坏当前 WROOM-32 固件和它的预编译演示镜像。
2. 不把 S3 的 16 MB Flash 当成旧固件 4 MB Flash 使用。
3. 不把相似 CAM 板的参考 pin map 当成已验证的泰斯凯 PCB pin map。
4. 电脑端 ASR、LLM、VoxCPM2、YOLO 都继续运行在当前 RTX 4060 Ti 16 GB 主机；本次不引入第二台计算机或 MQTT。
5. S3 负责外设采集、音频收发、图像上传和电机执行；电脑继续负责 AI 推理与调度。
6. 保持后端音频协议不变：16 kHz 上行、48 kHz 下行。
7. 先完成无电机的摄像头与音频验收，再接电机，最后装入外壳。

## 3. 固件目录策略

不要直接把现有 firmware/ 改成 esp32s3，否则旧 WROOM 设备无法复现。

建议新增独立目标：

- firmware/：保留现有经典 ESP32-WROOM-32。
- firmware_s3/：新增 ESP32-S3-N16R8 目标。
- scripts/build_firmware_s3.py：独立 S3 构建。
- scripts/flash_firmware_s3.py：独立 S3 烧录和备份。

S3 工程配置至少需要：
- CONFIG_IDF_TARGET="esp32s3"
- 16 MB Flash。
- 8 MB Octal PSRAM，启用 OPI PSRAM。
- 按所选摄像头驱动配置相应组件和帧缓冲。
- 独立的 S3 预编译产物目录。

S3 烧录脚本必须识别 esp32s3，备份并校验完整 16 MB Flash。**禁止使用现有 WROOM 的 4 MB flash_firmware.py 对 S3 进行备份或烧录。**

## 4. 单 S3 候选引脚规划（必须先核对板级版本）

以 larryli ESP32-S3-CAM / Freenove 类布局作为参考，候选规划如下：

### 4.1 摄像头

| 信号 | GPIO |
|---|---:|
| SIOD / SDA | 4 |
| SIOC / SCL | 5 |
| VSYNC | 6 |
| HREF | 7 |
| PCLK | 13 |
| XCLK | 15 |
| D0–D7 | 11、9、8、10、12、18、17、16 |

### 4.2 音频：建议评估 I²S 全双工 48 kHz

| 信号 | 候选 GPIO | 连接 |
|---|---:|---|
| BCLK | 41 | INMP441 SCK + MAX98357A BCLK 共用 |
| WS / LRCLK | 42 | INMP441 WS + MAX98357A LRC 共用 |
| DIN | 1 | INMP441 SD → S3 |
| DOUT | 14 | S3 → MAX98357A DIN |

原因：ESP-IDF 标准 I²S 全双工可以让 TX/RX 共用 BCLK 和 WS，但配对通道必须使用相同帧时序。现有系统 RX 16 kHz、TX 48 kHz，不能直接共用时钟。

候选改法：
1. S3 I²S TX/RX 均使用 48 kHz、32-bit stereo。
2. INMP441 以 48 kHz 采集。
3. S3 对麦克风采样进行抗混叠低通滤波和 3:1 降采样，形成现有后端需要的 16 kHz PCM16。
4. MAX98357A 继续播放 48 kHz PCM16。
5. 上行/下行 WebSocket 协议仍保持 16 kHz / 48 kHz，不要求重写 ASR/TTS 后端。

这是减少 GPIO 的首选方案，但必须测试 I²S 时钟、电平、音质和连续播放稳定性。若全双工方案不稳定，再评估双 I²S 控制器的独立时钟方案；独立 16 kHz RX + 48 kHz TX 会多占 BCLK/WS GPIO。

### 4.3 电机：优先评估 DRV8833 四输入方案

| 信号 | 候选 GPIO | 说明 |
|---|---:|---|
| 左电机 IN1 | 38 | PWM/方向输入 |
| 左电机 IN2 | 39 | PWM/方向输入 |
| 右电机 IN1 | 40 | PWM/方向输入 |
| 右电机 IN2 | 47 | PWM/方向输入 |
| nSLEEP | 21 | 驱动使能；也可评估硬件上拉 + 输入下拉的安全方案 |

DRV8833 用两组 H-bridge 控制两个直流电机，四个输入脚即可完成方向与 PWM 控制。TI 数据手册给出的电流能力依封装而异；PWP/RTY 封装标称每桥 1.5 A RMS、2 A peak，模块 PCB 散热会进一步影响持续能力。

**必须先拿到电机堵转电流，再决定 DRV8833 是否合适。** 若电机堵转电流超过驱动模块的额定范围，换更高电流驱动器，不得只因 GPIO 方案方便而硬用 DRV8833。

### 4.4 GPIO 候选映射汇总

| GPIO | 候选功能 |
|---:|---|
| 1、14、41、42 | I²S 全双工音频 |
| 38、39、40、47、21 | DRV8833 电机控制 |
| 4、5、6、7、8–13、15–18 | OV2640 摄像头 |
| 35–37 | Octal PSRAM，禁止使用 |
| 19、20 | 原生 USB，保留 |
| 43、44 | 常见 USB-UART 桥接，保留 |
| 38–40 | 参考板上连 microSD；本项目不用 SD，但须确认板级电路允许复用 |
| 2、48 | 参考板上 LED，优先保留 |

这是一份**候选设计表**，不是最终接线表。GPIO14、21、47 及 SD 插槽相关引脚必须与用户实际 PCB 核对。

## 5. 摄像头数据链路

本项目不使用 SD 卡。摄像头数据仅实时传给电脑。

建议 S3 固件提供：
- GET /camera/snapshot：返回一张 JPEG。
- GET /camera/stream：返回 MJPEG 流（若采用 MJPEG）。
- 相机状态与帧率诊断接口。

初始设置：
- OV2640。
- JPEG。
- 640×480。
- 先以 5–10 FPS 验证。
- 帧缓冲放 PSRAM。
- 优先级：音频 > 电机安全控制 > 视频帧率。

电脑端新增独立 VisionService：
- 从 S3 获取 JPEG。
- RTX 4060 Ti 16 GB 上运行已选 YOLO 模型。
- 将检测结果、目标框、时间戳和原图转发到现有 React 工作台。
- 用户说“看看前面有什么”时由 LLM 触发按需检测；后续再加持续检测/跟踪。

第一阶段不引入 MQTT。当前是一台 AI 电脑，先使用现有 FastAPI 内部任务/事件机制即可。

## 6. 运动控制链路

建议电脑端提供机器人运动 API，复用现有 FastAPI 工作台；固件接收运动命令并输出 PWM/方向控制。

命令至少包括：
- stop
- forward
- backward
- turn_left
- turn_right
- set_wheels(left, right)

安全要求：
- 每条运动命令带有效期，初始建议 300 ms；超时自动停止。
- Wi-Fi 断开、后端进程退出、固件重启、命令解析异常时，电机默认停止。
- 上电时驱动器默认禁止运动。
- 先限速、架空轮子测试，再落地测试。
- 电机供电与 S3/麦克风电源分路稳压、共地；电机电流不得经过 S3 供电走线。
- 初版无编码器时只能开环控制；后续若加入双通道编码器，每个电机两路脉冲会额外占用 4 个 GPIO，需要重新规划或增加外部计数/控制器。

## 7. 迁移验收阶段

| 阶段 | 任务 | 验收标准 |
|---|---|---|
| S0 | 确认实际板版本、背面照片、摄像头 GPIO | pin map 冻结；无猜测引脚 |
| S1 | S3 最小工程启动、Wi-Fi、PSRAM | 识别 esp32s3；16 MB Flash；8 MB PSRAM 可用 |
| S2 | OV2640 单帧 JPEG | 稳定获取图像，PSRAM 帧缓存工作 |
| S3 | 摄像头 Wi-Fi 流 | 电脑连续收图，丢帧/延迟可观测 |
| S4 | INMP441 + MAX98357A | 保持 16 kHz 上行、48 kHz 下行协议 |
| S5 | 接入现有 FastAPI/ASR/LLM/VoxCPM2 | 真实语音对话成功，旧后端不重写 |
| S6 | 接入电机驱动 | 架空轮子正反转、PWM、急停、断网停机 |
| S7 | 整机同时运行 | 视频、语音、运动不互相造成复位或严重丢包 |
| S8 | 安装到底盘和外壳 | 重心、线束、散热、USB 可维护性合格 |

## 8. 当前不能宣称已完成的事项

- 尚未对用户实际泰斯凯板完成背面核对。
- 尚未冻结最终 GPIO。
- 尚未把 WROOM 固件编译成 S3 固件。
- 尚未验证 INMP441/MAX98357A 在同一 48 kHz I²S 时钟下的真实效果。
- 尚未选择最终电机与驱动器。
- 尚未验证电机启动噪声不会导致音频断流或 S3 复位。
- 尚未把摄像头流和 YOLO 接入现有网页。

完成这些实测后再更新本文件状态，不得把设计方案标记为“已实现”。
