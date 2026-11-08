# 从零安装：Windows 10/11 x64

本版桌面启动、Wi-Fi助手和凭据加密使用Windows接口。Linux/macOS需要适配，不能直接套用本文的CMD和DPAPI流程。

## 1. 解压与安装Python

从本仓库Release下载整包，或点Code → Download ZIP。解压到例如`C:\dafe-chat`，不要直接在ZIP里运行。开发板编译最好使用无空格英文路径；已有中文目录可用构建脚本的英文镜像解决。

安装[Python3.12 Windows x64](https://www.python.org/downloads/windows/)，保留`py`启动器。NVIDIA用户安装支持CUDA12.6运行时的驱动。PyTorch官方wheel自带运行时；本工程不编译CUDA扩展，不要求为了运行再安装完整CUDA Toolkit。

## 2. 安装项目依赖

双击`安装依赖.cmd`。等价命令如下，在项目目录CMD中运行：

```bat
py -3.12 -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
.venv\Scripts\python.exe -m pip install -r requirements.txt
```

这些命令创建项目自己的环境，不升级其他Anaconda环境。项目附带已验证的VoxCPM推理源码快照，启动时优先使用`third_party/VoxCPM/src`；不要再盲目执行`pip install -U voxcpm`替换它。原作者完整环境版本另见PERFORMANCE.md，公开依赖清单只列推理/网页/烧录必需包，不带原电脑的整套529个包。

已有可用Python的人可以安装到自己的环境，并设置环境变量`DAFE_PYTHON`为该python.exe完整路径。启动CMD的优先级为DAFE_PYTHON → 项目.venv → py -3.12。

## 3. 下载本地模型

双击`下载模型.cmd`。模型不会打进Git仓库，也不会在打开工作台时隐式下载。默认目录：

```text
models/
  paraformer-zh-streaming/   # model.pt、config.yaml、tokens.json等
  VoxCPM2/                  # model.safetensors、audiovae.pth、config.json、tokenizer等
```

下载来源见MODELS.md，需要数GB磁盘和网络流量。中国大陆访问Hugging Face不方便时，可按MODELS.md从ModelScope下载VoxCPM2，放到相同目录。

已有权重可直接复制，或在首次启动前设置：

```bat
set DAFE_ASR_MODEL_PATH=C:\my-models\paraformer
set DAFE_TTS_MODEL_PATH=C:\my-models\VoxCPM2
```

也可在网页修改每个对话的模型目录。环境变量只决定新建数据库的初始路径，不自动覆盖已经保存的对话配置。

## 4. 配置自己的网络和Key

双击`首次配置.cmd`。网络可以是普通2.4GHz路由器，也可以是手机热点。输入自己的DeepSeek Key时不会回显，保存后用Windows DPAPI加密；Key不可写进README或提交到GitHub。

若使用公开预编译固件，网络名称/密码需采用公开演示值；若用自己的普通Wi-Fi，按FLASHING.md重新编译。不能只改电脑配置而保持板上另一个SSID。

也可先跳过Key，进入网页“连接与密钥”配置其他厂商或本地LLM。默认DeepSeek未配置时会提示错误，但网页仍能打开，不用模拟回答冒充连接成功。

## 5. 诊断、烧录、启动

```bat
.venv\Scripts\python.exe scripts\doctor.py
```

本地默认栈需要依赖为OK、cuda=true、asr_weights=true、tts_weights=true、web_bundle=true。此脚本只检查，不加载权重、不请求API、不发声；通过它不等于最终问答通过。

按HARDWARE.md接线、FLASHING.md烧录。双击`启动大肥鱼.cmd`，浏览器访问 **http://127.0.0.1:18766/**。页面先打开，后台模型预热可能需几十秒；完成前可进入设置修正。ESP32状态为已连接后开始说话。

如果防火墙询问，允许此项目Python用于当前网络的局域网接入，不必关闭整个防火墙。DeepSeek需要电脑能访问互联网；纯本地LLM/ASR/TTS在权重齐全后可离线使用。

退出双击`关闭大肥鱼.cmd`。关闭浏览器只关闭界面，后台仍在工作。日常不需要重装依赖、重新下载或重新烧录。
