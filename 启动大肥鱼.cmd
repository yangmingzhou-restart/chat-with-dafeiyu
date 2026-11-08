@echo off
call "%~dp0scripts\run_python.cmd" scripts\launch_studio.py
if errorlevel 1 pause
