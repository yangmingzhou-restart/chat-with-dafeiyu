import asyncio
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

from server.studio_app import create_app
from server.studio_config import ChatSettings
from server.studio_models import audio_pcm, Engine
from server.studio_runtime import Runtime, context_messages
from server.studio_store import Store, protect
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from server.studio_runtime import StudioSession, DeviceBridge


class StudioStoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'app.db')

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_credentials_encrypted_and_blank_preserves(self):
        self.assertEqual(protect(protect('not-a-real-key'), True), 'not-a-real-key')
        cfg = dict(name='Test', preset='compatible', base_url='http://localhost:1234/v1', kinds=['llm'], api_key='not-a-real-key')
        self.store.save_connection('test', cfg)
        self.assertNotIn('not-a-real-key', json.dumps(self.store.connections()))
        self.store.save_connection('test', {**cfg, 'api_key': None})
        self.assertEqual(self.store.connection('test')['api_key'], 'not-a-real-key')
        self.assertNotIn('not-a-real-key', self.store.db.execute('SELECT secret FROM connections WHERE id="test"').fetchone()[0])

    def test_independent_configs_and_persistent_messages(self):
        a = self.store.create_chat('A')
        b = self.store.create_chat('B')
        cfg = a['config']; cfg['tts']['steps'] = 10
        self.store.update_chat(a['id'], config=cfg)
        self.assertEqual(self.store.chat(b['id'])['config']['tts']['steps'], 5)
        self.store.message(a['id'], 'turn', 'user', 'my name is A')
        self.assertEqual(self.store.chat(b['id'])['messages'], [])
        again = Store(Path(self.tmp.name)/'app.db')
        try:
            self.assertEqual(again.chat(a['id'])['messages'][0]['content'], 'my name is A')
        finally:
            again.db.close()

    def test_api_browse_does_not_activate_and_keys_are_not_returned(self):
        app = create_app(self.store, False)
        with TestClient(app) as c:
            original = c.get('/api/state').json()['status']['active']
            new = c.post('/api/chats', json={'title': 'B'}).json()
            self.assertEqual(c.get('/api/chats/'+new['id']).status_code, 200)
            state = c.get('/api/state').json()
            self.assertEqual(state['status']['active'], original)
            self.assertNotIn('api_key', json.dumps(state))
            self.assertEqual(c.put('/api/defaults', json={'tts': {'steps': 0}}).status_code, 422)
            self.assertEqual(c.post('/api/projects', json={'name': 'voice project'}).status_code, 200)
            self.assertEqual(c.post('/api/chats', json={'title': 'bad', 'project': 'missing'}).status_code, 400)
            self.assertEqual(c.get('/api/state', headers={'Origin':'https://unrelated.example'}).status_code, 403)

    def test_audio_conversion_stereo_24k_to_mono_48k(self):
        pcm = audio_pcm(np.full((24000, 2), .25, dtype=np.float32), 24000)
        samples = np.frombuffer(pcm, dtype='<i2')
        self.assertEqual(len(samples), 48000)
        self.assertAlmostEqual(float(samples[100:-100].mean()), 8191, delta=10)


class FakeProvider:
    def __init__(self, store, settings):
        self.settings = settings
        self.model = settings.model if settings.model != 'auto' else 'test-model'
    async def resolve(self, verify=False): return self
    async def close(self): pass
    async def summarize(self, old, messages): return old + ' Summary: ' + messages[0]['content']
    async def stream(self, messages):
        yield 'answer to ' + messages[-1]['content']


class FakeEngine:
    signature = staticmethod(Engine.signature)
    def __init__(self, store, settings): self.settings = settings
    def load(self):
        if self.settings.tts.model == 'fail': raise ValueError('test load failure')
    def unload(self): pass
    def begin(self): return None
    async def transcribe(self, path, recognition=None): return 'hardware input'
    async def speech(self, text):
        yield bytes(1920)


class StudioRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'app.db')
        self.store.put('references', {'jm-tech': {}})
        self.runtime = Runtime(self.store)
        self.patch1 = patch('server.studio_runtime.Provider', FakeProvider)
        self.patch2 = patch('server.studio_runtime.Engine', FakeEngine)
        self.patch1.start(); self.patch2.start()

    async def asyncTearDown(self):
        self.patch1.stop(); self.patch2.stop()
        self.store.db.close(); self.tmp.cleanup()

    async def test_activation_failure_rolls_back_config_and_active_id(self):
        old = self.runtime.active
        await self.runtime.activate(old)
        new = self.store.create_chat('B')
        cfg = new['config']; cfg['tts']['model'] = 'fail'
        self.store.update_chat(new['id'], config=cfg)
        with self.assertRaisesRegex(ValueError, '准备失败'):
            await self.runtime.activate(new['id'])
        self.assertEqual(self.runtime.active, old)
        self.assertEqual(self.store.get('active'), old)
        self.assertTrue(self.runtime.ready)
        self.assertFalse(self.runtime.switching)

    async def test_summary_is_chat_scoped_original_messages_survive(self):
        a = self.store.create_chat('A')['id']; b = self.store.create_chat('B')['id']
        for i in range(22):
            self.store.message(a, str(i), 'user', 'A private name '+str(i))
            self.store.message(a, str(i), 'assistant', 'ack '+str(i))
        provider = FakeProvider(self.store, ChatSettings().llm)
        messages = await context_messages(self.store, a, provider, 'remember?')
        self.assertEqual(len(self.store.chat(a)['messages']), 44)
        self.assertTrue(self.store.chat(a)['summary'])
        other = await context_messages(self.store, b, provider, 'hello')
        self.assertNotIn('private', json.dumps(other))
        self.assertEqual(self.store.chat(b)['covered'], 0)
        self.assertTrue(any('摘要' in m['content'] for m in messages))

    async def test_cancelled_generation_never_writes_to_new_chat(self):
        a = self.runtime.active; b = self.store.create_chat('B')['id']
        await self.runtime.activate(a)
        entered = asyncio.Event()
        class Slow(FakeProvider):
            async def stream(self, messages):
                yield 'partial'
                entered.set()
                await asyncio.sleep(100)
                yield 'stale'
        async def work():
            async for _ in self.runtime.answer(a, 'my name is A'):
                pass
        with patch('server.studio_runtime.Provider', Slow):
            task = asyncio.create_task(work())
            await asyncio.wait_for(entered.wait(), 2)
            await self.runtime.activate(b)
            self.assertTrue(task.cancelled())
        self.assertEqual(self.store.chat(b)['messages'], [])
        self.assertEqual(self.store.chat(a)['messages'][-1]['state'], 'interrupted')
        self.assertNotIn('stale', self.store.chat(a)['messages'][-1]['content'])

    async def test_summary_failure_keeps_history_and_does_not_send_over_budget(self):
        id = self.runtime.active
        for i in range(22):
            self.store.message(id, str(i), 'user', 'name')
            self.store.message(id, str(i), 'assistant', 'ack')
        class Bad(FakeProvider):
            async def summarize(self, old, messages): raise RuntimeError('summary failed')
        with self.assertRaises(RuntimeError):
            await context_messages(self.store, id, Bad(self.store, ChatSettings().llm), 'hello')
        self.assertEqual(self.store.chat(id)['covered'], 0)
        self.assertEqual(len(self.store.chat(id)['messages']), 44)

    async def test_real_websocket_device_played_ack_and_switch_transport(self):
        r = self.runtime
        a = r.active
        await r.activate(a)
        async def connected(ws):
            session = StudioSession(ws, Path(self.tmp.name), r)
            r.device = session
            try:
                await session.run()
            finally:
                if r.device is session:
                    r.device = None
        async with serve(connected, '127.0.0.1', 0) as server:
            port = server.sockets[0].getsockname()[1]
            async with connect(f'ws://127.0.0.1:{port}/audio') as ws:
                await ws.send(json.dumps(dict(type='hello',protocol_version=1,capture_rate=16000,playback_rate=48000,format='pcm_s16le')))
                hello = json.loads(await ws.recv())
                cap = json.loads(await ws.recv())
                await ws.send(b'\x00\x10' * 320)
                await ws.send(json.dumps(dict(type='capture_end',session_id=hello['session_id'],turn_id=cap['turn_id'])))
                self.assertEqual(json.loads(await ws.recv())['type'], 'capture_end')
                self.assertEqual(json.loads(await ws.recv())['type'], 'play_start')
                self.assertEqual(len(await ws.recv()), 1920)
                self.assertEqual(json.loads(await ws.recv())['type'], 'play_end')
                self.assertTrue(r.busy)
                await ws.send(json.dumps(dict(type='played', session_id=hello['session_id'], turn_id=cap['turn_id'])))
                self.assertEqual(json.loads(await ws.recv())['type'], 'capture_start')
                self.assertFalse(r.busy)
                self.assertEqual(self.store.chat(a)['messages'][0]['content'], 'hardware input')
                b = self.store.create_chat('B')['id']
                await r.activate(b)
                await ws.wait_closed()
                self.assertEqual(self.store.chat(b)['messages'], [])
            async with connect(f'ws://127.0.0.1:{port}/audio') as ws:
                await ws.send(json.dumps(dict(type='hello',protocol_version=1,capture_rate=16000,playback_rate=48000,format='pcm_s16le')))
                new_hello = json.loads(await ws.recv())
                self.assertNotEqual(new_hello['session_id'], hello['session_id'])
                self.assertEqual(json.loads(await ws.recv())['turn_id'], 1)

    async def test_switch_cancels_recognition_before_old_text_is_saved(self):
        r = self.runtime
        a = r.active
        await r.activate(a)
        entered = asyncio.Event()
        async def slow(path, recognition=None):
            entered.set()
            await asyncio.sleep(100)
            return 'old private transcript'
        r.engine.transcribe = slow
        async def run():
            async for _ in DeviceBridge(r).respond(Path(self.tmp.name)/'unused.wav', []):
                pass
        task = asyncio.create_task(run())
        await entered.wait()
        self.assertTrue(r.busy)
        b = self.store.create_chat('B')['id']
        await r.activate(b)
        self.assertTrue(task.cancelled())
        self.assertEqual(self.store.chat(a)['messages'], [])
        self.assertEqual(self.store.chat(b)['messages'], [])

    async def test_switch_closes_synthesis_and_discards_late_audio(self):
        r = self.runtime
        a = r.active
        await r.activate(a)
        entered, closed = asyncio.Event(), asyncio.Event()
        async def speech(text):
            try:
                yield b'first'
                entered.set()
                await asyncio.sleep(100)
                yield b'stale'
            finally:
                closed.set()
        r.engine.speech = speech
        received = []
        async def run():
            async for pcm in r.answer(a, 'hello', speak=True):
                received.append(pcm)
        task = asyncio.create_task(run())
        await entered.wait()
        b = self.store.create_chat('B')['id']
        await r.activate(b)
        self.assertTrue(task.cancelled())
        self.assertTrue(closed.is_set())
        self.assertEqual(received, [b'first'])
        self.assertEqual(self.store.chat(b)['messages'], [])
