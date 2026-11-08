"""Streamed capture/playback; explicit mock or local-model conversation mode."""
import argparse
import asyncio
import contextlib
import json
import logging
import math
from pathlib import Path
import socket
import struct
import uuid
import wave
import ipaddress
import psutil

from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from .protocol import DOWN_BYTES, DOWN_RATE, Endpoint, UP_RATE, validate_hello

LOG = logging.getLogger('dafe')
ROOT = Path(__file__).resolve().parents[1]


class Session:
    def __init__(self, ws, output, pipeline=None):
        self.ws = ws
        self.output = output
        self.session_id = uuid.uuid4().hex
        self.turn = 0
        self.state = 'hello'
        self.writer = self.response = None
        self.endpoint = None
        self.pipeline = pipeline
        self.history = []
        self.path = None
        self.playback_deadline = None
        self.pre_roll = bytearray()
        self.pre_roll_bytes = 6400
        self.recognition = None
        self.playback_writer = None

    def close_playback(self):
        if self.playback_writer is not None:
            self.playback_writer.close()
            self.playback_writer = None

    async def send(self, kind, **extra):
        await self.ws.send(json.dumps({'type': kind, 'session_id': self.session_id,
                                      'turn_id': self.turn, **extra}))

    def close_capture(self):
        if self.writer is not None:
            self.writer.close()
            self.writer = None

    async def start_capture(self):
        self.close_capture()
        if self.recognition:
            await self.recognition.close()
            self.recognition = None
        self.turn += 1
        self.endpoint = Endpoint()
        self.pre_roll.clear()
        self.path = self.output / f'{self.session_id}_{self.turn}.wav'
        self.writer = wave.open(str(self.path), 'wb')
        self.writer.setparams((1, 2, UP_RATE, 0, 'NONE', 'not compressed'))
        self.state = 'capture'
        await self.send('capture_start', sample_rate=UP_RATE, format='pcm_s16le')

    async def respond(self):
        self.close_playback()
        await self.send('capture_end')
        self.playback_deadline = None
        if self.pipeline:
            await self.respond_real()
            return
        await self.send('play_start', sample_rate=DOWN_RATE, channels=1,
                        format='pcm_s16le', mode='mock_tone')
        # Low level, 300ms, tapered test tone. Generate and send one block at a time.
        count = DOWN_BYTES // 2
        total = DOWN_RATE * 3 // 10
        for start in range(0, total, count):
            samples = []
            for i in range(start, min(start + count, total)):
                fade = min(1, i / 480, (total - i - 1) / 480)
                samples.append(round(1000 * fade * math.sin(2 * math.pi * 440 * i / DOWN_RATE)))
            await self.send_pcm(struct.pack('<' + 'h' * len(samples), *samples))
        await self.send('play_end')
        self.close_playback()
        LOG.info('mock tone sent, waiting for hardware playback drain')

    async def send_pcm(self, chunk):
        if self.playback_writer is None:
            folder = self.output / 'playback'
            folder.mkdir(exist_ok=True)
            self.playback_writer = wave.open(str(folder / f'{self.session_id}_{self.turn}.wav'), 'wb')
            self.playback_writer.setparams((1, 2, DOWN_RATE, 0, 'NONE', 'not compressed'))
        loop = asyncio.get_running_loop()
        for offset in range(0, len(chunk), DOWN_BYTES):
            block = chunk[offset:offset + DOWN_BYTES]
            now = loop.time()
            # Absolute deadlines prevent Windows timer quantization accumulating
            # on every 20ms block. Cap catch-up bursts at 40ms of audio.
            self.playback_deadline = max(self.playback_deadline or now, now - 0.04)
            await self.ws.send(block)
            self.playback_writer.writeframesraw(block)
            self.playback_deadline += len(block) / (DOWN_RATE * 2)
            await asyncio.sleep(max(0, self.playback_deadline - loop.time()))

    async def respond_real(self):
        started = False
        recognition = self.recognition
        iterator = (self.pipeline.respond(self.path, self.history, recognition=recognition)
                    if recognition else self.pipeline.respond(self.path, self.history))
        try:
            async for chunk in iterator:
                if len(chunk) % 2:
                    raise ValueError('TTS returned an incomplete sample')
                if not chunk:
                    continue
                if not started:
                    await self.send('play_start', sample_rate=DOWN_RATE, channels=1,
                                    format='pcm_s16le', mode=self.pipeline.mode)
                    started = True
                await self.send_pcm(chunk)
            if started:
                await self.send('play_end')
            else:
                await self.start_capture()
        except asyncio.CancelledError:
            raise
        except ConnectionClosed:
            raise
        except Exception as exc:
            # Do not print provider exception bodies: they can contain request content.
            LOG.error('Conversation failed: %s', type(exc).__name__)
            await self.send('error', message='Conversation failed; listening again')
            await self.send('stop')
            await self.start_capture()
        finally:
            self.close_playback()
            await iterator.aclose()
            if recognition:
                await recognition.close()
                if self.recognition is recognition:
                    self.recognition = None

    async def finish_capture(self):
        self.close_capture()
        if self.pipeline and self.endpoint.voiced == 0:
            await self.start_capture()
            return
        self.state = 'play'
        self.response = asyncio.create_task(self.respond())

    async def playback_finished(self):
        if self.response:
            await self.response
        await self.start_capture()

    async def run(self):
        try:
            async for raw in self.ws:
                if self.response and self.response.done():
                    if self.response.cancelled():
                        self.response = None
                    else:
                        self.response.result()
                if isinstance(raw, bytes):
                    if self.state != 'capture':
                        continue
                    if not raw or len(raw) % 2 or len(raw) > 12800:
                        raise ValueError('Invalid PCM packet length')
                    had_speech = self.endpoint.voiced > 0
                    ended = self.endpoint.feed(raw)
                    if had_speech:
                        self.writer.writeframesraw(raw)
                        if self.recognition:
                            self.recognition.push(raw)
                    elif self.endpoint.voiced:
                        if self.pipeline and hasattr(self.pipeline, 'begin_recognition'):
                            self.recognition = self.pipeline.begin_recognition()
                            if self.recognition:
                                self.recognition.push(bytes(self.pre_roll))
                                self.recognition.push(raw)
                        self.writer.writeframesraw(self.pre_roll)
                        self.writer.writeframesraw(raw)
                        self.pre_roll.clear()
                    else:
                        self.pre_roll.extend(raw)
                        if self.pre_roll_bytes:
                            del self.pre_roll[:-self.pre_roll_bytes]
                        else:
                            self.pre_roll.clear()
                    if ended:
                        await self.finish_capture()
                    continue
                message = json.loads(raw)
                if not isinstance(message, dict):
                    raise ValueError('Control frame must be an object')
                kind = message.get('type')
                if self.state == 'hello':
                    if kind != 'hello':
                        raise ValueError('hello required')
                    validate_hello(message)
                    await self.send('hello', protocol_version=1,
                                    mode=self.pipeline.mode if self.pipeline else 'mock')
                    await self.start_capture()
                    continue
                if kind == 'ping':
                    await self.send('pong')
                    continue
                if message.get('session_id') != self.session_id or message.get('turn_id') != self.turn:
                    await self.send('error', message='Stale session or turn')
                    continue
                if kind == 'capture_end' and self.state == 'capture':
                    await self.finish_capture()
                elif kind == 'played' and self.state == 'play':
                    await self.playback_finished()
                elif kind == 'stop':
                    if self.response:
                        self.response.cancel()
                    # Flush hardware immediately; model-thread cleanup may take longer.
                    await self.send('stop')
                    if self.response:
                        with contextlib.suppress(asyncio.CancelledError):
                            await self.response
                    await self.start_capture()
        finally:
            self.close_capture()
            self.close_playback()
            if self.response:
                self.response.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self.response
            if self.recognition:
                await self.recognition.close()


