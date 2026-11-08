"""Generate ignored firmware settings from private local configuration."""
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
config = json.loads((root / '.private/local.json').read_text(encoding='utf-8'))
values = {
    'DAFE_WIFI_SSID': json.dumps(config['wifi_ssid'], ensure_ascii=True),
    'DAFE_WIFI_PASSWORD': json.dumps(config['wifi_password'], ensure_ascii=True),
    'DAFE_SERVER_PORT': str(int(config['server_port'])),
    'DAFE_DISCOVERY_PORT': str(int(config['discovery_port'])),
    'DAFE_VOLUME_PERCENT': str(max(0, min(100, int(config.get('speaker_volume_percent', 25))))),
}
header = '#pragma once\n' + ''.join(f'#define {k} {v}\n' for k, v in values.items())
(root / 'firmware/main/private_config.h').write_text(header, encoding='utf-8')
print('Generated private firmware configuration; values suppressed')
