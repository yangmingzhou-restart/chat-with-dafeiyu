"""Record a short PCM WAV or request a low-level tone without Wi-Fi."""
import argparse
import json
from pathlib import Path
import time
import wave

import numpy as np
import serial

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('command', choices=['status', 'tone', 'record'])
    parser.add_argument('--port', default='COM4')
    args = parser.parse_args()
    if args.command == 'tone':
        raise SystemExit('Standalone test tones disabled at user request; only conversation playback is permitted')
    port = serial.Serial(port=None, baudrate=921600, timeout=0.2)
    port.dtr = port.rts = False
    port.port = args.port
    frames = []
    lines = []
    complete = False
    expected = None
    with port:
        time.sleep(2)
        port.reset_input_buffer()
        port.write({'status': b's', 'tone': b't', 'record': b'r'}[args.command])
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            line = port.readline().decode('ascii', errors='replace').strip()
            if not line:
                continue
            if line.startswith('DAFE_PCM '):
                payload = bytes.fromhex(line[9:])
                if len(payload) != 640:
                    raise RuntimeError('Unexpected PCM frame length')
                frames.append(payload)
            else:
                lines.append(line)
                if line.startswith('DAFE_PCM_BEGIN '):
                    _, rate, expected = line.split()
                    if rate != '16000':
                        raise RuntimeError('Unexpected capture rate')
                    expected = int(expected)
                if (args.command == 'status' and line.startswith('DAFE_STATUS ')) or (
                        args.command == 'tone' and line == 'DAFE_TONE_DRAINED'):
                    complete = True
                    break
                if args.command == 'record' and line.startswith('DAFE_PCM_END '):
                    complete = expected == len(frames) == int(line.split()[-1])
                    break
    runtime = ROOT / 'runtime'
    runtime.mkdir(exist_ok=True)
    report = {'command': args.command, 'complete': complete, 'status_lines': lines}
    if frames:
        pcm = b''.join(frames)
        with wave.open(str(runtime / 'usb-microphone.wav'), 'wb') as wav:
            wav.setparams((1, 2, 16000, 0, 'NONE', 'not compressed'))
            wav.writeframes(pcm)
        samples = np.frombuffer(pcm, dtype='<i2').astype(np.float64)
        report.update(samples=len(samples), seconds=len(samples)/16000,
                      peak=float(np.max(np.abs(samples)) / 32768),
                      rms=float(np.sqrt(np.mean(samples**2))/32768),
                      clipping=float(np.mean(np.abs(samples) >= 32767)))
    (runtime / f'usb-{args.command}.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report))
    if not complete:
        raise SystemExit('USB diagnostic did not complete; see runtime report')


if __name__ == '__main__':
    main()
