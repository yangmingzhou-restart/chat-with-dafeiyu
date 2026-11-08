"""Stop only our loopback studio, with normal task/model cleanup."""
import json
import urllib.request

URL = 'http://127.0.0.1:18766'
try:
    with urllib.request.urlopen(URL+'/api/health', timeout=2) as response:
        if json.load(response).get('app') != 'dafe-studio':
            raise RuntimeError('Port belongs to another application')
    request = urllib.request.Request(URL+'/api/shutdown', method='POST', data=b'{}', headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request, timeout=30):
        print('Studio is shutting down; the speaker remains silent.')
except urllib.error.URLError:
    print('Studio is not running, or its shutdown endpoint is unavailable.')
