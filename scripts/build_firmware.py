"""Run from an ESP-IDF 5.3.4 terminal. Build a private ASCII-path copy, never flash."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    idf = os.environ.get('IDF_PATH')
    if not idf or not (Path(idf)/'tools/idf.py').exists():
        raise RuntimeError('Open the ESP-IDF 5.3.4 terminal first; IDF_PATH is not configured')
    subprocess.run([sys.executable,str(ROOT/'scripts/prepare_firmware.py')],check=True)
    name = hashlib.sha256(str(ROOT).encode()).hexdigest()[:12]
    mirror = Path(os.environ.get('DAFE_BUILD_DIR',str(Path(tempfile.gettempdir())/'dafe-build'/name)))
    if not str(mirror).isascii() or ' ' in str(mirror):
        raise RuntimeError('Set DAFE_BUILD_DIR to an ASCII path without spaces, e.g. C:\\dafe-build')
    marker = mirror/'.dafe-source.json'
    if mirror.exists() and (not marker.exists() or json.loads(marker.read_text())['source']!=str(ROOT/'firmware')):
        raise RuntimeError('Build directory is not owned by this source; choose another DAFE_BUILD_DIR')
    mirror.mkdir(parents=True,exist_ok=True)
    marker.write_text(json.dumps({'source':str(ROOT/'firmware')}),encoding='utf-8')
    for p in (ROOT/'firmware').rglob('*'):
        rel=p.relative_to(ROOT/'firmware')
        if not p.is_file() or any(x in ('build','build-ascii','managed_components','prebuilt') for x in rel.parts) or p.name in ('sdkconfig','sdkconfig.old'):
            continue
        dst=mirror/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(p,dst)
    shutil.copy2(ROOT/'firmware/sdkconfig.defaults',mirror/'sdkconfig')
    env=dict(os.environ,PYTHONUTF8='1',IDF_CCACHE_ENABLE='0')
    runtime=ROOT/'runtime';runtime.mkdir(exist_ok=True)
    with (runtime/'firmware-build.log').open('w',encoding='utf-8') as log:
        subprocess.run([sys.executable,str(Path(idf)/'tools/idf.py'),'-C',str(mirror),'--no-ccache','build'],
                       check=True,env=env,stdout=log,stderr=subprocess.STDOUT)
    output=runtime/'firmware';output.mkdir(exist_ok=True)
    for rel in ('dafe_voice.bin','bootloader/bootloader.bin','partition_table/partition-table.bin','flasher_args.json'):
        dst=output/rel;dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(mirror/'build'/rel,dst)
    print('Build passed: runtime/firmware. This command did not flash a device.')


if __name__=='__main__':main()
