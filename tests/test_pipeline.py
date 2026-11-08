import asyncio
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from server.main import handler, Session
from server.pipeline import take_sentences, threaded_chunks


class SentenceTests(unittest.TestCase):
    def test_releases_first_clause_before_final_answer(self):
        ready, rest = take_sentences('你好！今天')
        self.assertEqual(ready, ['你好！'])
        self.assertEqual(rest, '今天')
        self.assertEqual(take_sentences(rest, final=True), (['今天'], ''))


class BridgeTests(unittest.IsolatedAsyncioTestCase):
    async def test_pcm_pacing_does_not_accumulate_windows_timer_rounding(self):
        class Socket:
            async def send(self, data):
                pass
        with tempfile.TemporaryDirectory() as tmp:
            session = Session(Socket(), Path(tmp))
            start = time.perf_counter()
            await session.send_pcm(bytes(96000))
            elapsed = time.perf_counter()-start
            session.close_playback()
        self.assertGreater(elapsed, 0.95)
        self.assertLess(elapsed, 1.3)

    async def test_cancel_closes_producer_with_bounded_backlog(self):
        closed = threading.Event()
        produced = []
        def source():
            try:
                for i in range(10000):
                    produced.append(i)
                    yield bytes(1920)
            finally:
                closed.set()
        iterator = threaded_chunks(source)
        await anext(iterator)
        await asyncio.sleep(0.05)
        await asyncio.wait_for(iterator.aclose(), 2)
        self.assertTrue(closed.is_set())
        self.assertLess(len(produced), 10)

    async def test_producer_failure_surfaces(self):
        def source():
            yield b'12'
            raise ValueError('test failure')
        with self.assertRaises(ValueError):
            async for _ in threaded_chunks(source):
                pass

    async def test_real_path_sends_first_block_before_producer_completes(self):
        release = asyncio.Event()
        class Pipeline:
            mode = 'test_pipeline'
            async def respond(self, path, history):
                yield bytes(1920)
                await release.wait()
                yield bytes(1920)
        with tempfile.TemporaryDirectory() as tmp:
            async with serve(lambda ws: handler(ws, Path(tmp), Pipeline()), '127.0.0.1', 0) as server:
                port = server.sockets[0].getsockname()[1]
                async with connect(f'ws://127.0.0.1:{port}/audio') as ws:
                    await ws.send(json.dumps({'type': 'hello', 'protocol_version': 1,
                                             'capture_rate': 16000, 'playback_rate': 48000,
                                             'format': 'pcm_s16le'}))
                    self.assertEqual(json.loads(await ws.recv())['mode'], 'test_pipeline')
                    start = json.loads(await ws.recv())
                    await ws.send(b'\x00\x10' * 320)
                    await ws.send(json.dumps({'type': 'capture_end', 'session_id': start['session_id'], 'turn_id': 1}))
                    self.assertEqual(json.loads(await ws.recv())['type'], 'capture_end')
                    self.assertEqual(json.loads(await ws.recv())['type'], 'play_start')
                    first = await asyncio.wait_for(ws.recv(), 1)
                    self.assertEqual(first, bytes(1920))
                    self.assertFalse(release.is_set())
                    release.set()
                    self.assertEqual(await ws.recv(), bytes(1920))
                    self.assertEqual(json.loads(await ws.recv())['type'], 'play_end')
