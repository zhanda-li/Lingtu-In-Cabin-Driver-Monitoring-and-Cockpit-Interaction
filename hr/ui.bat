@echo off
rem ===========================================================================
rem  One-click: start the cockpit web UI. The heart rate shows up live on three
rem  pages (home #rHr, detail #mHr, monitor #mvHr).
rem
rem  This is only a delegate -- the UI itself lives in ui\ and owns its own
rem  arguments, so anything you pass here is forwarded verbatim:
rem      hr\ui.bat                                      live camera (default)
rem      hr\ui.bat --source demo                        canned demo, no camera
rem      hr\ui.bat --source replay:runs\session1.csv
rem
rem  NOTE: keep this file PURE ASCII (cmd.exe reads .bat in the OEM codepage).
rem  The real header, with the why behind every switch, is ui\run_ui.bat.
rem ===========================================================================

call "%~dp0..\ui\run_ui.bat" %*
