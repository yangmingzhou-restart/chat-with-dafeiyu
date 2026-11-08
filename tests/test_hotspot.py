import sys
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from connect_hotspot import profile_xml, ssid_present


class HotspotTests(unittest.TestCase):
    def test_only_exact_ssid_is_matched(self):
        scan = 'SSID 1 : DEMO_TEST_NETWORK-guest\nSSID 2 : DEMO_TEST_NETWORK\n'
        self.assertTrue(ssid_present(scan, 'DEMO_TEST_NETWORK'))
        self.assertFalse(ssid_present('SSID 1 : DEMO_TEST_NETWORK-guest\n', 'DEMO_TEST_NETWORK'))
        self.assertFalse(ssid_present('BSSID : DEMO_TEST_NETWORK\n', 'DEMO_TEST_NETWORK', connected=True))
        self.assertTrue(ssid_present('    SSID : DEMO_TEST_NETWORK\r\n', 'DEMO_TEST_NETWORK', connected=True))

    def test_profile_escapes_values_and_keeps_manual_connection_mode(self):
        root = ET.fromstring(profile_xml('test&<ssid>', 'test&<password>'))
        ns = {'w': 'http://www.microsoft.com/networking/WLAN/profile/v1'}
        self.assertEqual(root.find('w:name', ns).text, 'test&<ssid>')
        self.assertEqual(root.find('w:connectionMode', ns).text, 'manual')
        self.assertEqual(root.find('.//w:keyMaterial', ns).text, 'test&<password>')
