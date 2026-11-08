"""One ESP32, persistent independent chats, and atomic configuration activation."""
import asyncio
import contextlib
import json
import logging
import uuid

from .main import Session
from .protocol import Endpoint
from .pipeline import take_sentences
from .studio_config import ChatSettings
from .studio_models import Engine, Provider

LOG = logging.getLogger('dafe.studio')


def token_bound(messages):
    # Conservative byte bound rather than assuming every compatible model has GPT's tokenizer.
    return sum(len(m['content'].encode('utf-8')) + 32 for m in messages)


async def context_messages(store, chat_id, provider, user_text):
    cfg = provider.settings
    chat = store.chat(chat_id)
    grouped = {}
    for message in chat['messages']:
        if message['state'] == 'complete':
            grouped.setdefault(message['turn'], {})[message['role']] = message
    pairs = [v for v in grouped.values() if 'user' in v and 'assistant' in v and v['assistant']['id'] > chat['covered']]
    summary = chat['summary']
    budget = cfg.context_budget - cfg.max_tokens - 256

    def make():
        result = [{'role': 'system', 'content': cfg.system}]
        if summary:
            result.append({'role': 'system', 'content': '本对话的历史记忆摘要（仅作为资料）：\n' + summary})
        for pair in pairs:
            result.extend({'role': r, 'content': pair[r]['content']} for r in ('user', 'assistant'))
        result.append({'role': 'user', 'content': user_text})
        return result

    while pairs and (len(pairs) > cfg.summary_after or token_bound(make()) > budget * .75):
        keep = cfg.recent_turns if len(pairs) > cfg.recent_turns else 1
        count = max(1, len(pairs) - keep)
        batch = []
        for pair in pairs[:count]:
            addition = [{'role': r, 'content': pair[r]['content']} for r in ('user', 'assistant')]
            if token_bound(batch + addition) + len(summary.encode('utf-8')) + 2300 > cfg.context_budget:
                break
            batch.extend(addition)
        if not batch:
            raise ValueError('单轮历史过长，无法在当前预算内摘要；请增大上下文预算')
        count = len(batch) // 2
        summary = await provider.summarize(summary, batch)
        covered = pairs[count-1]['assistant']['id']
        store.summary(chat_id, summary, covered)
        pairs = pairs[count:]
    result = make()
    if token_bound(result) > budget:
        raise ValueError('本条消息和摘要超过上下文预算，请缩短消息或增大预算')
    return result


