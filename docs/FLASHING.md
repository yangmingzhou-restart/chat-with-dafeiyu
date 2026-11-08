# ESP32烧录：从预编译固件到自己编译

目标为**经典ESP32、4MB Flash**，不是ESP32-S3/S2/C3。烧录的是本仓库`firmware/`中的ESP-IDF C程序；网页和Python模型服务运行在电脑，不烧进开发板。

## 1. 准备串口和软件

1. 使用支持数据的USB线连接开发板。设备管理器 → 端口中查看对应COM号；插拔确认，**COM4只是示例，不是固定值**。
2. 实测板为CP210x，驱动可从[Silicon Labs官网](https://www.silabs.com/developer-tools/usb-to-uart-bridge-vcp-drivers)下载；CH340等板子用其对应驱动。
3. 关闭工作台和串口监视器。使用项目Python环境中的esptool4.11；首次安装依赖时已安装。

## 2. 最简单：刷公开演示固件

`firmware/prebuilt/`已包含ESP-IDF5.3.4重新编译的三个镜像，**只含公开演示Wi-Fi配置**：`DAFE_DEMO` / `dafe-demo-1234`。它没有作者的网络信息或API Key。把手机2.4GHz/WPA2热点设为这两个值，可以先快速复现；正式接自己的普通Wi-Fi时看第4节重新编译。

在项目目录CMD执行：

```bat
.venv\Scripts\python.exe scripts\flash_firmware.py --port COM4
```

脚本会先识别ESP32和4MB Flash、读取MAC，再读取整片4MB并用esptool验证，保存到`.private/flash-backups/<MAC>.bin`和对应JSON。115200波特率备份可能需要约6分钟，日志暂不刷新不代表程序挂了。完成备份后才刷写，已有原备份不会被覆盖。

只想先备份：

```bat
.venv\Scripts\python.exe scripts\flash_firmware.py --port COM4 --backup-only
```

不要上传备份：其中可能含设备原有程序和网络配置。脚本对不完整、摘要不符或非4MB的备份会拒绝继续。

## 3. GUI或手工烧录

也可从[Espressif官网下载Flash Download Tools](https://www.espressif.com/en/support/download/other-tools)。**先按上一节备份**，再选ESP32的SPI下载模式，COM选自己的端口，波特率先用115200。

| 镜像（相对firmware/prebuilt） | 地址 |
|---|---|
| bootloader/bootloader.bin | `0x1000` |
| partition_table/partition-table.bin | `0x8000` |
| dafe_voice.bin | `0x10000` |

SPI模式DIO、Flash频率40MHz、Flash大小4MB。勾选三个文件后开始下载，完成后按EN复位或重新插拔。不同版本GUI标签可能略不同，以地址和参数为准；不要先随意点ERASE。

已备份的情况下，手工esptool等价命令为：

```bat
.venv\Scripts\python.exe -m esptool --chip esp32 --port COM4 --baud 115200 write_flash --flash_mode dio --flash_freq 40m --flash_size 4MB 0x1000 firmware\prebuilt\bootloader\bootloader.bin 0x8000 firmware\prebuilt\partition_table\partition-table.bin 0x10000 firmware\prebuilt\dafe_voice.bin
```

发布镜像的SHA256在`firmware/prebuilt/SHA256SUMS.json`；官方脚本在刷写前检查它。

## 4. 接普通Wi-Fi或修改参数：自己编译

### 安装ESP-IDF

使用[ESP-IDF5.3.4 Windows安装教程](https://docs.espressif.com/projects/esp-idf/en/v5.3.4/esp32/get-started/windows-setup.html)或[官方安装器](https://dl.espressif.com/dl/esp-idf/)。选择5.3.4和ESP32工具链，SDK和工具路径尽量用无空格英文目录。

VS Code的Espressif扩展可用于编辑和构建，但不是必须。不要混用Arduino旧I²S驱动或其他ESP32示例接线。本项目使用`driver/i2s_std.h`、I²S0采集和I²S1播放。

### 填自己的Wi-Fi

运行`首次配置.cmd`，或者把`config.example.json`复制为`.private/local.json`，填写自己的SSID/密码。**这可以是普通2.4GHz路由器，不要求手机热点。** 本地文件不要提交。

`server_port=18765`、`discovery_port=18767`保持默认；若改这两个端口，必须同时修改Python服务，不能只改固件。

### 构建

从开始菜单打开“ESP-IDF5.3 CMD”，在其中执行：

```bat
cd /d C:\dafe-chat
python scripts\build_firmware.py
```

脚本根据你的私有配置生成被忽略的`firmware/main/private_config.h`，在临时英文目录构建，再把产物复制到`runtime/firmware/`。只构建，**不自动刷写**。若提示英文目录问题，可先设置：

```bat
set DAFE_BUILD_DIR=C:\dafe-build
python scripts\build_firmware.py
```

构建目录有来源标记，拒绝覆盖不属于本项目的目录。日志为`runtime/firmware-build.log`。若特殊终端提示平台`Windows-`不支持，检查`PROCESSOR_ARCHITECTURE`；本版测试x64，可在该终端设置`set PROCESSOR_ARCHITECTURE=AMD64`后重新启动IDF环境。

生成的固件含你自己的SSID/密码，**不要再把runtime/firmware或生成头文件上传公开仓库**。

### 刷入自己构建的固件

在普通CMD中执行：

```bat
.venv\Scripts\python.exe scripts\flash_firmware.py --port COM4 --artifacts runtime\firmware
```

仍会验证本设备原备份后才写入。成功后启动网页，等ESP32自动发现电脑。

## 5. 连接失败、日志与恢复

- 停在Connecting：尝试按住BOOT开始连接，出现连接/写入进度后松开；必要时按EN复位。检查USB数据线、驱动和端口占用。
- 固件控制台为921600波特率；上电最早的ROM日志可能是115200，不要把那部分乱码直接判为程序故障。
- 没声音时先确认设备已连接且是正在回答；待机TX关闭是正常行为，独立测试音已禁用。
- 恢复旧程序：先核对当前板MAC、备份4MB大小和JSON中的SHA256，再用esptool将对应整片备份写回`0x0`并校验。这会覆盖整片Flash，不能拿另一块板的备份随意刷入。

固件源码的GPIO配置、公共默认值和依赖均在仓库；原型已测版本为ESP-IDF5.3.4、官方esp_websocket_client1.4.0。对其他SDK版本不宣称直接兼容。
