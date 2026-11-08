"""Explicit download, not an implicit side effect of application startup."""
from pathlib import Path
import argparse
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from server.paths import ASR_MODEL,TTS_MODEL
from modelscope import snapshot_download
from huggingface_hub import snapshot_download as hf_download

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--tts-source',choices=('modelscope','huggingface'),default='modelscope')
    args=parser.parse_args()
    print('Downloading Paraformer (~0.9GB) and VoxCPM2 (multiple GB).')
    snapshot_download('iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online',local_dir=str(ASR_MODEL))
    if args.tts_source=='modelscope':
        snapshot_download('OpenBMB/VoxCPM2',local_dir=str(TTS_MODEL))
    else:
        hf_download('openbmb/VoxCPM2',local_dir=str(TTS_MODEL))
    print('Model download complete.')
