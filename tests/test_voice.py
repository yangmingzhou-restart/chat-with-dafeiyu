import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from server.pipeline import RealPipeline
from server.voice import load_fixed_voice


class ReferenceTests(unittest.TestCase):
    def test_pins_same_audio_for_reference_and_continuation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'jm-tech.wav').write_bytes(b'reference audio')
            (root / 'jm-tech.txt').write_text('reference transcript', encoding='utf-8')
            manifest = root / 'manifest.json'
            manifest.write_text(json.dumps({
                'audio_sha256': hashlib.sha256(b'reference audio').hexdigest(),
                'transcript_sha256': hashlib.sha256(b'reference transcript').hexdigest()}))
            calls = []
            def build(**kwargs):
                calls.append(kwargs)
                return {'mode': 'ref_continuation'}
            with patch('server.voice.REFERENCE_DIR', root), patch('server.voice.MANIFEST', manifest):
                load_fixed_voice(SimpleNamespace(build_prompt_cache=build))
                self.assertEqual(calls[0]['reference_wav_path'], calls[0]['prompt_wav_path'])
                self.assertEqual(calls[0]['prompt_text'], 'reference transcript')
                (root / 'jm-tech.wav').write_bytes(b'another voice')
                with self.assertRaisesRegex(RuntimeError, 'checksum'):
                    load_fixed_voice(SimpleNamespace(build_prompt_cache=build))
                self.assertEqual(len(calls), 1)


class SynthesisTests(unittest.TestCase):
    def test_all_clauses_reuse_reference_and_close_generator(self):
        calls, closed = [], []
        class Wave:
            def squeeze(self, axis): return self
            def cpu(self): return self
            def numpy(self): return np.array([-1.0, 0.0, 1.0])
        def generate(**kwargs):
            calls.append(kwargs)
            try:
                yield Wave(), None, None
                yield Wave(), None, None
            finally:
                closed.append(True)
        pipeline = RealPipeline('unused-test-key')
        pipeline.tts = SimpleNamespace(tts_model=SimpleNamespace(generate_with_prompt_cache_streaming=generate))
        pipeline.voice_cache = {'mode': 'ref_continuation'}
        for text in ('first clause', 'second clause'):
            stream = pipeline.synthesize(text)
            self.assertEqual(np.frombuffer(next(stream), dtype='<i2').tolist(), [-32767, 0, 32767])
            stream.close()
        self.assertEqual(len(closed), 2)
        self.assertTrue(all(call['prompt_cache'] is pipeline.voice_cache for call in calls))
        self.assertTrue(all(call['seed'] == 0 for call in calls))
        self.assertFalse(pipeline.model_lock.locked())

    def test_missing_reference_never_generates_another_voice(self):
        with self.assertRaisesRegex(RuntimeError, 'reference voice'):
            next(RealPipeline('unused-test-key').synthesize('hello'))
