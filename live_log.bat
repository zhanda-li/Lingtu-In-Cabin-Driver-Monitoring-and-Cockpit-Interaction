@echo off
rem ============================================================
rem  Same as live.bat, but also writes every decision to live.csv
rem  so tools\live_report.py can grade the run afterwards.
rem
rem  Double-click it. Nothing to type.
rem
rem  ASCII ONLY in this file -- see the note in live.bat.
rem ============================================================
chcp 65001 >nul
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0"

echo Starting realtime demo on the camera, logging to live.csv
echo Press Q or ESC in the window to quit.
echo Need a light source: below ~12 fps the pose data gets coarse.
echo.

"D:\Anaconda3\envs\dms\python.exe" src\live.py --log-probs live.csv

echo.
echo --- done. live.csv is in this folder. press any key to close ---
pause >nul
