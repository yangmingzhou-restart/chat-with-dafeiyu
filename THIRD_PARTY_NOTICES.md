# 第三方代码与资源

本仓库根LICENSE的MIT授权适用于本项目原创软件和文档，不替代第三方代码、模型或声音的许可。

| 内容 | 来源与许可 | 保留位置 |
|---|---|---|
| VoxCPM推理源码快照 | [OpenBMB/VoxCPM](https://github.com/OpenBMB/VoxCPM)，Apache-2.0 | third_party/VoxCPM/LICENSE、SOURCE.json |
| esp_websocket_client1.4.0 | [Espressif esp-protocols](https://github.com/espressif/esp-protocols/tree/websocket-v1.4.0/components/esp_websocket_client)，Apache-2.0 | firmware/components/esp_websocket_client中的原LICENSE和SOURCE.json |
| ESP-IDF工具链/SDK | [Espressif](https://github.com/espressif/esp-idf/tree/v5.3.4)，各组件自己的许可 | SDK另行安装；预编译镜像由该SDK构建 |
| React / React DOM / scheduler | Meta及贡献者，MIT | licenses下对应LICENSE |
| Lucide图标 | Lucide贡献者，ISC及Feather部分MIT | licenses/lucide-react-LICENSE.txt |
| Python模型/网络依赖 | 各上游许可，见requirements及原项目 | 由安装工具下载，不打包解释器或整个site-packages |
| Paraformer模型 | ModelScope iic官方模型页，按其模型许可使用 | 权重不随包分发 |
| VoxCPM2模型 | OpenBMB官方模型页，Apache-2.0 | 权重不随包分发 |

`assets/voice/jm-tech.wav`及转写经维护者允许随项目公开，用于本项目运行和复现实验，不是私人聊天录音。参考音不自动套用软件MIT授权；其他用途请联系维护者确认。用户自行导入的声音和模型也不因使用本软件自动改变其授权。

未打包商家资料压缩包、原电脑数据手册合集、个人实物照片、私有数据库或设备整片Flash；硬件文档提供原厂资料链接。
