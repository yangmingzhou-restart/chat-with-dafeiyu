"""PCM and wire-format rules shared by the mock service and checks."""
import array
import math
import sys

UP_RATE = 16000
DOWN_RATE = 48000
BLOCK_MS = 20
UP_BYTES = UP_RATE * 2 * BLOCK_MS // 1000
DOWN_BYTES = DOWN_RATE * 2 * BLOCK_MS // 1000


def pcm_rms(data):
    if not data or len(data) % 2:
        raise ValueError('PCM must contain complete int16 samples')
    samples = array.array('h', data)
    if sys.byteorder != 'little':
        samples.byteswap()
    return math.sqrt(sum(x * x for x in samples) / len(samples)) / 32768


def validate_hello(message):
    expected = {'protocol_version': 1, 'capture_rate': UP_RATE,
                'playback_rate': DOWN_RATE, 'format': 'pcm_s16le'}
    if any(message.get(k) != v for k, v in expected.items()):
        raise ValueError('Unsupported audio protocol or rates')


class Endpoint:
    """VAD based on sample count, independent of network packet boundaries."""
    def __init__(self, threshold=0.002, silence_ms=650, max_seconds=15):
        self.threshold = threshold
        self.silence_samples = UP_RATE * silence_ms // 1000
        self.limit = UP_RATE * max_seconds
        self.total = self.quiet = self.voiced = 0
        self.speech_elapsed = 0

    def feed(self, data):
        level = pcm_rms(data)
        count = len(data) // 2
        self.total += count
        if self.voiced:
            self.speech_elapsed += count
        if level >= self.threshold:
            if not self.voiced:
                self.speech_elapsed = count
            self.voiced += count
            self.quiet = 0
        else:
            self.quiet += count
        speech_end = self.voiced >= UP_RATE // 5 and self.quiet >= self.silence_samples
        return speech_end or self.speech_elapsed >= self.limit or (not self.voiced and self.total >= self.limit)
