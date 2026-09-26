@echo off
rem ===========================================================================
rem  Xiaoqi cockpit UI - CAMERA mode. Double click this file to start.
rem
rem  Same as run_ui.bat, except the UI opens the camera itself and runs the
rem  real fatigue model inside this process. This is the mode for the live
rem  demo, and the screen shows the driver's genuine current state.
rem
rem  WHY A SEPARATE FILE: double clicking a .bat cannot pass arguments, and
rem  camera mode needs "--source cam". So this wrapper forwards that one flag
rem  to run_ui.bat - the python lookup, the PATH repair and the browser launch
rem  then live in exactly one place and cannot drift apart between the two.
rem
rem  IMPORTANT: the camera is an EXCLUSIVE device. While this window is open,
rem  do NOT also run live_fuse.bat. Whoever grabs the camera second goes black.
rem
rem  Keep this file ASCII only, and keep parentheses out of echo text inside
rem  any ( ) block - see the long note in run_ui.bat for what that costs.
rem ===========================================================================

echo.
echo   Camera mode - the UI is taking over the camera now.
echo   Do NOT start live_fuse.bat while this window is open.
echo.

rem  %~dp0 ends with a backslash, so this points at run_ui.bat next to us.
rem  %* forwards anything else you append, e.g. run_ui_cam.bat --port 8800
call "%~dp0run_ui.bat" --source cam %*
