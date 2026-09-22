@echo off
rem ============================================================
rem  Double-click this file to start recording.
rem
rem  NOTE: this file must contain ASCII ONLY.
rem  cmd.exe parses .bat files with the system ANSI codepage (GBK on
rem  this machine), so UTF-8 Chinese text here corrupts the parsing
rem  and breaks every following line. All Chinese output is printed
rem  by the Python program instead (config.py forces UTF-8 stdout).
rem ============================================================
chcp 65001 >nul
rem Repair PATH: when cmd is launched from a garbled environment the
rem drive-letter colons get mangled, which breaks the python lookup.
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0"

"D:\Anaconda3\envs\dms\python.exe" tools\record.py %*

echo.
echo --- program exited. press any key to close this window ---
pause >nul
