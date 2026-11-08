"""Portable defaults. Settings UI can override model directories per conversation."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODEL_ROOT = Path(os.environ.get('DAFE_MODEL_ROOT', str(ROOT/'models'))).expanduser().resolve()
ASR_MODEL = Path(os.environ.get('DAFE_ASR_MODEL_PATH', str(MODEL_ROOT/'paraformer-zh-streaming')))
TTS_MODEL = Path(os.environ.get('DAFE_TTS_MODEL_PATH', str(MODEL_ROOT/'VoxCPM2')))
VOX_SOURCE = Path(os.environ.get('DAFE_VOXCPM_SOURCE', str(ROOT/'third_party/VoxCPM/src')))
