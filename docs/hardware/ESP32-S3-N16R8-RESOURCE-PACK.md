# ESP32-S3-N16R8 资料包（大肥鱼硬件迁移）

> 版本：Research Pack v0.1  
> 状态：已整理公开资料；**尚未对用户准备购买的泰斯凯具体 PCB 版本完成背面核对、原理图核对或实机测量**。  
> 使用原则：以下板级 GPIO 表是相似 ESP32-S3-CAM / Freenove 布局的参考，不得在未核对实际 PCB 前作为最终焊接表。

## 1. N16R8 模组规格

用户目标模组为 **ESP32-S3-WROOM-1-N16R8**：

| 项目 | 原厂规格 | 说明 |
|---|---|---|
| SoC | ESP32-S3，双核 Xtensa LX7，最高 240 MHz | 芯片级能力 |
| Flash | 16 MB Quad SPI | N16 |
| PSRAM | 8 MB Octal SPI | R8；必须启用 OPI PSRAM 配置 |
| Wi-Fi | 2.4 GHz 802.11 b/g/n | 机器人与电脑局域网通信 |
| Bluetooth | Bluetooth LE 5 | 非本项目主通信链路 |
| 外设 | I²S、Camera/LCD_CAM、USB OTG、USB Serial/JTAG、LEDC、MCPWM、PCNT 等 | 可承担音频、摄像头和运动控制 |
| GPIO | 模组最多 36 个 GPIO 引出能力 | 开发板实际可用数量会更少 |
| R8 温度范围 | -40～65 °C | 原厂模组规格 |

