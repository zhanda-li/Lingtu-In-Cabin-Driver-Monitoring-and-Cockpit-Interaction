@echo off
rem ===========================================================================
rem  Install the OPTIONAL local speech recognition engine (openai-whisper).
rem
rem  Double click this file. No arguments = install the packages and then fetch
rem  the 142 MB model. Nothing here is needed to RUN the UI: without it the
rem  microphone button still works, it just only has the browser's speech
rem  recognition to work with. See ui/asr.py for why there are two paths.
rem
rem  *** THIS FILE MUST STAY ASCII ONLY ***
rem  cmd.exe parses a .bat with the OEM codepage (GBK on this machine), so any
rem  Chinese text here corrupts the lines that follow it. Every Chinese message
rem  is printed by the python side instead (PYTHONIOENCODING=utf-8 below).
rem
rem  *** KEEP PARENTHESES OUT OF echo TEXT INSIDE A ( ) BLOCK ***
rem  cmd.exe's block parser counts a ")" as the end of the block even when it
rem  sits inside plain echo text. See the long note in run_ui.bat.
rem
rem  *** WHY THIS IS NOT IN requirements.txt ***
rem  openai-whisper needs numba, numba needs llvmlite, and llvmlite puts an
rem  UPPER BOUND on numpy. This machine runs numpy 2.2.6 + torch + mediapipe,
rem  and mediapipe is picky about the numpy version. If pip moves numpy aside,
rem  what breaks is NOT speech input - it is cam mode, i.e. the demo itself.
rem  So the install is deliberately conservative:
rem    - whisper goes in with --no-deps, so pip cannot walk the dep tree
rem    - the four packages it actually needs are listed by hand in
rem      ui/requirements-asr.txt
rem    - pip gets a constraint pinning numpy to the version installed NOW
rem  If something genuinely needs a different numpy, pip refuses and says so.
rem  Better to fail loudly than to break the camera quietly.
rem
rem  Usage:
rem    install_asr.bat                 install packages, then fetch the model
rem    install_asr.bat --check         only report the state, change nothing
rem    install_asr.bat --fetch-model   only fetch the model
rem    install_asr.bat --mirror URL    fetch the model from a mirror
rem    install_asr.bat --python PATH   use a specific python.exe
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
set "MIRROR="

:args
if "%~1"=="" goto args_done
if /i "%~1"=="--check"       set "MODE=check"
if /i "%~1"=="--fetch-model" set "MODE=fetch"
if /i "%~1"=="--help"        set "MODE=help"
if /i "%~1"=="--mirror"      set "MIRROR=%~2"
if /i "%~1"=="--python"      set "PY=%~2"
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

if /i "!MODE!"=="check" goto check
if /i "!MODE!"=="fetch" goto fetch

rem ---------------------------------------------------------------------------
echo --- 1. snapshot the environment BEFORE touching anything ---
echo.
set "BEFORE=%TEMP%\xq_asr_env_before.json"
"!PY!" -u ui\env_snapshot.py --save "!BEFORE!"
if errorlevel 1 goto failed

echo.
echo --- 2. install openai-whisper, with --no-deps ---
echo.
"!PY!" -m pip install --no-deps openai-whisper -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto pip_failed

echo.
echo --- 3. install the four packages it needs, numpy pinned by constraint ---
echo.
set "PINS=%TEMP%\xq_asr_pins.txt"
"!PY!" -c "import numpy;print('numpy=='+numpy.__version__)" > "!PINS!"
echo constraint file: !PINS!
type "!PINS!"
"!PY!" -m pip install -r ui\requirements-asr.txt -c "!PINS!" -i https://pypi.tuna.tsinghua.edu.cn/simple
if errorlevel 1 goto pip_failed

echo.
echo --- 4. check the environment AFTER ---
echo.
"!PY!" -u ui\env_snapshot.py --compare "!BEFORE!"
if errorlevel 1 goto env_changed

