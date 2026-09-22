@echo off
rem ============================================================
rem  Double-click this file for the realtime demo (camera).
rem
rem  NOTE: this file must contain ASCII ONLY.
rem  cmd.exe parses .bat files with the system ANSI codepage (GBK on
rem  this machine), so UTF-8 Chinese text here corrupts the parsing
rem  and breaks every following line. All Chinese output is printed
rem  by the Python program instead (config.py forces UTF-8 stdout).
rem
rem  Any arguments are passed through to src\live.py, e.g.
rem      live.bat --replay data\raw\fatigue\fatigue_02.mp4
rem      live.bat --seconds 30
rem      live.bat --serial COM3
rem ============================================================
chcp 65001 >nul
rem Repair PATH: when cmd is launched from a garbled environment the
rem drive-letter colons get mangled, which breaks the python lookup.
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0"

if "%~1"=="" (
  echo Starting realtime demo on the camera. Press Q or ESC in the window to quit.
  echo Need a light source: below ~12 fps the pose data gets coarse.
  echo.
)

"D:\Anaconda3\envs\dms\python.exe" src\live.py %*

echo.
echo --- program exited. press any key to close this window ---
pause >nul