async def handler(ws, output, pipeline=None):
    if ws.request.path != '/audio':
        await ws.close(1008, 'Use /audio')
        return
    try:
        await Session(ws, output, pipeline).run()
    except ConnectionClosed:
        LOG.info('Audio client disconnected')
    except (ValueError, json.JSONDecodeError) as exc:
        LOG.warning('Protocol rejected: %s', exc)
        await ws.close(1008, 'Invalid audio protocol')
    except RuntimeError as exc:
        safe_reason = str(exc) if str(exc) in {
            'ASR cannot keep up with audio', 'Recognizer has already ended'} else type(exc).__name__
        LOG.error('Audio processing failed: %s; closing this session', safe_reason)
        await ws.close(1011, 'Audio processing failed')


async def beacon(port, discovery_port):
    payload = json.dumps({'service': 'dafe-voice', 'protocol_version': 1,
                          'port': port, 'path': '/audio'}).encode()
    while True:
        for name, addresses in psutil.net_if_addrs().items():
            state = psutil.net_if_stats().get(name)
            if not state or not state.isup:
                continue
            for address in addresses:
                if address.family != socket.AF_INET or not address.netmask:
                    continue
                interface = ipaddress.IPv4Interface(f'{address.address}/{address.netmask}')
                if interface.ip.is_loopback or interface.ip.is_link_local or interface.network.prefixlen >= 31:
                    continue
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                try:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    sock.bind((address.address, 0))
                    sock.setblocking(False)
                    await asyncio.get_running_loop().sock_sendto(
                        sock, payload, (str(interface.network.broadcast_address), discovery_port))
                except OSError:
                    LOG.warning('Discovery broadcast unavailable on an interface; retrying')
                finally:
                    sock.close()
        await asyncio.sleep(2)


async def main(args):
    args.output.mkdir(parents=True, exist_ok=True)
    pipeline = None
    if args.mode == 'real':
        from .pipeline import RealPipeline
        pipeline = RealPipeline.configured()
    try:
        if pipeline:
            await pipeline.start()
        active_client = asyncio.Lock()
        async def one_client(ws):
            if active_client.locked():
                await ws.close(1013, 'One ESP32 session at a time')
                return
            async with active_client:
                await handler(ws, args.output, pipeline)
        async with serve(one_client, args.host, args.port,
                         max_size=16384, max_queue=16, ping_interval=15, ping_timeout=15):
            task = asyncio.create_task(beacon(args.port, args.discovery_port))
            LOG.info('%s audio service listening on %s:%s/audio', args.mode, args.host, args.port)
            try:
                await asyncio.Future()
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
    finally:
        if pipeline:
            await pipeline.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--mode', choices=['mock', 'real'], default='mock')
    parser.add_argument('--port', type=int, default=18765)
    parser.add_argument('--discovery-port', type=int, default=18767)
    parser.add_argument('--output', type=Path, default=ROOT / 'runtime' / 'captures')
    logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')
    try:
        asyncio.run(main(parser.parse_args()))
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        # Provider error bodies may contain credential or request details.
        LOG.error('Service startup failed (%s). Check local API configuration and runtime dependencies.',
                  type(exc).__name__)
        raise SystemExit(1)
