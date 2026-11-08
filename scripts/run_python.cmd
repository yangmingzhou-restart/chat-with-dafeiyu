@echo off
setlocal
cd /d "%~dp0.."
if defined DAFE_PYTHON (
  "%DAFE_PYTHON%" -X utf8 %*
) else if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -X utf8 %*
) else (
  py -3.12 -X utf8 %*
)
exit /b %errorlevel%