echo.
echo --- 5. what the UI will now report ---
echo.
"!PY!" -u ui\asr.py
if errorlevel 1 goto failed

:fetch
echo.
echo --- fetching the model ---
echo.
set "MARG="
if defined MIRROR set "MARG=--fetch-mirror !MIRROR!"
"!PY!" -u ui\asr.py --fetch !MARG!
if errorlevel 1 goto model_failed

echo.
echo --- how fast it actually is on THIS machine ---
echo.
"!PY!" -u ui\asr.py --bench
echo.
echo Done. The UI picks this up the next time you start run_ui.bat.
echo.
pause
endlocal
exit /b 0

:check
echo --- current state, changing nothing ---
echo.
"!PY!" -u ui\env_snapshot.py
echo.
"!PY!" -u ui\asr.py
echo.
pause
endlocal
exit /b 0

:no_python
echo.
echo   Could not find the project python env - conda env "dms".
echo.
echo   Looked for Anaconda3\envs\dms\python.exe in the usual places, and did
echo   NOT fall back to whatever "python" is on PATH. That fallback is right
echo   for run_ui.bat but wrong here: plain "python" is the Anaconda BASE env,
echo   and installing whisper and its dependencies into the wrong env is a
echo   mistake that is very annoying to undo.
echo.
echo   Point it at the right one explicitly:
echo       install_asr.bat --python "D:\Anaconda3\envs\dms\python.exe"
echo.
pause
endlocal
exit /b 1

:env_changed
echo.
echo   Stopping here: something in the environment moved, see the list above.
echo   Fix that first - the camera path is worth more than speech input.
echo   When the versions are back, re-run:  ui\install_asr.bat --fetch-model
echo.
pause
endlocal
exit /b 1

:pip_failed
echo.
echo   pip failed. Nothing else was touched, the UI still runs as before.
echo   The usual causes: no network, or the mirror is unreachable.
echo   Try again, or use the default index instead of the tuna mirror.
echo.
pause
endlocal
exit /b 1

:model_failed
rem The python side returns a distinct code per cause; do not guess at it here.
rem 2 = whisper itself is not installed, 3 = the model name is not one whisper
rem knows, 1 = the download itself failed. Telling someone with cause 2 to go
rem fix their network would be worse than saying nothing.
if "!ERRORLEVEL!"=="2" goto need_packages
if "!ERRORLEVEL!"=="3" goto bad_model_name
echo.
echo   Only the model download failed. The URL lives on
echo   openaipublic.azureedge.net and may be slow or unreachable here.
echo   Options:
echo     1. retry later, or from a proxied network
echo     2. use a mirror:  ui\install_asr.bat --fetch-model --mirror URL
echo        the mirror must keep the /sha256/name.pt tail of the URL -
echo        whisper checks the file against the hash embedded in that path
echo   Until then the UI says "no local model" and uses the browser path only.
echo.
pause
endlocal
exit /b 1

:need_packages
echo.
echo   openai-whisper is not installed yet, so there is nothing to download
echo   the model with. Run this file with NO arguments first:
echo.
echo       ui\install_asr.bat
echo.
pause
endlocal
exit /b 1

:bad_model_name
echo.
echo   The model name in ui\config.json is not one whisper knows.
echo   Use "base". See the list printed above for what this whisper version
echo   does offer. Nothing was downloaded.
echo.
pause
endlocal
exit /b 1

:failed
echo.
echo   Something above failed, see the message. Nothing was left half-done
echo   that the UI depends on: the UI runs without any of this.
echo.
pause
endlocal
exit /b 1

:help
echo.
echo   install_asr.bat                 install packages, then fetch the model
echo   install_asr.bat --check         only report the state, change nothing
echo   install_asr.bat --fetch-model   only fetch the model
echo   install_asr.bat --mirror URL    fetch the model from a mirror
echo   install_asr.bat --python PATH   use a specific python.exe
echo.
pause
endlocal
exit /b 0
