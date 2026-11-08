"""Local recognition / GPU TTS and non-thinking DeepSeek text streaming."""
import asyncio
import contextlib
import logging
import os
from pathlib import Path
from .voice import load_fixed_voice
from .paths import VOX_SOURCE, TTS_MODEL
import queue
import re
import sys
import threading
import time

LOG = logging.getLogger('dafe.pipeline')
ROOT = Path(__file__).resolve().parents[1]


async def threaded_chunks(factory):
    """Bounded bridge; cancellation stops generation and waits for thread cleanup."""
    items = queue.Queue(maxsize=4)
    stopped = threading.Event()

    def put(value):
        while not stopped.is_set():
            try:
                items.put(value, timeout=0.1)
                return
            except queue.Full:
                pass

    def produce():
        iterator = None
        try:
            iterator = iter(factory())
            for chunk in iterator:
                if stopped.is_set():
                    break
                put(('chunk', chunk))
        except Exception as exc:
            put(('error', exc))
        finally:
            if iterator is not None and hasattr(iterator, 'close'):
                iterator.close()
            put(('end', None))

    worker = asyncio.create_task(asyncio.to_thread(produce))
    try:
        while True:
            try:
                kind, item = await asyncio.to_thread(items.get, True, 0.2)
            except queue.Empty:
                continue
            if kind == 'end':
                break
            if kind == 'error':
                raise item
            yield item
    finally:
        stopped.set()
        await asyncio.shield(worker)


def take_sentences(buffer, final=False):
    """Release short spoken clauses without waiting for the entire LLM answer."""
    result = []
    while buffer:
        match = re.search(r'[。！？!?；;\n]', buffer)
        cut = match.end() if match else (48 if len(buffer) >= 48 else None)
        if cut is None:
            if final:
                result.append(buffer.strip())
                buffer = ''
            break
        text, buffer = buffer[:cut].strip(), buffer[cut:]
        if text:
            result.append(text)
    return [s for s in result if s], buffer


class RealPipeline:
    mode = 'local_asr_deepseek_local_tts'

    def __init__(self, key, model_name='auto'):
        self.key = key
        self.model_name = model_name
        self.model_lock = threading.Lock()
        self.turn_lock = asyncio.Lock()
        self.asr = self.tts = self.client = None
        self.voice_cache = None

    @classmethod
    def configured(cls):
        key_file = ROOT / '.private/deepseek.key'
        key = os.environ.get('DEEPSEEK_API_KEY')
        if not key and key_file.exists():
            key = key_file.read_text(encoding='utf-8-sig').strip()
        if not key:
            raise RuntimeError('DeepSeek key missing: save one line in .private/deepseek.key')
        return cls(key, os.environ.get('DAFE_DEEPSEEK_MODEL', 'auto'))

    def load_models(self):
        import torch
        from .asr import Paraformer
        sys.path.insert(0, str(VOX_SOURCE))
        from voxcpm import VoxCPM
        torch.set_num_threads(6)
        self.asr = Paraformer()
        self.tts = VoxCPM(voxcpm_model_path=str(TTS_MODEL),
                          enable_denoiser=False, optimize=False, device='cuda')
        if self.tts.tts_model.sample_rate != 48000:
            raise RuntimeError('VoxCPM2 must output 48000Hz')
        self.voice_cache = load_fixed_voice(self.tts.tts_model)
        for _ in self.synthesize('你好，我是大肥鱼。'):
            pass
        # GPU model loading can evict CPU ASR pages on this 16GB-RAM machine.
        # Re-warm ASR after TTS, on the same thread used for live recognition.
        import gc
        gc.collect()
        self.asr.executor.submit(self.asr.warmup).result()
        LOG.info('Local ASR and TTS loaded and warmed; fixed voice jm-tech')

    async def start(self):
        from openai import AsyncOpenAI
        self.client = AsyncOpenAI(api_key=self.key, base_url='https://api.deepseek.com',
                                  timeout=30, max_retries=1)
        available = {model.id for model in (await self.client.models.list()).data}
        if self.model_name == 'auto':
            self.model_name = next((name for name in ['deepseek-flash', 'deepseek-v4-flash', 'deepseek-chat']
                                    if name in available), None)
        if self.model_name not in available:
            raise RuntimeError('No configured non-thinking DeepSeek chat model is available')
        LOG.info('DeepSeek model authorized: %s', self.model_name)
        await asyncio.to_thread(self.load_models)

    async def close(self):
        if self.client:
            await self.client.close()
        if self.asr:
            await asyncio.to_thread(self.asr.close)

    def begin_recognition(self):
        return self.asr.begin()

    def transcribe(self, path):
        with self.model_lock:
            return self.asr.transcribe(str(path))

    def synthesize(self, text):
        import numpy as np
        if self.voice_cache is None:
            raise RuntimeError('Fixed reference voice is required')
        with self.model_lock:
            # Use the installed VoxCPM2 cache API so the same reference is encoded once.
            # Streaming does not support retry_badcase in this model version.
            chunks = self.tts.tts_model.generate_with_prompt_cache_streaming(
                target_text=re.sub(r'\s+', ' ', text).strip(), prompt_cache=self.voice_cache,
                inference_timesteps=5, cfg_value=2.0, seed=0, retry_badcase=False)
            try:
                for chunk, _, _ in chunks:
                    wave = chunk.squeeze(0).cpu().numpy().reshape(-1)
                    yield (np.clip(wave, -1, 1) * 32767).astype('<i2').tobytes()
            finally:
                chunks.close()

    async def respond(self, path, history, recognition=None):
        async with self.turn_lock:
            start = time.perf_counter()
            text = await recognition.finish() if recognition else await asyncio.to_thread(self.transcribe, path)
            LOG.info('ASR final in %.3fs, %d characters', time.perf_counter()-start, len(text))
            if not text:
                return
            history.append({'role': 'user', 'content': text})
            messages = [{'role': 'system', 'content':
                         '你是桌面语音伙伴大肥鱼。用自然中文简短回答，通常一到三句话。'
                         '始终由大肥鱼一人说话，不编排多个说话人或切换人物音色。'
                         '不用Markdown、表情或长列表。不能声称执行了你没有执行的操作。'}] + history[-12:]
            stream = await self.client.chat.completions.create(
                model=self.model_name, messages=messages, stream=True, max_tokens=240,
                extra_body={'thinking': {'type': 'disabled'}})
            pending = ''
            answer = ''
            try:
                async for event in stream:
                    if not event.choices:
                        continue
                    part = event.choices[0].delta.content or ''
                    answer += part
                    pending += part
                    sentences, pending = take_sentences(pending)
                    for sentence in sentences:
                        async for chunk in threaded_chunks(lambda s=sentence: self.synthesize(s)):
                            yield chunk
                sentences, _ = take_sentences(pending, final=True)
                for sentence in sentences:
                    async for chunk in threaded_chunks(lambda s=sentence: self.synthesize(s)):
                        yield chunk
            finally:
                await stream.close()
            if answer:
                history.append({'role': 'assistant', 'content': answer})
                del history[:-12]
