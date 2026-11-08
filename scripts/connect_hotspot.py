"""Wait for the configured hotspot, then join it without touching other profiles."""
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def ssid_present(output, ssid, connected=False):
    label = r'SSID\s*' if connected else r'SSID\s+\d+\s*'
    return re.search(r'^\s*' + label + r':\s*' + re.escape(ssid) + r'\s*$',
                     output, re.MULTILINE) is not None


def profile_xml(ssid, password):
    ns = 'http://www.microsoft.com/networking/WLAN/profile/v1'
    ET.register_namespace('', ns)
    def child(parent, name, value=None):
        node = ET.SubElement(parent, '{'+ns+'}'+name)
        node.text = value
        return node
    root = ET.Element('{'+ns+'}WLANProfile')
    child(root, 'name', ssid)
    child(child(child(root, 'SSIDConfig'), 'SSID'), 'name', ssid)
    child(root, 'connectionType', 'ESS')
    child(root, 'connectionMode', 'manual')
    security = child(child(root, 'MSM'), 'security')
    auth = child(security, 'authEncryption')
    for key, value in [('authentication', 'WPA2PSK'), ('encryption', 'AES'), ('useOneX', 'false')]:
        child(auth, key, value)
    shared = child(security, 'sharedKey')
    for key, value in [('keyType', 'passPhrase'), ('protected', 'false'), ('keyMaterial', password)]:
        child(shared, key, value)
    return ET.tostring(root, encoding='utf-8', xml_declaration=True)


def netsh(*args):
    result = subprocess.run(['netsh', 'wlan', *args], capture_output=True,
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode:
        raise RuntimeError('Windows Wi-Fi command failed, exit '+str(result.returncode))
    # The configured SSID is ASCII; no unrelated network names are logged.
    try:
        return result.stdout.decode('utf-8')
    except UnicodeDecodeError:
        return result.stdout.decode('mbcs', errors='replace')


def main():
    config = json.loads((ROOT/'.private/local.json').read_text(encoding='utf-8'))
    ssid = config['wifi_ssid']
    print('Waiting for the configured hotspot; no test audio will play.', flush=True)
    while not ssid_present(netsh('show', 'interfaces'), ssid, connected=True):
        if ssid_present(netsh('show', 'networks'), ssid):
            if ssid_present(netsh('show', 'interfaces'), ssid, connected=True):
                print('Computer connected to hotspot.', flush=True)
                return
            profile = ROOT/'.private/windows-hotspot.xml'
            existing = subprocess.run(['netsh', 'wlan', 'show', 'profile', 'name='+ssid],
                                      capture_output=True, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
            if existing.returncode != 0:
                profile.write_bytes(profile_xml(ssid, config['wifi_password']))
                netsh('add', 'profile', 'filename='+str(profile), 'user=current')
            netsh('connect', 'name='+ssid, 'ssid='+ssid)
            for _ in range(15):
                time.sleep(1)
                if ssid_present(netsh('show', 'interfaces'), ssid, connected=True):
                    print('Computer connected to hotspot.', flush=True)
                    return
            raise RuntimeError('Windows could not join the configured hotspot')
        time.sleep(5)
    print('Computer already connected to hotspot.', flush=True)


if __name__ == '__main__':
    main()
