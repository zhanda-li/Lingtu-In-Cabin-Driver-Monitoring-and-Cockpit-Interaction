@echo off
rem Explicit rollback launcher; reuse the original UI and Python discovery.
setlocal
set "DMS_YOLO_SHADOW=0"
set "DMS_FUSION_COMPARE=0"
set "DMS_FUSION_V2_ALLOWED=0"
set "FUSION_MODE=legacy"
call "%~dp0run_ui.bat" %*
endlocal
