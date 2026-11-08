# 结构、修改参数与扩展接口

本项目针对一台电脑和一块经典ESP32，不引入通用Agent平台、工具执行或多设备集群。

```text
server/       FastAPI管理API、SQLite、模型适配、语音Session
web/src/      React + TypeScript界面
web/dist/     预构建网页，运行不需要Node
firmware/     ESP-IDF5.3.4源码、官方WebSocket组件、公开预编译镜像
assets/voice/ 固定参考音和转写
third_party/  已验证VoxCPM推理源码快照及Apache许可证
scripts/      首次配置、下载、启动、构建、备份烧录与诊断
tests/        32项电脑回归测试
docs/         软硬件、网络、模型、烧录和性能资料
```

## 改哪里

| 内容 | 位置 |
|---|---|
| 默认角色提示、参数、厂商能力 | server/studio_config.py |
| 可移植模型目录和环境变量 | server/paths.py |
| SQLite记录和Windows DPAPI凭据 | server/studio_store.py |
| LLM文本/摘要、ASR/TTS适配、音频转换 | server/studio_models.py |
| 激活切换、取消、上下文隔离、摘要、设备桥接 | server/studio_runtime.py |
| 网页API、事件、参考音导入、设备监听 | server/studio_app.py |
| 网页交互与样式 | web/src/main.tsx、style.css |
| 引脚、I²S、播放缓冲和网络 | firmware/main/audio_io.c、network.c |

默认值修改只影响新建配置，不覆盖已保存在SQLite的旧对话。普通使用优先在网页编辑当前对话或保存默认配置。想从零初始化时先停止并备份自己的.private，不要随意删除已有聊天。

## 适配新API

OpenAI兼容服务直接在网页添加连接即可；若是其他协议，在studio_models中增加明确的适配分支/类，在PRESETS中登记支持的类型，再补测试。不要把不同厂商专有鉴权简单塞进URL。

- LLM必须提供可取消的有序文本流；摘要用同一对话的LLM。
- ASR返回最终文本；可增量时提供push/finish/close，不支持增量时返回None并走整句转写。
- TTS交给设备前必须是48kHz mono PCM16LE偶数字节块；容器需解码，其他采样率/声道先转换，不发送WAV头。
- 所有任务固定chat_id、turn和运行epoch；取消后的旧结果不能写入新对话。
- 错误必须明确显示，禁止自动改用随机参考音、其他厂商或模拟回答。

当前DeepSeek采用thinking显式开关；OpenAI输出长度使用max_completion_tokens，其他兼容服务使用max_tokens。温度默认不发送，避免对未知模型自动附带不支持的参数。

## 设备与管理端口

ESP32音频WebSocket：TCP18765 `/audio`；UDP18767发现电脑。管理端：只监听127.0.0.1:18766。固件二进制音频不带话轮头，切换对话会重连，丢弃旧连接排队的麦克风包。收到设备played后才恢复监听，不把网络下发完成当作播放完成。

主要API：`/api/state`、`/api/chats`、`/api/chats/{id}/activate`、`/api/chats/{id}/config`、`/api/chats/{id}/messages`、`/api/defaults`、`/api/connections`及`/api/events`事件WebSocket。浏览聊天的GET不激活它。

## 前端构建与测试

开发前端使用Node24（作者环境），在web中运行`npm ci`、`npm run build`，交付dist和lockfile；不要把node_modules提交。日常用户不需要Node。

```bat
.venv\Scripts\python.exe -m unittest discover -s tests -v
.venv\Scripts\python.exe scripts\doctor.py
```

新增接口应验证鉴权、请求字段、流结束、错误取消和音频转换。没有真实凭据时，只能标注“协议测试”，不要声称该厂商真账号已经可用。

## 发布前

绝不提交.private、runtime、models、.venv、生成的private_config.h、自己的编译镜像或聊天录音。只有firmware/prebuilt中的公开演示配置镜像可随发行版发布；替换它时必须检查Wi-Fi配置和SHA256。保留第三方许可证。
