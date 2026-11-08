"""Create only this user's private configuration. Never ships credentials."""
import argparse
import getpass
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description='Configure your own Wi-Fi and DeepSeek key')
    parser.add_argument('--download-models', action='store_true')
    args = parser.parse_args()
    private = ROOT/'.private'
    private.mkdir(exist_ok=True)
    config_path = private/'local.json'
    current = json.loads(config_path.read_text(encoding='utf-8')) if config_path.exists() else {}
    print('Public demo firmware uses SSID DAFE_DEMO and password dafe-demo-1234.')
    print('Use those hotspot values for prebuilt firmware, or rebuild for your own values.')
    ssid = input('2.4GHz WPA2 Wi-Fi SSID [DAFE_DEMO]: ').strip() or current.get('wifi_ssid','DAFE_DEMO')
    password = getpass.getpass('Wi-Fi password [Enter keeps previous/public demo value]: ') or current.get('wifi_password','dafe-demo-1234')
    if not 8 <= len(password) <= 63:
        raise ValueError('WPA2 Wi-Fi password must contain 8-63 characters')
    config = dict(wifi_ssid=ssid, wifi_password=password, server_port=18765, discovery_port=18767, speaker_volume_percent=25)
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding='utf-8')
    key = getpass.getpass('Your DeepSeek API key [Enter preserves existing key / configure later in UI]: ').strip()
    from server.studio_store import Store
    store = Store()
    try:
        if key:
            store.save_connection('deepseek', dict(name='DeepSeek',preset='deepseek',kinds=['llm'],
                                                  base_url='https://api.deepseek.com/v1',api_key=key))
    finally:
        store.db.close()
    print('Private setup saved. No API key or Wi-Fi password was printed.')
    if args.download_models:
        import subprocess
        print('Downloading Paraformer (~0.9GB) and VoxCPM2 (multiple GB); this needs internet and disk space.')
        subprocess.run([sys.executable,str(ROOT/'scripts/download_models.py')],check=True)
        print('Models downloaded. See docs/MODELS.md for original tested hashes and version differences.')


if __name__ == '__main__':
    main()
