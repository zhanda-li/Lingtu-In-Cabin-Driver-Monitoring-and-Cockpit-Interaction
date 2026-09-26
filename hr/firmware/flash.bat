@echo off
REM ===========================================================================
REM  Flash the built firmware into the HPM5300EVK on-board QSPI NOR via openocd.
REM
REM  Run build.bat first -- this script only writes an existing output/demo.elf.
REM
REM  The on-board FT2232 provides both JTAG (channel A) and the console UART
REM  (channel B, shows up as "USB Serial Port (COMn)"). openocd only drives JTAG;
REM  the UART is read separately by dms_project/ui/serial_hr.py (see hr\README.md).
REM
REM  NOTE: keep this file PURE ASCII (cmd.exe reads .bat in the OEM codepage).
REM
REM  Usage (flags are order-independent, use at most one of each):
REM    flash.bat            flash the SOFT float build
REM    flash.bat hf         flash the HARD float build (build.bat hf)
REM    flash.bat reset      just reset the target and run
REM    flash.bat hf reset   reset only, hard float build dir (same effect)
REM ===========================================================================

setlocal

set "SDK_ENV=D:\sdk_env_v1.12.1"
set "OPENOCD=%SDK_ENV%\tools\openocd\openocd.exe"
set "CFG=%~dp0tools\openocd_hpm5300evk.cfg"

REM %~dp0 has a trailing backslash -> strip it (must match build.bat exactly).
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"

set "HF="
set "RESET="
if /i "%~1"=="hf"    set "HF=1"
if /i "%~2"=="hf"    set "HF=1"
if /i "%~1"=="reset" set "RESET=1"
if /i "%~2"=="reset" set "RESET=1"

REM Same path build.bat writes to -- keep the two in sync.
set "BUILD_DIR=%APP_DIR%\build_hpm5300evk_flash_xip_debug"
if defined HF set "BUILD_DIR=%BUILD_DIR%_hf"
set "ELF=%BUILD_DIR%\output\demo.elf"

REM openocd -c takes a TCL string, and inside a TCL quoted string a backslash is
REM an escape character -- passing a Windows path verbatim silently eats every
REM separator: D:\sdk_env... arrives as D:sdk_env... and openocd fails with
REM "couldn't open". Forward slashes are inert in TCL and fine for openocd.
set "ELF_TCL=%ELF:\=/%"

if defined RESET (
    echo [openocd] reset run
    "%OPENOCD%" -f "%CFG%" -c "init; reset run; shutdown"
    goto done
)

if not exist "%ELF%" (
    echo [ERROR] %ELF% not found - run build.bat first
    exit /b 1
)

echo [openocd] flashing %ELF%
"%OPENOCD%" -f "%CFG%" -c "init; halt; flash write_image erase %ELF_TCL%; verify_image %ELF_TCL%; reset run; shutdown"
if errorlevel 1 (
    echo [ERROR] flash failed
    exit /b 1
)
echo [ok] flashed and verified

:done
endlocal
