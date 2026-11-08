"""One pinned reference for every utterance; never fall back to an unconditioned voice."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_DIR = ROOT / 'assets/voice'
MANIFEST = ROOT / 'docs/reference-voice.json'


def load_fixed_voice(model):
    manifest = json.loads(MANIFEST.read_text(encoding='utf-8'))
    audio = REFERENCE_DIR / 'jm-tech.wav'
    transcript = REFERENCE_DIR / 'jm-tech.txt'
    for path, key in ((audio, 'audio_sha256'), (transcript, 'transcript_sha256')):
        if hashlib.sha256(path.read_bytes()).hexdigest() != manifest[key]:
            raise RuntimeError('Fixed voice reference checksum mismatch')
    text = transcript.read_text(encoding='utf-8-sig').strip()
    if not text:
        raise RuntimeError('Fixed voice transcript is empty')
    cache = model.build_prompt_cache(prompt_wav_path=str(audio), prompt_text=text,
                                     reference_wav_path=str(audio))
    if cache.get('mode') != 'ref_continuation':
        raise RuntimeError('Fixed reference voice was not prepared')
    return cache
