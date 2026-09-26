@echo off
rem ===========================================================================
rem  Xiaoqi cockpit UI - double click this file to start.
rem
rem  IMPORTANT: this file must stay ASCII only.
rem  cmd.exe parses .bat with the OEM codepage (GBK on this machine), so any
rem  Chinese text here corrupts the lines that follow it. All Chinese output is
rem  printed by the python side instead (PYTHONIOENCODING=utf-8 below).
rem
rem  What it does:
rem    1. cd to the repo root (this file lives in <root>\ui)
rem    2. build the derived images once, if they are missing
rem    3. start the UI server and open Edge in kiosk mode
rem
rem  WHY NOT JUST "python": the project has its own conda env (dms) that owns
rem  torch / mediapipe / cv2. Plain `python` resolves to the Anaconda BASE env,
rem  which has none of them - the camera mode would die on import cv2.
rem
rem  DEFAULT IS THE LIVE CAMERA - changed 2026-09-24 at the user's request
rem  ("I only want the realtime picture"). The on-screen source switcher was
rem  removed the same day, so the source is decided ONLY by this argument.
rem      run_ui.bat                                      live camera, real model
rem      run_ui.bat --source cam:data\raw\fatigue\fatigue_02.mp4
rem      run_ui.bat --source demo                       canned demo arc, no camera
rem      run_ui.bat --source replay:runs\session1.csv
rem  A --source typed here OVERRIDES the built-in cam below: argparse keeps the
rem  LAST --source it is given, and %* is appended after it.
rem
rem  IMPORTANT (2026-09-24 late, user: "only connect the camera when I click"):
rem  "--source cam" now means THE CAMERA IS AVAILABLE, not "grab it now".
rem  Nothing takes the device at startup any more. The camera is opened ONLY by
rem  the "connect camera" button in the top-right of the driving-monitor page,
rem  and it is released again after 12s with no page open - after that release
rem  you must click it again. Opening or refreshing a page does NOT connect it.
rem  The startup banner says which state you are in; trust it over this comment.
rem
rem  The camera is an EXCLUSIVE device. While the UI owns it, do NOT also run
rem  live_fuse.bat - whoever grabs it second goes black. Before you click
rem  "connect camera", running live_fuse.bat is safe.
rem ===========================================================================

chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8

rem Repair PATH: a garbled inherited environment can mangle the drive-letter
rem colons and break both the python lookup and the cd below.
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0.."

set PY=
for %%C in (
    "D:\Anaconda3\envs\dms\python.exe"
    "%USERPROFILE%\anaconda3\envs\dms\python.exe"
    "%USERPROFILE%\miniconda3\envs\dms\python.exe"
    "C:\ProgramData\Anaconda3\envs\dms\python.exe"
) do (
    if not defined PY if exist %%C set PY=%%~C
)
rem  NOTE: keep parentheses OUT of echo text inside a ( ) block.
rem  cmd.exe's block parser counts a ")" as the end of the block even when it
rem  sits inside plain echo text - or inside quotes. The old line here read
rem  "... python env (conda env "dms")." and the parser closed the block at that
rem  ")", leaving the trailing "." as a stray token, which is what produced
rem  " . was unexpected at this time." and the window flashing shut.
if not defined PY (
    echo.
    echo   Could not find the project python env - conda env "dms".
    echo   Looked for Anaconda3\envs\dms\python.exe in the usual places.
    echo   Falling back to whatever "python" is on PATH -camera mode will
    echo   probably fail unless that env has torch + mediapipe + cv2.
    echo.
    set PY=python
)

if not exist "ui\web\assets\bg.jpg" (
    echo Building background image ...
    "!PY!" ui\make_assets.py
)

echo.
echo Using python: !PY!
echo Starting UI server. Press Ctrl+C in this window to stop.
echo.

rem  -u so the banner and any traceback show up immediately instead of sitting
rem     in the stdout buffer when the window is scrolled.
rem  --source cam is the built-in default (see the header). Anything the user
rem  passes in %* wins, because argparse keeps the LAST --source it sees.
"!PY!" -u ui\server.py --open --source cam %*

set EC=%ERRORLEVEL%
if not "%EC%"=="0" (
    echo.
    echo   Server exited with code %EC%.
    echo.
    echo   If it failed opening the camera, either close whatever else holds it
    echo   - live_fuse.bat, a webcam app - or run without it:
    echo       run_ui.bat --source demo
    echo.
    pause
)
endlocal
