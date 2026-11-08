import asyncio
import json
from pathlib import Path
import struct
import tempfile
import unittest
import wave

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from server.main import handler
from server.protocol import Endpoint, pcm_rms, validate_hello


HELLO = {'type': 'hello', 'protocol_version': 1, 'capture_rate': 16000,
         'playback_rate': 48000, 'format': 'pcm_s16le'}


class PCMTests(unittest.TestCase):
    def test_signed_little_endian(self):
        self.assertAlmostEqual(pcm_rms(struct.pack('<hh', -16384, 16384)), 0.5)
        with self.assertRaises(ValueError):
            pcm_rms(b'\x01')

    def test_wrong_rate_rejected(self):
        with self.assertRaises(ValueError):
            validate_hello({**HELLO, 'capture_rate': 48000})

    def test_vad_uses_audio_duration(self):
        vad = Endpoint()
        self.assertFalse(vad.feed(struct.pack('<h', 4000) * 3200))
        self.assertFalse(vad.feed(bytes(16000)))
        self.assertTrue(vad.feed(bytes(4800)))

    def test_silence_has_bounded_turn(self):
        vad = Endpoint(max_seconds=1)
        self.assertFalse(vad.feed(bytes(16000)))
        self.assertTrue(vad.feed(bytes(16000)))

    def test_waiting_before_speech_does_not_cut_off_new_sentence(self):
        vad = Endpoint(max_seconds=2)
        self.assertFalse(vad.feed(bytes(16000 * 3)))  # 1.5s waiting.
        self.assertFalse(vad.feed(struct.pack('<h', 3000) * 16000))
        self.assertTrue(vad.feed(struct.pack('<h', 3000) * 16000))


class WireTests(unittest.IsolatedAsyncioTestCase):
    async def test_streamed_audio_two_turns_reconnect_and_wav(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)
            async with serve(lambda ws: handler(ws, output), '127.0.0.1', 0) as server:
                port = server.sockets[0].getsockname()[1]
                uri = f'ws://127.0.0.1:{port}/audio'
                for connection in range(2):
                    async with connect(uri) as ws:
                        await ws.send(json.dumps(HELLO))
                        hello = json.loads(await ws.recv())
                        self.assertEqual(hello['mode'], 'mock')
                        for turn in range(1, 3):
                            start = json.loads(await ws.recv())
                            self.assertEqual((start['type'], start['turn_id']), ('capture_start', turn))
                            session = start['session_id']
                            # Long waiting audio is trimmed to 200ms of pre-roll.
                            await ws.send(bytes(12800))
                            # Multiple independent network messages form one recording.
                            for _ in range(10):
                                await ws.send(struct.pack('<h', 3000) * 320)
                            await ws.send(json.dumps({'type': 'capture_end', 'session_id': session, 'turn_id': turn}))
                            self.assertEqual(json.loads(await ws.recv())['type'], 'capture_end')
                            self.assertEqual(json.loads(await ws.recv())['type'], 'play_start')
                            blocks = []
                            while True:
                                frame = await asyncio.wait_for(ws.recv(), 3)
                                if isinstance(frame, str):
                                    self.assertEqual(json.loads(frame)['type'], 'play_end')
                                    break
                                self.assertLessEqual(len(frame), 1920)
                                blocks.append(frame)
                            self.assertEqual(len(blocks), 15)
                            self.assertEqual(sum(map(len, blocks)), 28800)
                            await ws.send(json.dumps({'type': 'played', 'session_id': session, 'turn_id': turn}))
                server.close()
                await server.wait_closed()
                recorded = []
                for path in output.glob('*.wav'):
                    with wave.open(str(path), 'rb') as wav:
                        self.assertEqual((wav.getnchannels(), wav.getsampwidth(), wav.getframerate()), (1, 2, 16000))
                        if wav.getnframes():
                            recorded.append(wav.getnframes())
                self.assertEqual(recorded, [6400] * 4)


if __name__ == '__main__':
    unittest.main()
