"""Back up and flash only a classic 4MB ESP32, using the caller's selected COM port."""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]


def tool(port,*args):
    result=subprocess.run([sys.executable,'-m','esptool','--chip','esp32','--port',port,'--baud','115200',*map(str,args)],
                          stdout=subprocess.PIPE,stderr=subprocess.STDOUT,encoding='utf-8',errors='replace')
    if result.returncode:
        raise RuntimeError('esptool failed: '+result.stdout[-1500:])
    return result.stdout


def backup(port):
    info=tool(port,'flash_id')
    if '4MB' not in info:
        raise RuntimeError('This release is tested on 4MB flash only. Inspect your board before flashing.')
    result=tool(port,'read_mac');mac=re.search(r'MAC:\s*([0-9a-fA-F:]{17})',result)
    if not mac:raise RuntimeError('Cannot identify device MAC')
    identity=mac.group(1).replace(':','').lower()
    folder=ROOT/'.private/flash-backups';folder.mkdir(parents=True,exist_ok=True)
    image=folder/(identity+'.bin');meta=folder/(identity+'.json')
    if image.exists() or meta.exists():
        if not image.exists() or not meta.exists():raise RuntimeError('Incomplete existing backup; inspect it, do not overwrite')
        m=json.loads(meta.read_text())
        if image.stat().st_size!=4194304 or hashlib.sha256(image.read_bytes()).hexdigest()!=m['sha256'] or not m.get('verified'):
            raise RuntimeError('Original backup verification failed; refusing to overwrite it or flash')
        return image
    part=folder/(identity+'.part')
    tool(port,'read_flash','0','0x400000',part)
    if part.stat().st_size!=4194304:raise RuntimeError('Backup size is not 4MB')
    tool(port,'verify_flash','0',part)
    part.replace(image)
    meta.write_text(json.dumps({'mac':identity,'bytes':4194304,'sha256':hashlib.sha256(image.read_bytes()).hexdigest(),
                               'verified':True,'created':datetime.now().isoformat()},indent=2),encoding='utf-8')
    print('Original 4MB flash backup verified and retained in .private/flash-backups.')
    return image


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--port',required=True,help='Your board port, e.g. COM4 (not fixed to the author port)')
    p.add_argument('--artifacts',type=Path,default=ROOT/'firmware/prebuilt')
    p.add_argument('--backup-only',action='store_true')
    args=p.parse_args()
    if not args.backup_only:
        folder=args.artifacts.resolve()
        manifest=json.loads((folder/'SHA256SUMS.json').read_text(encoding='utf-8')) if (folder/'SHA256SUMS.json').exists() else None
        mapping={'0x1000':'bootloader/bootloader.bin','0x8000':'partition_table/partition-table.bin','0x10000':'dafe_voice.bin'}
        for relative in mapping.values():
            file=folder/relative
            if not file.exists():raise RuntimeError('Firmware artifact missing: '+relative)
            if manifest and hashlib.sha256(file.read_bytes()).hexdigest()!=manifest['files'][relative]:
                raise RuntimeError('Firmware checksum mismatch')
    backup(args.port)
    if args.backup_only:return
    command=['write_flash','--flash_mode','dio','--flash_freq','40m','--flash_size','4MB']
    for address,relative in mapping.items():command.extend([address,str(folder/relative)])
    result=tool(args.port,*command)
    log=ROOT/'runtime';log.mkdir(exist_ok=True)
    (log/('flash-'+datetime.now().strftime('%Y%m%d-%H%M%S')+'.log')).write_text(result,encoding='utf-8')
    print('Flash completed with esptool verification. Original device backup was not overwritten.')


if __name__=='__main__':main()
