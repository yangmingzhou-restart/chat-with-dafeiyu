"""16kHz Paraformer streaming, with a fresh cache per utterance."""
from pathlib import Path
import asyncio
from concurrent.futures import ThreadPoolExecutor
import contextlib
import queue
import threading
import logging
import time

from .paths import ASR_MODEL
MODEL = ASR_MODEL


class Paraformer:
    def __init__(self, config=None):
        from funasr import AutoModel
        self.config = config
        self.threads = config.threads if config else 6
        self.stride = (config.chunk_size if config else 10) * 960
        self.model = AutoModel(model=str(config.model if config else MODEL), device='cpu', ncpu=self.threads,
                               disable_update=True, disable_pbar=True)
        self.lock = threading.Lock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='dafe-asr')
        # Warm the actual inference thread, including its FFT/OpenMP initialization.
        self.executor.submit(self.warmup).result()

    def warmup(self):
        import numpy as np
        import torch
        torch.set_num_threads(self.threads)
        self.decode(np.zeros(9600, dtype=np.float32), {}, True)

    def decode(self, samples, cache, final):
        started = time.perf_counter()
        with self.lock:
            result = self.model.generate(input=samples, cache=cache, is_final=final,
                                         chunk_size=[0, self.config.chunk_size if self.config else 10, 5],
                                         encoder_chunk_look_back=self.config.encoder_lookback if self.config else 4,
                                         decoder_chunk_look_back=self.config.decoder_lookback if self.config else 1, disable_pbar=True)
        duration = time.perf_counter()-started
        if duration > 0.6:
            logging.getLogger('dafe.asr').warning('ASR chunk took %.3fs for %d samples', duration, len(samples))
        return ''.join(item.get('text', '') for item in result)

    def begin(self):
        return OnlineRecognition(self)

    def close(self):
        self.executor.shutdown(wait=True, cancel_futures=True)

    def transcribe(self, path):
        import soundfile as sf
        samples, rate = sf.read(path, dtype='float32')
        if rate != 16000 or samples.ndim != 1:
            raise ValueError('ASR requires 16kHz mono audio')
        cache, parts = {}, []
        stride = self.stride  # Independent of 20ms network audio messages.
        for offset in range(0, len(samples), stride):
            parts.append(self.decode(samples[offset:offset+stride], cache,
                                     offset+stride >= len(samples)))
        return ''.join(parts).strip()


class OnlineRecognition:
    """Feed PCM without blocking network reception; infer during speech."""
    def __init__(self, recognizer):
        self.recognizer = recognizer
        self.input = queue.Queue(maxsize=64)  # 1.28s at normal 20ms packets.
        self.stopped = threading.Event()
        self.ended = False
        self.future = asyncio.get_running_loop().run_in_executor(recognizer.executor, self.run)

    def push(self, pcm):
        if self.future.done():
            self.future.result()
            raise RuntimeError('Recognizer has already ended')
        try:
            self.input.put_nowait(pcm)
        except queue.Full:
            raise RuntimeError('ASR cannot keep up with audio') from None

    def run(self):
        import numpy as np
        pending, cache, parts = bytearray(), {}, []
        while not self.stopped.is_set():
            try:
                pcm = self.input.get(timeout=0.1)
            except queue.Empty:
                continue
            if pcm is None:
                if pending:
                    samples = np.frombuffer(pending, dtype='<i2').astype(np.float32) / 32768
                    parts.append(self.recognizer.decode(samples, cache, True))
                return ''.join(parts).strip()
            pending.extend(pcm)
            # Hold the last chunk so an exact multiple of 600ms can be finalized.
            stride_bytes = getattr(self.recognizer, 'stride', 9600) * 2
            while len(pending) > stride_bytes and not self.stopped.is_set():
                samples = np.frombuffer(pending[:stride_bytes], dtype='<i2').astype(np.float32) / 32768
                del pending[:stride_bytes]
                parts.append(self.recognizer.decode(samples, cache, False))
        return ''

    async def finish(self):
        if not self.ended:
            self.push(None)
            self.ended = True
        return await asyncio.shield(self.future)

    async def close(self):
        self.stopped.set()
        with contextlib.suppress(Exception):
            await asyncio.shield(self.future)
