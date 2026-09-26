@echo off
rem ===========================================================================
rem  One-click: LIVE heart-rate window -- a standalone window (NOT a web page)
rem  showing the pulse wave, the IR-DC trend and every raw number, in real time.
rem
rem  CLOSE THE UI FIRST. The serial port is exclusive: while ui\run_ui.bat is
rem  running, this window cannot open COM and shows a red line
rem  "PORT BUSY - close the UI?" . That means "the UI has the port",
rem  NOT "the board is broken".
rem
rem  What you see:
rem    - the band-passed pulse wave (25 Hz decimated, last 10 s) with a dot on
rem      every beat the algorithm registered;
rem    - the IR DC trend over the last 60 s (that is the finger gate's input);
rem    - one line per gate: value / threshold, and whether it passed. When there
rem      is no number on screen, THAT line says which gate is holding it back.
rem
rem  Stale data is greyed out and labelled: if the serial link stops, the
rem  buffers keep their last values and would otherwise draw a frozen wave that
rem  looks perfectly plausible.
rem
rem  EVERY SESSION IS LOGGED. The window draws but used to record nothing, so a
rem  problem could only be read off the screen as a single instant -- which beat
rem  broke the NN chain, how the span climbed, whether samples were dropped. The
rem  log keeps all three, as three kinds of CSV rows, so it can be replayed
rem  offline. It lands in runs\_hr_live_<date>_<time>.log -- one file per session,
rem  never overwritten.
rem      S rows  ~1 Hz state snapshot (gates, hr, rmssd, pi, finger)
rem      B rows  EVERY registered beat, with its interval in ms
rem      T rows  step histogram: a healthy link is 10 ms almost every time
rem  Read it back with:  python _scratch\_hr_live_log.py
rem
rem  Keys: q or ESC to quit, or just close the window.
rem
rem  Usage:
rem      hr\live.bat              live window
rem      hr\live.bat --selftest   headless self-check (no port, no board)
rem      hr\live.bat --log P      write the session log to P instead
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
    echo   The live window needs the project conda env "dms".
    echo.
    pause
    exit /b 1
)

"%PY%" _scratch\_hr_live_win.py %*
set "EC=%ERRORLEVEL%"

echo.
echo   Exit code %EC%  -- in live mode: 0 = you closed the window normally,
echo   non-zero = it could not start, read the message above.
echo   With --selftest: the number of checks that went red, so 0 = all passed.
echo   Detail: runs\_hr_live_selftest.log
echo.
echo   The session log path was printed above, as
echo     hr live win: log=D:\...\runs\_hr_live_YYYYMMDD_HHMMSS.log
echo   Read it back with:  python _scratch\_hr_live_log.py
echo.
pause
endlocal
