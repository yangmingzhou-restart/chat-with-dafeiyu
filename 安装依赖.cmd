@echo off
setlocal
cd /d "%~dp0"
py -3.12 -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install torch==2.6.0 torchaudio==2.6.0 --index-url https://download.pytorch.org/whl/cu126
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation complete. Next: first-run configuration and model downloads. See docs\INSTALL.md.
pause
exit /b 0
:failed
echo Installation failed. See docs\INSTALL.md. Do not ignore this error.
pause
exit /b 1
