@echo off
rem ===========================================================================
rem  Install the OPTIONAL online voice engine (edge-tts) for the mascot's speech.
rem
rem  Double click this file. Nothing here is needed to RUN the UI: the voice
rem  works out of the box through the browser's speechSynthesis, which already
rem  has Microsoft's Chinese neural voices. What this installs is the online
rem  voice for the SERVER-SIDE fallback path in ui/tts.py - the one that used
rem  to be stuck with Windows SAPI "Huihui", the shrill robotic voice the user
rem  described as a pixie.
rem
rem  *** THIS FILE MUST STAY ASCII ONLY ***
rem  cmd.exe parses a .bat with the OEM codepage (GBK on this machine), so any
rem  Chinese text here corrupts the lines that follow it. Everything the user
rem  needs to read is printed by the python side (PYTHONIOENCODING=utf-8 below).
rem
rem  *** KEEP PARENTHESES OUT OF echo TEXT INSIDE A ( ) BLOCK ***
rem  cmd.exe's block parser counts a ")" as the end of the block even when it
rem  sits inside plain echo text. See the long note in run_ui.bat.
rem
rem  *** WHY THIS IS NOT IN requirements.txt ***
rem  Same reason as ui/install_asr.bat: the root requirements.txt means "install
rem  this and the README flow runs". Speech is optional - the UI runs without
rem  any of it - so it gets its own file plus a snapshot/compare wrapper.
rem
rem  *** WHY THIS ONE IS SAFE, UNLIKE install_asr.bat ***
rem  edge-tts 7.2.8 needs aiohttp, certifi, tabulate, typing-extensions. None
rem  of them touches numba/llvmlite, so pip cannot move numpy out from under
rem  mediapipe, so this cannot break cam mode. install_asr.bat needs all that
rem  ceremony because whisper CAN break it. This one keeps the snapshot anyway -
rem  it costs two seconds and it means "nothing moved" is a printed fact rather
rem  than a promise.
rem
rem  Usage:
rem    install_tts.bat                 install the packages, then list the voices
rem    install_tts.bat --check         only report the state, change nothing
rem    install_tts.bat --voices        only list the online Chinese voices
rem    install_tts.bat --python PATH   use a specific python.exe
rem
rem  To actually HEAR a voice, use the page, not this file: the page lets you
rem  audition all 14 Chinese voices and switch between them in one click.
rem    run_ui.bat, then open  http://127.0.0.1:8765/voice.html
rem ===========================================================================

chcp 65001 >nul
setlocal enabledelayedexpansion
set PYTHONIOENCODING=utf-8

rem Repair PATH: a garbled inherited environment can mangle the drive-letter
rem colons and break both the python lookup and the cd below.
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0.."

set "PY="
set "MODE=install"

:args
if "%~1"=="" goto args_done
if /i "%~1"=="--check"  set "MODE=check"
if /i "%~1"=="--voices" set "MODE=voices"
if /i "%~1"=="--help"   set "MODE=help"
if /i "%~1"=="--python" set "PY=%~2"
shift
goto args
:args_done

rem --help must not depend on finding python.
if /i "!MODE!"=="help" goto help

rem Resolve the project env only if --python was not given.
if not defined PY (
    for %%C in (
        "D:\Anaconda3\envs\dms\python.exe"
        "%USERPROFILE%\anaconda3\envs\dms\python.exe"
        "%USERPROFILE%\miniconda3\envs\dms\python.exe"
        "C:\ProgramData\Anaconda3\envs\dms\python.exe"
    ) do (
        if not defined PY if exist %%C set PY=%%~C
    )
)
if not defined PY goto no_python

echo.
echo Using python: !PY!
echo Repo root   : %CD%
echo.

if /i "!MODE!"=="check"  goto check
if /i "!MODE!"=="voices" goto voices

rem ---------------------------------------------------------------------------
echo --- 1. snapshot the environment BEFORE touching anything ---
echo.
set "BEFORE=%TEMP%\xq_tts_env_before.json"
"!PY!" -u ui\env_snapshot.py --save "!BEFORE!"
if errorlevel 1 goto failed

echo.
echo --- 2. install edge-tts ---
echo.
"!PY!" -m pip install -r ui\requirements-tts.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto pip_failed

echo.
echo --- 3. check the environment AFTER ---
echo.
"!PY!" -u ui\env_snapshot.py --compare "!BEFORE!"
if errorlevel 1 goto env_changed

echo.
echo --- 4. what the UI will now report ---
echo.
"!PY!" -u ui\tts.py
if errorlevel 1 goto failed

echo.
echo Done. The UI picks this up the next time you start run_ui.bat.
echo If the online voice still does not come out, the reason is shown on the
echo voice page:  http://127.0.0.1:8765/voice.html
echo.
pause
endlocal
exit /b 0

:check
echo --- current state, changing nothing ---
echo.
"!PY!" -u ui\env_snapshot.py
echo.
"!PY!" -u ui\tts.py --edge-voices
echo.
echo   --check stops here on purpose: it must not make any sound, and it must
echo   not change anything. It also does NOT run the full self test - that one
echo   speaks several lines and takes half a minute. Run it by hand when you
echo   want it:
echo.
echo       set PYTHONIOENCODING=utf-8
echo       "!PY!" ui\tts.py
echo.
pause
endlocal
exit /b 0

:voices
"!PY!" -u ui\tts.py --edge-voices
echo.
pause
endlocal
exit /b 0

:no_python
echo.
echo   Could not find the project python env - conda env "dms".
echo.
echo   This deliberately does NOT fall back to whatever "python" is on PATH.
echo   Plain "python" is the Anaconda BASE env, and installing into the wrong
echo   env is a mistake that is very annoying to undo.
echo.
echo   Point it at the right one explicitly:
echo       install_tts.bat --python "D:\Anaconda3\envs\dms\python.exe"
echo.
pause
endlocal
exit /b 1

:env_changed
echo.
echo   Stopping here: something in the environment moved, see the list above.
echo   edge-tts is not supposed to move anything - check what else changed
echo   before going further.
echo.
pause
endlocal
exit /b 1

:pip_failed
echo.
echo   pip failed. Nothing else was touched, the UI still runs as before.
echo   The usual causes: no network, or the mirror is unreachable.
echo   Note the server fallback path also NEEDS the network at run time - this
echo   install is useless on an offline machine, but it is never harmful:
echo   without it the fallback simply uses the Windows voice as it always did.
echo.
pause
endlocal
exit /b 1

:failed
echo.
echo   Something above failed, see the message. The UI runs without any of this.
echo.
pause
endlocal
exit /b 1

:help
echo.
echo   install_tts.bat                 install the packages, then list the voices
echo   install_tts.bat --check         only report the state, change nothing
echo   install_tts.bat --voices        only list the online Chinese voices
echo   install_tts.bat --python PATH   use a specific python.exe
echo.
echo   To hear a voice, start run_ui.bat and open /voice.html - that page
echo   auditions all the Chinese voices and switches between them.
echo.
pause
endlocal
exit /b 0