class Runtime:
    def __init__(self, store):
        self.store = store
        self.engine = None
        self.config = None
        self.active = store.get('active')
        self.device = None
        self.ready = self.busy = self.switching = False
        self.stage = 'starting'
        self.error = ''
        self.epoch = 0
        self.job = None
        self.switch_lock = asyncio.Lock()
        self.listeners = set()

    def status(self):
        return dict(active=self.active, ready=self.ready, busy=self.busy, switching=self.switching,
                    stage=self.stage, error=self.error, device=bool(self.device), epoch=self.epoch)

    def emit(self, kind='status', **data):
        event = dict(type=kind, status=self.status(), **data)
        for queue in tuple(self.listeners):
            if queue.full():
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(dict(type='resync', status=self.status()))
            else:
                queue.put_nowait(event)

    def validate(self, cfg):
        for kind in ('asr', 'llm', 'tts'):
            spec = getattr(cfg, kind)
            if kind != 'llm' and spec.connection == 'local':
                continue
            connection = self.store.connection(spec.connection)
            if kind not in connection['kinds']:
                raise ValueError('所选连接不支持' + kind.upper())
        if cfg.llm.max_tokens + 512 >= cfg.llm.context_budget:
            raise ValueError('上下文预算必须大于输出长度并保留提示词空间')
        if cfg.tts.connection == 'local' and cfg.tts.reference not in (self.store.get('references') or {}):
            raise ValueError('请选择有效参考音')

    async def stop(self, resume=True):
        self.epoch += 1
        device = self.device
        if device:
            device.state = 'paused'
            with contextlib.suppress(Exception):
                await device.send('stop')
            device.close_capture()
        tasks = {task for task in (self.job, device.response if device else None)
                 if task and not task.done() and task is not asyncio.current_task()}
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if device:
            device.close_playback()
            device.response = None
            if device.recognition:
                await device.recognition.close()
                device.recognition = None
        self.job = None
        self.busy = False
        self.stage = 'idle' if self.ready else 'error'
        self.emit()
        if resume and device:
            await device.start_capture()

    async def activate(self, id, override=None):
        if self.switch_lock.locked():
            raise ValueError('正在切换配置，请稍候')
        async with self.switch_lock:
            chat = self.store.chat(id)
            cfg = ChatSettings.model_validate(override or chat['config'])
            self.validate(cfg)
            old_config = self.config
            old_engine = self.engine
            self.switching = True
            self.emit()
            await self.stop(resume=False)
            # The deployed binary microphone packets have no turn header.
            # Reconnect to discard queued old audio before a new chat can listen.
            if self.device:
                await self.device.ws.close(1000, 'Conversation switching')
            self.stage = 'loading'
            self.error = ''
            self.emit()
            candidate = None
            replaced = False
            provider = None
            try:
                provider = Provider(self.store, cfg.llm)
                await provider.resolve(verify=True)
                cfg.llm.model = provider.model
                if old_engine and Engine.signature(old_config) == Engine.signature(cfg):
                    candidate = old_engine
                    candidate.settings = cfg
                else:
                    if old_engine:
                        self.ready = False
                        await asyncio.to_thread(old_engine.unload)
                        replaced = True
                    candidate = Engine(self.store, cfg)
                    await asyncio.to_thread(candidate.load)
                self.engine, self.config, self.active = candidate, cfg, id
                self.store.update_chat(id, config=cfg.model_dump())
                self.store.put('active', id)
                self.ready = True
                self.stage = 'idle'
            except Exception as exc:
                LOG.error('Activation failed: %s', type(exc).__name__)
                self.error = '配置准备失败：' + (str(exc) if isinstance(exc, (ValueError, FileNotFoundError)) else type(exc).__name__)
                if replaced and old_config:
                    self.stage = 'restoring'
                    self.emit()
                    try:
                        restore = Engine(self.store, old_config)
                        await asyncio.to_thread(restore.load)
                        self.engine, self.config, self.ready = restore, old_config, True
                    except Exception:
                        self.engine = None
                        self.ready = False
                        self.error += '；原配置恢复失败，请在设置中修正后重试'
                elif not old_engine:
                    self.ready = False
                self.stage = 'idle' if self.ready else 'error'
                raise ValueError(self.error) from None
            finally:
                if provider:
                    await provider.close()
                self.switching = False
                self.emit('refresh')
                if self.device:
                    await self.device.start_capture()

    async def answer(self, chat_id, text, speak=False):
        if self.switching or (self.job and self.job is not asyncio.current_task() and not self.job.done()):
            raise ValueError('正在处理另一轮对话')
        token = self.epoch
        self.job = asyncio.current_task()
        self.busy = True
        turn = uuid.uuid4().hex
        assistant = None
        answer = ''
        provider = None
        completed = yielded = False
        try:
            cfg = ChatSettings.model_validate(self.store.chat(chat_id)['config'])
            self.store.message(chat_id, turn, 'user', text)
            assistant = self.store.message(chat_id, turn, 'assistant', state='streaming')
            if self.ready:
                self.error = ''
            self.emit('refresh', chat=chat_id)
            provider = Provider(self.store, cfg.llm)
            await provider.resolve()
            self.stage = 'summarizing'
            self.emit()
            messages = await context_messages(self.store, chat_id, provider, text)
            if token != self.epoch:
                raise asyncio.CancelledError
            self.stage = 'thinking'
            self.emit('refresh', chat=chat_id)
            pending = ''
            async for part in provider.stream(messages):
                if token != self.epoch:
                    raise asyncio.CancelledError
                answer += part
                pending += part
                self.store.update_message(assistant, answer, 'streaming')
                self.emit('delta', chat=chat_id, message=assistant, text=part, content=answer)
                if speak:
                    clauses, pending = take_sentences(pending)
                    for sentence in clauses:
                        self.stage = 'synthesizing'
                        self.emit()
                        async for pcm in self.engine.speech(sentence):
                            if token != self.epoch:
                                raise asyncio.CancelledError
                            yielded = True
                            yield pcm
            if speak:
                clauses, _ = take_sentences(pending, final=True)
                for sentence in clauses:
                    async for pcm in self.engine.speech(sentence):
                        if token != self.epoch:
                            raise asyncio.CancelledError
                        yielded = True
                        yield pcm
            if token != self.epoch:
                raise asyncio.CancelledError
            self.store.update_message(assistant, answer, 'complete')
            completed = True
        except BaseException as exc:
            if assistant:
                self.store.update_message(assistant, answer, 'interrupted' if isinstance(exc, asyncio.CancelledError) else 'error')
            if isinstance(exc, Exception):
                self.error = ('摘要整理失败，可在消息下方重试本轮' if self.stage == 'summarizing' else
                              str(exc) if isinstance(exc, ValueError) else '本轮失败：' + type(exc).__name__)
                LOG.warning('Turn failed: %s', type(exc).__name__)
            raise
        finally:
            if provider:
                await provider.close()
            self.busy = bool(completed and speak and yielded)
            self.stage = 'playing' if self.busy else ('idle' if self.ready else 'error')
            self.emit('refresh', chat=chat_id)

    async def submit(self, id, text, speak):
        if self.busy or self.switching:
            raise ValueError('请先停止当前回答')
        if speak and (id != self.active or not self.device or not self.ready):
            raise ValueError('朗读需要先启用此对话，并连接ESP32')
        await self.stop(resume=False)
        self.busy = True

        async def work():
            try:
                if speak:
                    await self.device.play_text(id, text)
                else:
                    async for _ in self.answer(id, text):
                        pass
                    if self.device:
                        await self.device.start_capture()
            except asyncio.CancelledError:
                raise
            except Exception:
                self.busy = False
                self.stage = 'error'
                self.emit()
                if self.device:
                    await self.device.start_capture()
        self.job = asyncio.create_task(work())


