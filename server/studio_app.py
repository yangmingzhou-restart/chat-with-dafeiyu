"""Loopback management UI and the existing LAN-only ESP32 audio server."""
import asyncio
from contextlib import asynccontextmanager
import hashlib
import io
import json
import logging
from pathlib import Path
import sys
import subprocess
import uuid

from fastapi import FastAPI, HTTPException, Request, WebSocket, UploadFile, Form
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from websockets.asyncio.server import serve

from .main import beacon
from .studio_config import ROOT, PRESETS, ChatSettings, Connection, validate_connection
from .studio_store import Store
from .studio_runtime import Runtime, StudioSession

LOG = logging.getLogger('dafe.studio')


def seed_references(store):
    if store.get('references'):
        return
    refs = {}
    manifest = json.loads((ROOT/'docs/reference-voice.json').read_text(encoding='utf-8'))
    refs['jm-tech'] = dict(id='jm-tech', label='jm-tech (default)',
        audio=str(ROOT/'assets/voice/jm-tech.wav'), transcript=str(ROOT/'assets/voice/jm-tech.txt'),
        seconds=manifest['reference_seconds'], audio_sha256=manifest['audio_sha256'],
        transcript_sha256=manifest['transcript_sha256'])
    store.put('references', refs)


def create_app(store=None, start_hardware=True):
    store = store or Store()
    seed_references(store)
    runtime = Runtime(store)
    background = set()

    async def device_connected(ws):
        if ws.request.path != '/audio' or runtime.device:
            await ws.close(1013, 'One ESP32 at a time')
            return
        session = StudioSession(ws, ROOT/'runtime/captures', runtime)
        runtime.device = session
        runtime.emit()
        try:
            await session.run()
        except Exception as exc:
            LOG.info('Device session closed: %s', type(exc).__name__)
        finally:
            if runtime.job is session.response and runtime.job and not runtime.job.done():
                runtime.job.cancel()
            if runtime.device is session:
                if runtime.busy and session.state == 'play':
                    await runtime.stop(resume=False)
                runtime.device = None
            runtime.emit()

    async def initial_load():
        try:
            await runtime.activate(runtime.active)
        except ValueError:
            pass  # Settings remains available even when credentials/model loading failed.

    async def hotspot():
        process = await asyncio.create_subprocess_exec(sys.executable, '-X', 'utf8',
            str(ROOT/'scripts/connect_hotspot.py'), cwd=ROOT,
            stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        try:
            code = await process.wait()
            if code == 0:
                while runtime.switching:
                    await asyncio.sleep(.5)
                if not runtime.ready:
                    await initial_load()
            else:
                LOG.warning('Hotspot connection helper stopped; UI remains available')
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()

    @asynccontextmanager
    async def lifespan(app):
        (ROOT/'runtime/captures').mkdir(parents=True, exist_ok=True)
        socket = None
        if start_hardware:
            socket = await serve(device_connected, '0.0.0.0', 18765, max_size=16384, max_queue=16,
                                 ping_interval=15, ping_timeout=15)
            background.add(asyncio.create_task(beacon(18765, 18767)))
            background.add(asyncio.create_task(initial_load()))
            background.add(asyncio.create_task(hotspot()))
        try:
            yield
        finally:
            for task in background:
                task.cancel()
            await asyncio.gather(*background, return_exceptions=True)
            await runtime.stop(resume=False)
            if socket:
                socket.close()
                await socket.wait_closed()
            if runtime.engine:
                await asyncio.to_thread(runtime.engine.unload)

    app = FastAPI(lifespan=lifespan)
    app.state.runtime, app.state.store = runtime, store

    @app.middleware('http')
    async def local_only(request, call_next):
        if request.url.path.startswith('/api'):
            if request.url.hostname not in ('127.0.0.1', 'localhost', 'testserver'):
                return JSONResponse({'detail': '仅允许本地主机名'}, status_code=403)
            origin = request.headers.get('origin')
            if origin and origin not in ('http://127.0.0.1:18766', 'http://localhost:18766', 'http://testserver'):
                return JSONResponse({'detail': '仅允许本地界面访问'}, status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': '仅允许本地界面访问'}, status_code=403)
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'detail': str(exc)}, status_code=400)

    @app.exception_handler(KeyError)
    async def missing(request, exc):
        return JSONResponse({'detail': '记录不存在'}, status_code=404)

    class NewChat(BaseModel):
        title: str = Field('新对话', min_length=1, max_length=100)
        project: str | None = None

    class Rename(BaseModel):
        name: str = Field(min_length=1, max_length=100)

    class EditChat(BaseModel):
        title: str | None = Field(None, min_length=1, max_length=100)
        project: str | None = None

    class Message(BaseModel):
        text: str = Field(min_length=1, max_length=12000)
        speak: bool = False

    @app.get('/api/health')
    async def health():
        return dict(app='dafe-studio', version=1)

    @app.post('/api/shutdown')
    async def shutdown():
        callback = getattr(app.state, 'shutdown', None)
        if callback is None:
            raise HTTPException(409, '此启动方式由外部进程管理')
        await runtime.stop(resume=False)
        callback()
        return dict(ok=True)

    @app.get('/api/state')
    async def snapshot():
        return dict(status=runtime.status(), chats=store.chats(), projects=store.projects(),
                    defaults=store.get('defaults'), connections=store.connections(), presets=PRESETS,
                    references=[{k: v for k, v in ref.items() if k in ('id', 'label', 'seconds')}
                                for ref in (store.get('references') or {}).values()])

    @app.post('/api/projects')
    async def new_project(body: Rename):
        id = store.project(body.name)
        runtime.emit('refresh')
        return dict(id=id)

    @app.patch('/api/projects/{id}')
    async def rename_project(id: str, body: Rename):
        if id not in {p['id'] for p in store.projects()}:
            raise KeyError(id)
        store.project(body.name, id)
        runtime.emit('refresh')
        return dict(ok=True)

    @app.post('/api/chats')
    async def new_chat(body: NewChat):
        if body.project and body.project not in {p['id'] for p in store.projects()}:
            raise ValueError('项目不存在')
        chat = store.create_chat(body.title, body.project)
        runtime.emit('refresh')
        return chat

    @app.get('/api/chats/{id}')
    async def chat(id: str):
        return store.chat(id)

    @app.patch('/api/chats/{id}')
    async def edit_chat(id: str, body: EditChat):
        args = {k: v for k, v in body.model_dump(exclude_unset=True).items()}
        if args.get('project') and args['project'] not in {p['id'] for p in store.projects()}:
            raise ValueError('项目不存在')
        store.update_chat(id, **args)
        runtime.emit('refresh')
        return store.chat(id)

    @app.post('/api/chats/{id}/activate')
    async def activate(id: str):
        await runtime.activate(id)
        return runtime.status()

    @app.put('/api/chats/{id}/config')
    async def configuration(id: str, config: ChatSettings):
        if runtime.busy or runtime.switching:
            raise HTTPException(409, '请先停止当前回答，再保存配置')
        runtime.validate(config)
        if runtime.active == id:
            await runtime.activate(id, config.model_dump())
        else:
            store.update_chat(id, config=config.model_dump())
            runtime.emit('refresh')
        return store.chat(id)

    @app.put('/api/defaults')
    async def defaults(config: ChatSettings):
        runtime.validate(config)
        store.put('defaults', config.model_dump())
        runtime.emit('refresh')
        return dict(ok=True)

    @app.post('/api/chats/{id}/messages')
    async def send_message(id: str, body: Message):
        store.chat(id)
        if not body.text.strip():
            raise ValueError('请输入消息')
        await runtime.submit(id, body.text.strip(), body.speak)
        return dict(accepted=True)

    @app.post('/api/stop')
    async def stop():
        if runtime.switching:
            raise HTTPException(409, '模型切换中，请等待准备结束')
        await runtime.stop()
        return runtime.status()

    @app.put('/api/connections/{id}')
    async def connection(id: str, config: Connection):
        if runtime.busy or runtime.switching:
            raise HTTPException(409, '当前正在运行，请先停止回答')
        # Connection edits are saved profiles; currently loaded settings are reapplied explicitly.
        store.save_connection(id, validate_connection(config))
        runtime.emit('refresh')
        return dict(ok=True)

    async def api_client(id):
        from openai import AsyncOpenAI
        cfg = store.connection(id)
        return AsyncOpenAI(api_key=cfg['api_key'] or 'local-no-key', base_url=cfg['base_url'], timeout=30, max_retries=0)

    @app.get('/api/connections/{id}/models')
    async def models(id: str):
        try:
            async with await api_client(id) as client:
                return dict(models=[m.id for m in (await client.models.list()).data])
        except Exception as exc:
            raise HTTPException(400, '获取模型失败（' + type(exc).__name__ + '），可手填模型ID') from None

    @app.post('/api/connections/{id}/test')
    async def test_connection(id: str, body: dict):
        kind, model = body.get('kind', 'llm'), body.get('model', '')
        cfg = store.connection(id)
        if kind not in cfg['kinds']:
            raise ValueError('连接不支持此模型类型')
        try:
            async with await api_client(id) as client:
                if not model or model == 'auto':
                    found = [m.id for m in (await client.models.list()).data]
                    return dict(ok=True, detail=f'模型目录可达，共{len(found)}个模型；选择模型后可测试推理')
                if kind == 'llm':
                    options = {'max_completion_tokens' if cfg['preset'] == 'openai' else 'max_tokens': 16}
                    if cfg['preset'] == 'deepseek':
                        options['extra_body'] = {'thinking': {'type': 'disabled'}}
                    await client.chat.completions.create(model=model, messages=[{'role': 'user', 'content': '只回答OK'}], **options)
                elif kind == 'asr':
                    import soundfile as sf
                    import numpy as np
                    sample = io.BytesIO()
                    sf.write(sample, np.zeros(16000), 16000, format='WAV', subtype='PCM_16')
                    await client.audio.transcriptions.create(model=model, file=('silence.wav', sample.getvalue(), 'audio/wav'))
                else:
                    import soundfile as sf
                    response = await client.audio.speech.create(model=model, voice=body.get('voice', 'alloy'), input='连接测试', response_format='wav')
                    sf.info(io.BytesIO(response.content))
            return dict(ok=True, detail='接口实际请求成功（未播放测试音）')
        except Exception as exc:
            raise HTTPException(400, '测试失败：' + type(exc).__name__) from None

    @app.post('/api/references')
    async def upload_reference(audio: UploadFile, transcript: str = Form(...), label: str = Form(...)):
        import soundfile as sf
        content = await audio.read(20 * 1024 * 1024 + 1)
        if len(content) > 20 * 1024 * 1024 or not transcript.strip() or not label.strip():
            raise ValueError('参考音需小于20MB，并填写名称和逐字转写')
        try:
            info = sf.info(io.BytesIO(content))
            if info.channels != 1 or info.samplerate < 16000 or not 1 <= info.duration <= 30:
                raise ValueError('请提供1—30秒、单声道、至少16kHz的参考音')
        except RuntimeError:
            raise ValueError('无法读取音频文件') from None
        # Uploaded containers are normalized once; the model and browser get a real WAV.
        decoded, rate = sf.read(io.BytesIO(content), dtype='float32')
        canonical = io.BytesIO()
        sf.write(canonical, decoded, rate, format='WAV', subtype='PCM_16')
        content = canonical.getvalue()
        id = uuid.uuid4().hex
        folder = ROOT/'.private/voice'/id
        folder.mkdir(parents=True)
        (folder/'reference.wav').write_bytes(content)
        (folder/'reference.txt').write_text(transcript.strip(), encoding='utf-8')
        refs = store.get('references') or {}
        refs[id] = dict(id=id, label=label.strip()[:100], seconds=info.duration, audio=str(folder/'reference.wav'),
            transcript=str(folder/'reference.txt'), audio_sha256=hashlib.sha256(content).hexdigest(),
            transcript_sha256=hashlib.sha256((folder/'reference.txt').read_bytes()).hexdigest())
        store.put('references', refs)
        runtime.emit('refresh')
        return dict(id=id)

    @app.get('/api/references/{id}/audio')
    async def reference_audio(id: str):
        ref = (store.get('references') or {}).get(id)
        if not ref:
            raise KeyError(id)
        return FileResponse(ref['audio'], media_type='audio/wav')

    @app.websocket('/api/events')
    async def events(ws: WebSocket):
        origin = ws.headers.get('origin')
        if origin not in ('http://127.0.0.1:18766', 'http://localhost:18766', 'http://testserver'):
            await ws.close(1008)
            return
        await ws.accept()
        queue = asyncio.Queue(maxsize=256)
        runtime.listeners.add(queue)
        try:
            await ws.send_json(dict(type='resync', status=runtime.status()))
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), 10)
                except asyncio.TimeoutError:
                    event = dict(type='status', status=runtime.status())
                await ws.send_json(event)
        except Exception:
            pass
        finally:
            runtime.listeners.discard(queue)

    assets = ROOT/'web/dist'
    if assets.exists():
        app.mount('/', StaticFiles(directory=assets, html=True), name='ui')
    else:
        @app.get('/')
        async def no_ui():
            return JSONResponse({'detail': '前端尚未构建，请参阅开发说明'}, status_code=503)
    return app


if __name__ == '__main__':
    import uvicorn
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    # SDK HTTP logs can contain user-provided endpoint query strings; keep them quiet.
    logging.getLogger('httpx').setLevel(logging.WARNING)
    app = create_app()
    server = uvicorn.Server(uvicorn.Config(app, host='127.0.0.1', port=18766, log_level='info'))
    app.state.shutdown = lambda: setattr(server, 'should_exit', True)
    server.run()
