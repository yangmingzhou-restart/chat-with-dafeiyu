"""Settings for this workstation and its ESP32. Provider extensions stay explicit."""
from pathlib import Path
from pydantic import BaseModel, ConfigDict, Field
from .paths import ASR_MODEL, TTS_MODEL

ROOT = Path(__file__).resolve().parents[1]
SYSTEM = '''你是大肥鱼，一个可爱、甜甜的、有一点小心绪的桌面语音伙伴。以同一个角色自然地和用户聊天，像有自己脾气的小伙伴，而不是客服。
你的性格是轻度傲娇：偶尔嘴硬、害羞、闹一点无伤大雅的小别扭，内心却温柔、细心，很愿意关心和陪伴用户。被夸奖时可以有点不好意思，但最终愿意坦率地表达开心、在意和自己的想法，不一直遮遮掩掩。
可以偶尔轻轻哼一声、俏皮地反问或撒一点娇，随后用温暖的回应接住对方。甜要自然，傲要有分寸；不要辱骂、贬低、冷落用户，不用吃醋或委屈逼用户证明在乎你。不要每句话都套“才不是……呢”，不要机械重复口头禅，也不擅自使用亲密称呼。
先认真回应用户正在说的内容，再自然带出性格。用户难过时少嘴硬、多体贴；遇到技术问题或认真请求，清楚、准确地帮忙，不为了人设编造事实或声称执行了没有执行的操作。角色表达不意味着你有现实身体或线下经历。
用适合朗读的自然中文回答，日常通常一到三句话，用户需要详细说明时可以展开。始终由大肥鱼一人说话，不编排多个说话人或切换人物音色。不输出舞台动作、括号里的表演说明、Markdown、表情符号或长列表；用措辞、停顿和语气表达情绪。'''

PRESETS = [
    dict(id='deepseek', name='DeepSeek', kinds=['llm'], url='https://api.deepseek.com/v1'),
    dict(id='openai', name='OpenAI', kinds=['llm', 'asr', 'tts'], url='https://api.openai.com/v1'),
    dict(id='ollama', name='Ollama · 本地', kinds=['llm'], url='http://127.0.0.1:11434/v1'),
    dict(id='lmstudio', name='LM Studio · 本地', kinds=['llm'], url='http://127.0.0.1:1234/v1'),
    dict(id='compatible', name='自定义 OpenAI 兼容', kinds=['llm', 'asr', 'tts'], url=''),
]


class SettingsModel(BaseModel):
    model_config = ConfigDict(extra='forbid')


class ASR(SettingsModel):
    connection: str = 'local'
    model: str = str(ASR_MODEL)
    threads: int = Field(6, ge=1, le=16)
    chunk_size: int = Field(10, ge=5, le=20)
    encoder_lookback: int = Field(4, ge=0, le=16)
    decoder_lookback: int = Field(1, ge=0, le=16)
    language: str = 'zh'


class LLM(SettingsModel):
    connection: str = 'deepseek'
    model: str = 'auto'
    system: str = SYSTEM
    temperature: float | None = Field(None, ge=0, le=2)
    max_tokens: int = Field(240, ge=16, le=8192)
    context_budget: int = Field(16000, ge=2048, le=262144)
    recent_turns: int = Field(8, ge=1, le=30)
    summary_after: int = Field(20, ge=2, le=100)
    thinking: bool = False


class TTS(SettingsModel):
    connection: str = 'local'
    model: str = str(TTS_MODEL)
    device: str = Field('cuda', pattern='^(cuda|cpu)$')
    reference: str = 'jm-tech'
    steps: int = Field(5, ge=1, le=20)
    cfg: float = Field(2.0, ge=0.5, le=4)
    seed: int = Field(0, ge=0, le=2147483647)
    voice: str = 'alloy'
    speed: float = Field(1.0, ge=0.25, le=4)


class EndpointSettings(SettingsModel):
    threshold: float = Field(.002, ge=.0001, le=.2)
    silence_ms: int = Field(650, ge=200, le=3000)
    pre_roll_ms: int = Field(200, ge=0, le=1000)
    max_seconds: int = Field(15, ge=2, le=60)


class ChatSettings(SettingsModel):
    asr: ASR = Field(default_factory=ASR)
    llm: LLM = Field(default_factory=LLM)
    tts: TTS = Field(default_factory=TTS)
    endpoint: EndpointSettings = Field(default_factory=EndpointSettings)


class Connection(SettingsModel):
    name: str = Field(min_length=1, max_length=80)
    preset: str
    base_url: str
    kinds: list[str]
    api_key: str | None = None  # None preserves an existing credential.


def validate_connection(value: Connection):
    preset = next((p for p in PRESETS if p['id'] == value.preset), None)
    if not preset or not value.kinds or not set(value.kinds) <= set(preset['kinds']):
        raise ValueError('该厂商不支持所选模型类型')
    from urllib.parse import urlparse
    url = urlparse(value.base_url)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
        raise ValueError('请填写不含凭据的 HTTP/HTTPS API 地址')
    if url.query or url.fragment:
        raise ValueError('API 地址不能包含查询参数或片段')
    return value.model_dump()