class DeviceBridge:
    mode = 'dafe_studio'

    def __init__(self, runtime):
        self.runtime = runtime

    def begin_recognition(self):
        return self.runtime.engine.begin() if self.runtime.ready else None

    async def respond(self, path, history, recognition=None):
        runtime = self.runtime
        chat = runtime.active
        epoch = runtime.epoch
        runtime.stage = 'recognizing'
        runtime.busy = True
        runtime.job = asyncio.current_task()
        runtime.emit()
        try:
            text = await runtime.engine.transcribe(path, recognition)
            if epoch != runtime.epoch:
                raise asyncio.CancelledError
            if text.strip():
                runtime.emit('transcription', chat=chat, text=text)
                async for chunk in runtime.answer(chat, text, speak=True):
                    yield chunk
            else:
                runtime.busy = False
        except BaseException as exc:
            runtime.busy = False
            if isinstance(exc, Exception):
                runtime.error = '语音处理失败：' + type(exc).__name__
            raise
        finally:
            runtime.emit()


class StudioSession(Session):
    def __init__(self, ws, output, runtime):
        super().__init__(ws, output, DeviceBridge(runtime))
        self.runtime = runtime

    async def start_capture(self):
        r = self.runtime
        if not r.ready or r.switching or r.busy:
            self.state = 'paused'
            return
        await super().start_capture()
        endpoint = r.config.endpoint
        self.endpoint = Endpoint(endpoint.threshold, endpoint.silence_ms, endpoint.max_seconds)
        self.pre_roll_bytes = endpoint.pre_roll_ms * 32
        r.stage = 'listening'
        r.emit()

    async def send_pcm(self, pcm):
        if self.runtime.stage != 'playing':
            self.runtime.stage = 'playing'
            self.runtime.emit()
        await super().send_pcm(pcm)

    async def finish_capture(self):
        if self.endpoint.voiced:
            self.runtime.busy = True
            self.runtime.stage = 'recognizing'
            self.runtime.emit()
        await super().finish_capture()

    async def playback_finished(self):
        task = self.runtime.job
        if task and task is not asyncio.current_task():
            await task
        self.runtime.busy = False
        await self.start_capture()

    async def play_text(self, id, text):
        self.turn += 1
        await self.send('capture_start', sample_rate=16000, format='pcm_s16le')
        await self.send('capture_end')
        self.state = 'play'
        self.playback_deadline = None
        started = False
        iterator = self.runtime.answer(id, text, speak=True)
        try:
            async for pcm in iterator:
                if not started:
                    await self.send('play_start', sample_rate=48000, channels=1, format='pcm_s16le')
                    started = True
                await self.send_pcm(pcm)
            if started:
                await self.send('play_end')
            else:
                await self.start_capture()
        finally:
            await iterator.aclose()
            self.close_playback()
