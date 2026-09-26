@echo off
rem ===========================================================================
rem  One-click: PC-side algorithm self-check. Touches NOTHING outside the
rem  process -- no serial port, no camera -- so it is safe to run while the UI
rem  is up.
rem
rem  Synthetic waveforms only: clean / noisy / dropped beats / empty sensor /
rem  board reset / the spectrum fallback. It asserts the numbers, so it prints
rem  PASS or FAIL per case and ends with a red count.
rem
rem  KNOWN RED, not a regression: the "clean 48 BPM" case in section [1]. It was
rem  already red before the spectrum fallback went in.
rem
rem  NOTE: keep this file PURE ASCII (cmd.exe reads .bat in the OEM codepage).
rem ===========================================================================

chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0.."

set "PY=D:\Anaconda3\envs\dms\python.exe"
if not exist "%PY%" (
    echo.
    echo   Not found: %PY%
    echo   The check needs the project conda env "dms".
    echo.
    pause
    exit /b 1
)

"%PY%" _scratch\_check_hr_algo.py
set "EC=%ERRORLEVEL%"

rem  The live window's self-check. It also touches nothing (no port, no board):
rem  it renders the WHOLE window on synthetic data through the Agg backend,
rem  asserts the panel shows the product's own numbers rather than recomputing
rem  them, and covers the five "no reading" states. Runs here so the window
rem  cannot rot unnoticed.
"%PY%" _scratch\_hr_live_win.py --selftest
set "EC2=%ERRORLEVEL%"

echo.
echo   Algo check exit code %EC%   = 1 red.
echo   Expected today: exit 1, exactly ONE red -- the "clean 48 BPM" case above.
echo   It was already red before the spectrum fallback went in, so it is not a
echo   regression. Anything more than 1 red, or a different case going red,
echo   means something did break.
echo.
echo   Live window self-check exit code %EC2%   = 0 means all 30 passed.
echo.
echo   Full UTF-8 detail: runs\_hr_algo_check.log
echo                      runs\_hr_live_selftest.log
echo                      runs\_hr_live_selftest.png   -- the rendered window
echo                      runs\_hr_live_selftest.hlog  -- a real session log,
echo                          written by the self-check and read back
echo.
pause
endlocal
