import asyncio
from concurrent.futures import ThreadPoolExecutor
import threading
import unittest

from server.asr import OnlineRecognition


class Recognizer:
    def __init__(self):
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.calls = []
        self.started = threading.Event()

    def decode(self, samples, cache, final):
        self.calls.append((len(samples), id(cache), final))
        self.started.set()
        return '终' if final else '中'


class OnlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_decodes_before_end_and_flushes_exact_chunk(self):
        model = Recognizer()
        stream = OnlineRecognition(model)
        try:
            stream.push(bytes(19200 * 2))
            self.assertTrue(await asyncio.to_thread(model.started.wait, 5))
            self.assertEqual(len(model.calls), 1)
            self.assertFalse(model.calls[0][2])
            self.assertEqual(await stream.finish(), '中终')
            self.assertEqual([c[0] for c in model.calls], [9600, 9600])
            self.assertEqual(model.calls[0][1], model.calls[1][1])
            self.assertTrue(model.calls[-1][2])
        finally:
            await stream.close()
            model.executor.shutdown()

    async def test_cancelled_capture_releases_worker_for_next_turn(self):
        model = Recognizer()
        first = OnlineRecognition(model)
        await first.close()
        second = OnlineRecognition(model)
        try:
            second.push(bytes(640))
            self.assertEqual(await asyncio.wait_for(second.finish(), 5), '终')
        finally:
            await second.close()
            model.executor.shutdown()
