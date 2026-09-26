@echo off
rem ===========================================================================
rem  One-click: raw measurement trace -- "I pressed my finger, why is there no
rem  number?".
rem
rem  CLOSE THE UI FIRST. The serial port is exclusive: while ui\run_ui.bat is
rem  running, this script cannot open COM and reports PermissionError(13).
rem  That message means "the UI has the port", NOT "the board is broken".
rem
rem  What it prints, second by second: hr (and whether it came from the main
rem  path or the spectrum fallback), finger gate, IR DC, envelope, peak, beat
rem  count, valid IBI count, median IBI, spread, spectrum. Then the last eight
rem  intervals and the raw beat timestamps -- that is how you tell a real slow
rem  heart rate from dropped beats, and a doubled count from a real fast one.
rem
rem  It finishes with ONE plain-ASCII verdict line, and writes the full UTF-8
rem  trace to runs\_hr_finger.log.
rem
rem  Usage (both optional):
rem      hr\probe.bat             6 s warm-up, 10 s sampling
rem      hr\probe.bat 8 20        warm up 8 s, sample 20 s
rem
rem  NOTE: keep this file PURE ASCII (cmd.exe reads .bat in the OEM codepage,
rem  and a ")" inside echo text closes an enclosing block).
rem ===========================================================================

chcp 65001 >nul
setlocal
set PYTHONIOENCODING=utf-8

rem Repair PATH first: a garbled inherited environment can mangle the drive
rem colons and break both the python lookup and the cd below.
set "PATH=C:\Windows\System32;C:\Windows;%PATH%"
cd /d "%~dp0.."

rem Plain "python" resolves to the Anaconda BASE env, which has none of the
rem UI's dependencies. Always use the project env.
set "PY=D:\Anaconda3\envs\dms\python.exe"
if not exist "%PY%" (
    echo.
    echo   Not found: %PY%
    echo   The probe needs the project conda env "dms".
    echo.
    pause
    exit /b 1
)

echo.
echo   Press your finger on the sensor now -- cover the whole part, hold still.
echo.

"%PY%" _scratch\_hr_finger_probe.py %*
set "EC=%ERRORLEVEL%"

echo.
echo   Full trace: %~dp0..\runs\_hr_finger.log
echo   Verdict exit code: %EC%   0 = it produced a number, 1 = see the log
echo.
pause
endlocal
