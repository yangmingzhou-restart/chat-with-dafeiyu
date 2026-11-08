import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import httpx
import numpy as np
from openai import AsyncOpenAI
import soundfile as sf

from server.studio_config import ChatSettings
from server.studio_models import Engine, Provider
from server.studio_store import Store


class ProviderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = Store(Path(self.tmp.name)/'app.db')
        self.store.save_connection('compatible-test', dict(name='test', preset='compatible',
            base_url='http://provider.test/v1', kinds=['llm','asr','tts'], api_key='unit-secret'))

    async def asyncTearDown(self):
        self.store.db.close(); self.tmp.cleanup()

    async def test_llm_request_auth_stream_and_deepseek_thinking(self):
        captured = []
        async def handle(request):
            captured.append(request)
            events = ['data: '+json.dumps({'id':'c','object':'chat.completion.chunk','choices':[{'index':0,'delta':{'content':v}}]})+'\n\n' for v in ('hello',' world')]
            return httpx.Response(200, text=''.join(events)+'data: [DONE]\n\n', headers={'content-type':'text/event-stream'})
        cfg = ChatSettings().llm
        self.store.save_connection('deepseek', dict(name='test DS',preset='deepseek',base_url='http://provider.test/v1',kinds=['llm'],api_key='unit-secret'))
        cfg.model = 'test-model'
        provider = Provider(self.store, cfg)
        await provider.client.close()
        provider.client = AsyncOpenAI(api_key='unit-secret', base_url='http://provider.test/v1',
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        try:
            text = ''.join([v async for v in provider.stream([{'role':'user','content':'test'}])])
        finally:
            await provider.close()
        self.assertEqual(text, 'hello world')
        self.assertEqual(captured[0].url.path, '/v1/chat/completions')
        self.assertEqual(captured[0].headers['authorization'], 'Bearer unit-secret')
        self.assertEqual(json.loads(captured[0].content)['thinking'], {'type':'disabled'})

    async def test_external_tts_wav_is_decoded_and_resampled(self):
        cfg = ChatSettings()
        cfg.tts.connection = 'compatible-test'; cfg.tts.model = 'test-tts'
        engine = Engine(self.store, cfg)
        wav = io.BytesIO(); sf.write(wav, np.ones((2400,2))*.1, 24000, format='WAV', subtype='PCM_16')
        calls = []
        async def handle(request):
            calls.append(json.loads(request.content))
            return httpx.Response(200, content=wav.getvalue(), headers={'content-type':'audio/wav'})
        original = AsyncOpenAI
        def client(**kwargs):
            return original(**kwargs, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        with patch('openai.AsyncOpenAI', client):
            pcm = b''.join([v async for v in engine.speech('test')])
        self.assertEqual(len(pcm), 9600)
        self.assertFalse(pcm.startswith(b'RIFF'))
        self.assertEqual(calls[0]['response_format'], 'wav')

    async def test_external_asr_sends_wav_file_not_pcm_json(self):
        cfg = ChatSettings(); cfg.asr.connection='compatible-test'; cfg.asr.model='test-asr'
        engine = Engine(self.store, cfg)
        path = Path(self.tmp.name)/'mic.wav'; sf.write(path,np.zeros(1600),16000)
        captured = []
        async def handle(request):
            captured.append(request)
            return httpx.Response(200,json={'text':'recognized'})
        original = AsyncOpenAI
        def client(**kwargs):
            return original(**kwargs,http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)))
        with patch('openai.AsyncOpenAI',client):
            result = await engine.transcribe(path)
        self.assertEqual(result,'recognized')
        self.assertEqual(captured[0].url.path,'/v1/audio/transcriptions')
        self.assertIn(b'RIFF',captured[0].content)
        self.assertIn('multipart/form-data',captured[0].headers['content-type'])