原厂资料：
- [ESP32-S3-WROOM-1 / WROOM-1U Datasheet v1.6（PDF）](https://www.espressif.com/sites/default/files/documentation/esp32-s3-wroom-1_wroom-1u_datasheet_en.pdf)
- [ESP32-S3 Technical Reference Manual（PDF）](https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf)

注意：N16R8 表示模组配置，不代表某一个固定开发板型号。不同厂商的摄像头排线、USB 桥接芯片、LED、SD 卡座和 GPIO 引出方式可能不同。

## 2. 已找到的板级参考工程

### 2.1 ESP32-S3-CAM BSP（最值得参考）

- [larryli/esp-idf_esp32_s3_cam](https://github.com/larryli/esp-idf_esp32_s3_cam)
- [硬件说明 hardware.md](https://github.com/larryli/esp-idf_esp32_s3_cam/blob/master/docs/hardware.md)
- [BSP 头文件与 GPIO 定义](https://github.com/larryli/esp-idf_esp32_s3_cam/blob/master/include/bsp/esp32_s3_cam.h)
- [摄像头初始化实现](https://github.com/larryli/esp-idf_esp32_s3_cam/blob/master/src/bsp_camera.c)
- [引脚图](https://github.com/larryli/esp-idf_esp32_s3_cam/blob/master/docs/ESP32S3_Pinout.png)

该工程描述的板子采用 ESP32-S3-N16R8、DVP 摄像头、microSD、GPIO 状态灯、WS2812 和 BOOT 按键。它提供了可阅读的 BSP 和 pin map。

**重要兼容性提醒：** 该 BSP 使用 esp_video，要求 ESP-IDF >= 5.5.2；当前大肥鱼原有固件固定在 ESP-IDF 5.3.4。不能把这个 BSP 原样复制进现有 5.3.4 工程。迁移时应选择兼容的 esp32-camera 组件，或为 S3 单独建立 IDF 5.5.2+ 固件目标。

### 2.2 Freenove ESP32-S3 WROOM CAM 资料

- [Prusa-Firmware-ESP32-Cam：Freenove ESP32-S3 WROOM 文档目录](https://github.com/prusa3d/Prusa-Firmware-ESP32-Cam/tree/master/doc/Freenove%20ESP32-S3-Wroom)
- [Freenove 板级说明](https://github.com/prusa3d/Prusa-Firmware-ESP32-Cam/blob/master/doc/Freenove%20ESP32-S3-Wroom/README.md)
- [Freenove Pinout 图片](https://github.com/prusa3d/Prusa-Firmware-ESP32-Cam/blob/master/doc/Freenove%20ESP32-S3-Wroom/ESP32S3_Pinout.png)

该文档说明板上有 OV2640、microSD、USB-C，并明确写到：作者没有找到完整主板原理图，现有资料主要是 pinout。它可以作为外观和引脚布局参考，但不能据此认定用户的泰斯凯板电路完全相同。

### 2.3 OV2640 摄像头引脚参考

- [jaysys：Freenove ESP32-S3 Cam N16R8 Pin Map](https://github.com/jaysys/esp32s3-with-camera-ov2640-and-sdcard/blob/main/pinmap.md)
- [Espressif 官方 esp32-camera 驱动](https://github.com/espressif/esp32-camera)

esp32-camera 官方驱动支持 ESP32-S3 和 OV2640。OV2640 最高分辨率为 1600×1200，并支持 JPEG 压缩输出。实际无线视频建议先从 VGA 640×480、JPEG、低帧率开始验证。

## 3. 相似 CAM 板的 OV2640 GPIO 映射（候选参考）

下表同时出现在 larryli BSP 与 jaysys 的参考配置中：

| 摄像头信号 | GPIO | 用途 |
|---|---:|---|
| SIOD / SCCB SDA | 4 | 摄像头寄存器控制 |
| SIOC / SCCB SCL | 5 | 摄像头寄存器控制 |
| VSYNC | 6 | 帧同步 |
| HREF | 7 | 行有效 |
| XCLK | 15 | 摄像头主时钟 |
| PCLK | 13 | 像素时钟 |
| D0 | 11 | 图像数据 |
| D1 | 9 | 图像数据 |
| D2 | 8 | 图像数据 |
| D3 | 10 | 图像数据 |
| D4 | 12 | 图像数据 |
| D5 | 18 | 图像数据 |
| D6 | 17 | 图像数据 |
| D7 | 16 | 图像数据 |
| RESET / PWDN | NC / -1 | 参考板上未连接 |

**此表只适用于相同摄像头走线的板子。** 最终必须用用户实际板子的背面丝印、原理图或万用表通断测量确认。

## 4. 相似双 USB-C CAM 板的其他引脚占用参考

| GPIO | 相似板用途 | 对大肥鱼的处理建议 |
|---:|---|---|
| 35、36、37 | N16R8 的 Octal PSRAM | **禁止复用** |
| 19、20 | ESP32-S3 原生 USB D-/D+ | 使用原生 USB 时保留 |
| 43、44 | 常见双 USB-C 板的 UART0 / CH343 桥接 | 保留给串口下载和日志，先不复用 |
| 38、39、40 | 常见板载 microSD 的 CMD、CLK、D0 | 用户不使用 SD；可列为候选 GPIO，但需确认插槽线路与上拉/外围电路 |
| 2 | 某些参考板的状态 LED | 尽量保留 |
| 48 | 某些参考板的 WS2812 RGB LED | 尽量保留 |
| 0、45、46 | 启动/strapping 相关引脚 | 不分配给电机或易产生上电电平的外设 |
| 14 | 部分 Freenove 参考板可接外部 Flash LED | 复用前确认实际板上是否连接 LED/驱动 |
| 21 | 部分参考资料用于工厂复位检测；另一些 BSP 标为可用 GPIO | 复用前核对具体 PCB |

参考板 larryli 的 pin map 还列出 GPIO1、GPIO14、GPIO21、GPIO38、GPIO39、GPIO40、GPIO41、GPIO42、GPIO47 等候选引脚。它们不是对用户实际板子的最终承诺。

## 5. 本项目不使用 microSD

大肥鱼只需要实时视觉，不需要本地录像存储：

1. OV2640 采集 JPEG。
2. ESP32-S3 把图像帧临时放在 8 MB PSRAM。
3. 通过 Wi-Fi 将图像传给电脑。
4. 电脑端 RTX 4060 Ti 16 GB 运行 YOLO，并把检测结果交给现有对话系统和网页。

因此不初始化 SDMMC、不挂载文件系统、不写入 SD 卡。GPIO38/39/40 可列入候选复用清单，但需先核对实际开发板插槽外围电路。

## 6. I²S 全双工：单板方案的关键

现有 WROOM 固件的音频配置是：
- INMP441：I²S RX，16 kHz，独立时钟。
- MAX98357A：I²S TX，48 kHz，独立时钟。

ESP-IDF 的标准 I²S 全双工模式允许同一 I²S 控制器的 TX/RX 共享 BCLK 和 WS；但配对通道必须满足相同帧时序（采样率和每帧总位数一致）。

官方文档：
- [ESP-IDF v5.4 ESP32-S3 I²S 文档](https://docs.espressif.com/projects/esp-idf/en/v5.4/esp32s3/api-reference/peripherals/i2s.html)
- [ESP32-S3 Technical Reference Manual：I²S](https://www.espressif.com/sites/default/files/documentation/esp32-s3_technical_reference_manual_en.pdf)

建议评估的单 I²S 方案：
- INMP441 和 MAX98357A 共用 48 kHz BCLK/WS。
- S3 使用 I²S 全双工 48 kHz、32-bit stereo。
- 麦克风原始数据在 S3 上经过低通滤波后 48 kHz → 16 kHz 降采样，输出 PCM16。
- 继续保持现有 WebSocket 音频协议：上传 16 kHz PCM16，播放 48 kHz PCM16。

不能简单地每三点丢弃两点；降采样前必须做抗混叠低通滤波。该方案是节省 GPIO 的设计候选，仍需在真实 INMP441/MAX98357A 上测试时钟和音质。

## 7. 组件与版本选择

摄像头驱动有两条路线：

| 路线 | 说明 | 迁移策略 |
|---|---|---|
| espressif/esp32-camera | 官方驱动，支持 ESP32-S3 和 OV2640 | 优先评估能否保持现有 ESP-IDF 5.3.4 |
| esp_video + esp_cam_sensor | larryli BSP 使用的较新视频框架 | 该参考 BSP 要求 IDF >= 5.5.2；若采用，S3 固件单独升级，不影响旧 WROOM 固件 |

参考：
- [esp32-camera](https://github.com/espressif/esp32-camera)
- [esp_video / esp_cam_sensor BSP 示例](https://github.com/larryli/esp-idf_esp32_s3_cam)

## 8. 实机核对清单

在把候选 GPIO 写进固件之前，必须完成：

- [ ] 拍摄开发板背面高清照片，确认 PCB 版本和丝印。
- [ ] 确认模组屏蔽罩标记为 ESP32-S3-WROOM-1-N16R8。
- [ ] 确认摄像头传感器确为 OV2640。
- [ ] 确认摄像头 FPC 连接器与上述 14 路 DVP GPIO 映射一致。
- [ ] 确认两个 Type-C 的用途（原生 USB 与 USB-UART 桥接）。
- [ ] 确认 GPIO38/39/40 只连接 microSD 插槽，没有其他冲突外围电路。
- [ ] 确认 GPIO14、GPIO21、GPIO47 在实际板上没有影响复用的 LED、按键或扩展器。
- [ ] 首次烧录前读取并备份 S3 全部 16 MB Flash；不得调用旧 WROOM 的 4 MB 备份/烧录脚本。

完成以上核对后，才能冻结正式 pin map。
