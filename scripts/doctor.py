"""Read-only installation checks, without API calls, downloads or speaker output."""
import importlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.paths import ASR_MODEL,TTS_MODEL,VOX_SOURCE

def main():
    results={}
    for name in ('fastapi','uvicorn','openai','websockets','numpy','soundfile','scipy','funasr','torch','torchaudio'):
        try:importlib.import_module(name);results[name]='OK'
        except Exception as e:results[name]=type(e).__name__
    try:
        sys.path.insert(0,str(VOX_SOURCE));from voxcpm import VoxCPM
        results['vendored_voxcpm']='OK'
    except Exception as e:results['vendored_voxcpm']=type(e).__name__
    import torch
    results.update(cuda=torch.cuda.is_available(),asr_weights=(ASR_MODEL/'model.pt').exists(),
                   tts_weights=(TTS_MODEL/'model.safetensors').exists(),web_bundle=(ROOT/'web/dist/index.html').exists(),
                   hotspot_config=(ROOT/'.private/local.json').exists())
    print(json.dumps(results,indent=2))
    return 0 if all(results.get(k)=='OK' for k in ('fastapi','uvicorn','openai','websockets','numpy','soundfile','scipy','funasr','torch','torchaudio','vendored_voxcpm')) else 1

if __name__=='__main__':raise SystemExit(main())
