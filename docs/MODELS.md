# 模型、本地部署和更换API

## 当前采用的三段模型

| 角色 | 默认方案 | 来源 |
|---|---|---|
| ASR语音转文字 | FunASR1.4.23 + Paraformer中文在线模型，CPU运行 | [ModelScope模型页](https://modelscope.cn/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online)、[FunASR](https://github.com/modelscope/FunASR) |
| LLM对话 | DeepSeek API，关闭思考，默认最大输出240 tokens | [DeepSeek API文档](https://api-docs.deepseek.com/) |
| TTS文字转语音 | VoxCPM2，CUDA，本地固定参考音 | [官方仓库](https://github.com/OpenBMB/VoxCPM)、[Hugging Face](https://huggingface.co/openbmb/VoxCPM2)、[ModelScope](https://modelscope.cn/models/OpenBMB/VoxCPM2) |

DeepSeek模型ID由账号可用列表决定：自动候选包含deepseek-flash、deepseek-v4-flash、deepseek-chat；本次账号实际为deepseek-flash。模型命名会变化，不能把它当作所有账号必定有的ID。网页可获取账号模型或手填明确ID。

## 本地模型如何下载

默认运行`下载模型.cmd`。手动下载等价示例：

```python
from modelscope import snapshot_download
snapshot_download('iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online',
                  local_dir='models/paraformer-zh-streaming')
snapshot_download('OpenBMB/VoxCPM2', local_dir='models/VoxCPM2')
```

也可用Hugging Face：

```python
from huggingface_hub import snapshot_download
snapshot_download('openbmb/VoxCPM2', local_dir='models/VoxCPM2')
```

ASR不能只拿一个model.pt，需同时有config.yaml、tokens.json、seg_dict、am.mvn等配套文件；VoxCPM2也需要AudioVAE、配置和tokenizer，不能只拷贝主权重。完整下载优先。

本仓库固定了实际使用的VoxCPM推理源码快照（third_party/VoxCPM），其上游提交ID未记录，按逐文件SHA256标识。原测试权重的SHA256见`tested-model-hashes.json`，本机下载缓存标记为上游master，不宣称锁定了未来的master。以后下载文件若与记录不同，说明模型版本有差异，需重新验证，不要认为所有新版本都已测过。

## 为什么默认参考音和5步

随包`assets/voice/jm-tech.wav`是24kHz单声道、10.72275秒参考音，逐字转写在同目录jm-tech.txt。默认同时作为prompt音频和reference音频，建立ref_continuation缓存，每个短句复用，不随机换人，也不把新回答反喂作参考。

默认5步、CFG2.0、seed0、48kHz输出。1/2/3步在实际试听中出现明显噪声；10步生成更慢，当前小喇叭上的提升不明显，所以选5步。固定参考约束音色，但不保证每个字的韵律完全一致。流式模式不支持retry_badcase，开启也会被当前上游实现关闭。

## 在网页更换模型

1. 设置 → 连接与密钥 → 添加连接。
2. 选择DeepSeek、OpenAI、Ollama、LM Studio或自定义兼容预设，填写Base URL和自己的Key。
3. 勾选该服务实际支持的LLM/ASR/TTS。DeepSeek预设只提供LLM，不假装有语音接口。
4. 在对应模型页选择连接、获取模型或填写ID，点测试，再保存。

常见Base URL：DeepSeek `https://api.deepseek.com/v1`；OpenAI `https://api.openai.com/v1`；Ollama `http://127.0.0.1:11434/v1`；LM Studio `http://127.0.0.1:1234/v1`。本地HTTP服务需自己先启动；本项目不安装或下载LLM权重。

LLM采用OpenAI兼容`/chat/completions`；ASR采用`/audio/transcriptions`整句转写；TTS采用`/audio/speech`并请求WAV。语音接口不是各厂商专有Realtime/WebSocket协议。非兼容服务请按DEVELOPMENT.md添加适配器，而不是只替换URL。

API Key仅在后端使用。留空编辑不会抹掉已存Key，本地免密服务可留空。连接测试可能真实调用并计费；TTS连接测试不自动播放。没有模型ID时只检查模型目录，不当作推理已经成功。

## 参数与配置归属

- 每个对话独立保存ASR/LLM/TTS和监听配置。连接配置记录可被多个对话引用；要分开地址/账号就创建不同连接。
- LLM可调系统提示、温度（默认不发送）、输出长度、上下文预算、摘要保留轮数；思考扩展仅给DeepSeek发送。
- Paraformer可调本地路径、CPU线程、解码块和回看参数；外部ASR只提供模型、语言等基础选项。
- VoxCPM2可调路径、CPU/CUDA、参考音、步数、CFG、seed；外部TTS提供模型、Voice ID、语速。
- 右上角“恢复默认”载入你保存的默认参数，保存后生效，不清空密钥；“保存为默认”影响以后新建对话，不批量改旧对话。

本地LLM与VoxCPM2可能同时占用显存；两者的显存需合计，不能只看TTS的数字。也可用CPU运行的小型本地LLM服务或把其中一段换为API，自行测试性能。
