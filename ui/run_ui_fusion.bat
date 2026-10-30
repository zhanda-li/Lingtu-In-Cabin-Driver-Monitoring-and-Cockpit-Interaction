@echo off
rem ASCII only. Reuse the established launcher, browser and UI configuration.
rem Starts real YOLO inference and side-by-side comparison; Legacy stays selected.
rem V2 switching still requires a passing matching backend validation report.
setlocal
set "DMS_YOLO_SHADOW=1"
set "DMS_YOLO_BACKEND=onnx"
set "DMS_FUSION_COMPARE=1"
set "DMS_FUSION_V2_ALLOWED=1"
set "FUSION_MODE=legacy"
call "%~dp0run_ui.bat" %*
endlocal
