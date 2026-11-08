"""Package tracked files only. Run after reviewing and staging the release."""
import argparse
import hashlib
from pathlib import Path
import subprocess
import zipfile

ROOT = Path(__file__).resolve().parents[1]
FORBIDDEN = {'.git', '.private', 'runtime', 'models', '.venv', 'node_modules', '__pycache__'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    names = subprocess.check_output(['git', 'ls-files', '-z'], cwd=ROOT).decode('utf-8').split('\0')
    names = [n for n in names if n]
    if not names:
        raise ValueError('Stage reviewed release files first')
    for name in names:
        p = Path(name)
        if FORBIDDEN.intersection(p.parts) or p.name in {'private_config.h', '.env'} or p.suffix in {'.pyc', '.sqlite', '.db', '.elf'}:
            raise ValueError(f'Private/generated file tracked: {name}')
        if p.suffix == '.bin' and not name.startswith('firmware/prebuilt/'):
            raise ValueError(f'Unexpected firmware/backup: {name}')
        if p.suffix.lower() in {'.wav', '.mp3', '.flac'} and name != 'assets/voice/jm-tech.wav':
            raise ValueError(f'Unexpected recording: {name}')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(names):
            archive.write(ROOT / name, 'chat-with-dafeiyu/' + name)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(output.suffix + '.sha256').write_text(f'{digest}  {output.name}\n', encoding='ascii')
    print(f'Packaged {len(names)} tracked files: {output.name}\nSHA256 {digest}')


if __name__ == '__main__':
    main()
