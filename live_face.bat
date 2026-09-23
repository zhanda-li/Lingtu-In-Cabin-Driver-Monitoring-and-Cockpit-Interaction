@echo off
rem ============================================================
rem  Double-click this file to watch branch 2 (the face branch)
rem  live on the camera.
rem
rem  This is a SCRATCH tool, not part of the demo. It exists to
rem  answer one question: is PERCLOS responding to the EYES, or
rem  is it just following the head? Watch PERCLOS and HEAD dPITCH
rem  together: eyes only -> PERCLOS moves, dPITCH does not.
rem
rem  NOTE: this file must contain ASCII ONLY.
rem  cmd.exe parses .bat files with the system ANSI codepage (GBK on
rem  this machine), so UTF-8 Chinese text here corrupts the parsing
rem  and breaks every following line. All Chinese output is printed
rem  by the Python program instead (config.py forces UTF-8 stdout).
rem
rem  Any arguments are passed through to _scratch\live_face.py, e.g.
rem      live_face.bat --cam 0
rem      live_face.bat --selftest
rem ============================================================
chcp 65001 >nul
rem Repair PATH: when cmd is launched from a garbled environment the
rem drive-letter colons get mangled, which breaks the python lookup.
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0"

echo Sit upright, keep your head still, close your eyes for 2-3 s,
echo open, repeat. Watch PERCLOS and HEAD dPITCH together.
echo Needs a light source: below ~12 fps the readings get coarse.
echo.

"D:\Anaconda3\envs\dms\python.exe" _scratch\live_face.py %*

echo.
echo --- program exited. press any key to close this window ---
pause >nul
