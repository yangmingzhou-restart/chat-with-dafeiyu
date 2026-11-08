"""Windows double-click entrypoint; reuses a running studio and never runs npm."""
import ctypes
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
URL = 'http://127.0.0.1:18766'


def running():
    try:
        with urllib.request.urlopen(URL + '/api/health', timeout=1) as response:
            return json.load(response).get('app') == 'dafe-studio'
    except Exception:
        return False


def main():
    if running():
        webbrowser.open(URL)
        return
    kernel = ctypes.windll.kernel32
    kernel.CreateMutexW.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.ReleaseMutex.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    mutex = kernel.CreateMutexW(None, False, 'Local\\DAFE_STUDIO_LAUNCH')
    try:
        # A second click waits for the first launch rather than starting another model process.
        result = ctypes.windll.kernel32.WaitForSingleObject(mutex, 30000)
        if result not in (0, 0x80):
            raise RuntimeError('工作台正在启动，请稍后重试')
        if running():
            webbrowser.open(URL)
            return
        for port in (18765, 18766):
            with socket.socket() as probe:
                if probe.connect_ex(('127.0.0.1', port)) == 0:
                    raise RuntimeError(f'端口{port}正被其他服务使用，请先关闭旧语音服务后再启动工作台')
        if not (ROOT/'web/dist/index.html').exists():
            raise RuntimeError('缺少预构建界面，请查看docs/USAGE.md')
        runtime = ROOT/'runtime'
        runtime.mkdir(exist_ok=True)
        env = dict(os.environ, PYTHONUTF8='1', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
        with (runtime/'studio.log').open('a', encoding='utf-8') as out, (runtime/'studio-errors.log').open('a', encoding='utf-8') as err:
            process = subprocess.Popen([sys.executable, '-X', 'utf8', '-u', '-m', 'server.studio_app'], cwd=ROOT,
                stdout=out, stderr=err, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
        (runtime/'studio-process.json').write_text(json.dumps({'pid':process.pid}), encoding='utf-8')
        for _ in range(50):
            if running():
                webbrowser.open(URL)
                return
            if process.poll() is not None:
                raise RuntimeError('服务启动失败，请查看runtime/studio-errors.log')
            time.sleep(.5)
        raise RuntimeError('服务尚未响应，请查看runtime/studio-errors.log；不要重复启动模型')
    finally:
        ctypes.windll.kernel32.ReleaseMutex(mutex)
        ctypes.windll.kernel32.CloseHandle(mutex)


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, str(exc), '大肥鱼工作台', 0x10)
        raise SystemExit(1)
