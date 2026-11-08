"""Our Paraformer/VoxCPM2 stack plus explicit OpenAI-compatible adapters."""
import asyncio
import hashlib
import io
import json
import math
import re
import sys
from pathlib import Path

import numpy as np

from .pipeline import threaded_chunks
from .studio_config import ROOT
from .paths import VOX_SOURCE


def audio_pcm(data, rate):
    """Normalize decoded provider audio to the existing ESP32 wire format."""
    from scipy.signal import resample_poly
    a = np.asarray(data, dtype=np.float32)
    if a.ndim == 2:
        a = a.mean(axis=1)
    if a.ndim != 1 or not np.isfinite(a).all() or rate <= 0:
        raise ValueError('音频格式无效')
    if rate != 48000:
        divisor = math.gcd(rate, 48000)
        a = resample_poly(a, 48000 // divisor, rate // divisor)
    return (np.clip(a, -1, 1) * 32767).astype('<i2').tobytes()


class Provider:
    def __init__(self, store, settings):
        from openai import AsyncOpenAI
        self.config = store.connection(settings.connection)
        if 'llm' not in self.config['kinds']:
            raise ValueError('所选连接不支持LLM')
        self.settings = settings
        self.model = settings.model
        self.client = AsyncOpenAI(api_key=self.config['api_key'] or 'local-no-key',
                                 base_url=self.config['base_url'], timeout=45, max_retries=0)

    async def resolve(self, verify=False):
        if self.model == 'auto':
            models = {v.id for v in (await self.client.models.list()).data}
            self.model = next((v for v in ('deepseek-flash', 'deepseek-v4-flash', 'deepseek-chat') if v in models), '')
            if not self.model:
                raise ValueError('请在设置中明确选择模型')
        elif verify:
            from openai import APIStatusError
            try:
                available = {m.id for m in (await self.client.models.list()).data}
                if self.model not in available:
                    raise ValueError('模型不在当前连接的可用列表中，请检查模型ID')
            except APIStatusError as exc:
                if exc.status_code not in (404, 405, 501):
                    raise
                # Some local services deliberately omit /models. Test the chosen chat endpoint instead.
                await self.client.chat.completions.create(messages=[{'role': 'user', 'content': '只回答OK'}],
                                                          **self.options(max_tokens=16))
        return self

    def options(self, stream=False, max_tokens=None):
        options = dict(model=self.model, stream=stream)
        limit = max_tokens or self.settings.max_tokens
        if self.config['preset'] == 'openai':
            options['max_completion_tokens'] = limit
        else:
            options['max_tokens'] = limit
        if self.config['preset'] == 'deepseek':
            options['extra_body'] = {'thinking': {'type': 'enabled' if self.settings.thinking else 'disabled'}}
        if self.settings.temperature is not None:
            options['temperature'] = self.settings.temperature
        return options

    async def stream(self, messages):
        response = await self.client.chat.completions.create(messages=messages, **self.options(True))
        try:
            async for event in response:
                if event.choices and event.choices[0].delta.content:
                    yield event.choices[0].delta.content
        finally:
            await response.close()

    async def summarize(self, old, messages):
        request = [{'role': 'system', 'content': '将旧摘要和新对话整理为中文记忆摘要，不超过1200字。保留姓名、偏好、约定、未解决事项；不要编造。'},
                   {'role': 'user', 'content': json.dumps({'old_summary': old, 'messages': messages}, ensure_ascii=False)}]
        response = await self.client.chat.completions.create(messages=request, **self.options(max_tokens=1800))
        text = response.choices[0].message.content or ''
        if not text.strip() or len(text) > 1800:
            raise RuntimeError('摘要结果为空或过长，请重试')
        return text.strip()

    async def close(self):
        await self.client.close()


class Engine:
    def __init__(self, store, settings):
        self.store, self.settings = store, settings
        self.references = store.get('references') or {}
        self.asr = self.tts = self.cache = None

    @staticmethod
    def signature(config):
        return json.dumps({'asr': config.asr.model_dump(), 'tts': {key: getattr(config.tts, key)
            for key in ('connection', 'model', 'device', 'reference')}}, sort_keys=True)

    def load(self):
        import torch
        cfg = self.settings
        try:
            for kind, weight in (('asr', 'model.pt'), ('tts', 'model.safetensors')):
                spec = getattr(cfg, kind)
                if spec.connection == 'local' and not (Path(spec.model).is_dir() and (Path(spec.model)/weight).is_file()):
                    raise ValueError(f'{kind.upper()}本地模型目录或权重不存在；不会自动下载模型')
            if cfg.asr.connection == 'local':
                from .asr import Paraformer
                self.asr = Paraformer(cfg.asr)
            if cfg.tts.connection == 'local':
                sys.path.insert(0, str(VOX_SOURCE))
                from voxcpm import VoxCPM
                self.tts = VoxCPM(voxcpm_model_path=cfg.tts.model, device=cfg.tts.device,
                                  enable_denoiser=False, optimize=False).tts_model
                refs = self.references
                ref = refs.get(cfg.tts.reference)
                if not ref:
                    raise ValueError('参考音不存在')
                for file, key in ((ref['audio'], 'audio_sha256'), (ref['transcript'], 'transcript_sha256')):
                    if hashlib.sha256(Path(file).read_bytes()).hexdigest() != ref[key]:
                        raise ValueError('参考音或转写已改变，请重新导入')
                text = Path(ref['transcript']).read_text(encoding='utf-8-sig').strip()
                if not text:
                    raise ValueError('参考音逐字转写不能为空')
                if self.tts.sample_rate != 48000:
                    raise ValueError('本机VoxCPM2输出必须为48kHz')
                self.cache = self.tts.build_prompt_cache(prompt_wav_path=ref['audio'], reference_wav_path=ref['audio'], prompt_text=text)
                if self.cache.get('mode') != 'ref_continuation':
                    raise ValueError('参考音未生效')
                for _ in self.local_speech('你好，我是大肥鱼。'):
                    pass
            if self.asr:
                self.asr.executor.submit(self.asr.warmup).result()
        except BaseException:
            self.unload()
            raise

    def unload(self):
        if self.asr:
            self.asr.close()
        self.asr = self.tts = self.cache = None
        import gc
        gc.collect()
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

    def local_speech(self, text):
        cfg = self.settings.tts
        if self.cache is None:
            raise RuntimeError('未准备固定参考音')
        iterator = self.tts.generate_with_prompt_cache_streaming(target_text=re.sub(r'\s+', ' ', text).strip(),
            prompt_cache=self.cache, inference_timesteps=cfg.steps, cfg_value=cfg.cfg, seed=cfg.seed, retry_badcase=False)
        try:
            for chunk, _, _ in iterator:
                yield audio_pcm(chunk.squeeze(0).cpu().numpy(), 48000)
        finally:
            iterator.close()

    def begin(self):
        return self.asr.begin() if self.asr else None

    async def transcribe(self, path, recognition=None):
        if recognition:
            return await recognition.finish()
        if self.asr:
            return await asyncio.to_thread(self.asr.transcribe, path)
        from openai import AsyncOpenAI
        cfg = self.settings.asr
        c = self.store.connection(cfg.connection)
        async with AsyncOpenAI(api_key=c['api_key'] or 'local-no-key', base_url=c['base_url'], timeout=60, max_retries=0) as client:
            with open(path, 'rb') as f:
                result = await client.audio.transcriptions.create(file=f, model=cfg.model, language=cfg.language)
            return result.text

    async def speech(self, text):
        if self.tts:
            async for chunk in threaded_chunks(lambda: self.local_speech(text)):
                yield chunk
            return
        import soundfile as sf
        from openai import AsyncOpenAI
        cfg = self.settings.tts
        c = self.store.connection(cfg.connection)
        async with AsyncOpenAI(api_key=c['api_key'] or 'local-no-key', base_url=c['base_url'], timeout=60, max_retries=0) as client:
            response = await client.audio.speech.create(model=cfg.model, voice=cfg.voice, input=text,
                                                        speed=cfg.speed, response_format='wav')
            data, rate = await asyncio.to_thread(sf.read, io.BytesIO(response.content), dtype='float32')
            pcm = await asyncio.to_thread(audio_pcm, data, rate)
            for offset in range(0, len(pcm), 1920):
                yield pcm[offset:offset+1920]
