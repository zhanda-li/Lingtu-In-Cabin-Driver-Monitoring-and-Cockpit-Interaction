@echo off
REM ===========================================================================
REM  Generate + build the heart-rate node firmware (HPM5300EVK, flash_xip, debug).
REM
REM  This is exactly what start_gui.exe runs under the hood -- kept here so the
REM  build is reproducible from the command line instead of only through the GUI.
REM
REM  Produces:
REM    <builddir>\build.ninja                                -> ninja can rebuild
REM    <builddir>\segger_embedded_studio\hr_node.emProject   -> open in SES to flash
REM
REM  NOTE: keep this file PURE ASCII. cmd.exe reads .bat in the OEM codepage
REM  (GBK on Chinese Windows), so UTF-8 Chinese comments corrupt the parser.
REM
REM  Usage:
REM    build.bat            generate (if needed) + build, SOFT float (default)
REM    build.bat gen        generate only
REM    build.bat hf         build HARD float (ilp32d) into a separate build dir
REM    build.bat hf gen     hard float, generate only
REM
REM  Why two float modes: the HPM5361 hart reports F/D in misa (hardware FPU
REM  present), yet the default build is soft float (-mabi=ilp32). Hard float is
REM  therefore a build-config choice, not a hardware limit. The default
REM  soft-float build is the intended one -- "hf" is kept only for parity with
REM  the CAN project and is not flashed.
REM
REM  Float math: since 2026-09-26 src/hr_algo.c carries a band-pass filter, so
REM  libm is linked and there IS float math -- about 2000 cycles per sample at
REM  100 Hz, i.e. 0.04% of the 480 MHz core. The ACQUISITION hot path (DMA ISR
REM  -> the two rings -> the D line) is still pure integer: no float there.
REM  hf is still not flipped, because 0.04% buys nothing.
REM
REM  The toolchain is multilib: rv32imafdc_zicsr_zba_zbb_zbc_zbs/ilp32d exists
REM  as a real library set, which is what makes this linkable at all.
REM ===========================================================================

setlocal

set "SDK_ENV=D:\sdk_env_v1.12.1"
set "HPM_SDK_BASE=%SDK_ENV%\hpm_sdk"
set "GNURISCV_TOOLCHAIN_PATH=%SDK_ENV%\toolchains\rv32imac_zicsr_zifencei_multilib_b_ext-win"
set "HPM_SDK_TOOLCHAIN_VARIANT=gcc"
set "CMAKE_EXE=%SDK_ENV%\tools\cmake\bin\cmake.exe"
set "NINJA_DIR=%SDK_ENV%\tools\ninja"
set "OPENOCD_DIR=%SDK_ENV%\tools\openocd"

REM openocd.exe must be ON PATH: segger.cmake locates it with
REM find_program(OPENOCD openocd), which only searches PATH -- an OPENOCD env
REM var alone is not enough. Without it the .emProject is generated with no
REM debug target and SES cannot flash.
set "PATH=%OPENOCD_DIR%;%NINJA_DIR%;%PATH%"

REM %~dp0 has a trailing backslash, which cmake dislikes inside quotes -> strip it
set "APP_DIR=%~dp0"
set "APP_DIR=%APP_DIR:~0,-1%"

REM Order-independent flags: accept "hf" and "gen" in either position.
set "HF="
set "GENONLY="
if /i "%~1"=="hf"  set "HF=1"
if /i "%~2"=="hf"  set "HF=1"
if /i "%~1"=="gen" set "GENONLY=1"
if /i "%~2"=="gen" set "GENONLY=1"

REM RV_ARCH / RV_ABI are read by cmake/toolchain.cmake as cache variables, so a
REM plain -D on the configure line overrides the ilp32 defaults.
REM
REM Do NOT spell out _zba_zbb_zbc_zbs here: soc/HPM5300/HPM5361/CMakeLists.txt
REM appends it unconditionally, and listing it twice makes gcc reject the
REM -march string with "extension 'zba' appear more than one time".
REM
REM zifencei must be spelled out: passing any RV_ARCH containing "_" skips the
REM auto-append block in cmake/toolchain.cmake, and the SDK needs fence.i.
REM gcc's multilib matcher then accepts the zifencei superset and still resolves
REM to the ilp32d hard-float libs (verified with -print-multi-directory):
REM   final march = rv32imafdc_zicsr_zifencei_zba_zbb_zbc_zbs
REM   multilib    = rv32imafdc_zicsr_zba_zbb_zbc_zbs/ilp32d
REM Build dir sits INSIDE the app dir so the whole module is self-contained and
REM travels with it. (It used to be %HPM_SDK_BASE%\hr_project_<...>, which broke
REM the moment this project moved out of hpm_sdk\.) flash.bat derives the same
REM path from its own %~dp0 -- keep the two in sync.
set "BUILD_DIR=%APP_DIR%\build_hpm5300evk_flash_xip_debug"
set "RV_OPTS="
if defined HF (
    set "BUILD_DIR=%BUILD_DIR%_hf"
    set "RV_OPTS=-DRV_ARCH=rv32imafdc_zicsr_zifencei -DRV_ABI=ilp32d"
)

echo [cmake] configure  %APP_DIR%
echo [cmake] build dir  %BUILD_DIR%
if defined HF echo [cmake] float mode HARD - ilp32d, FPU enabled by start.S
if not defined HF echo [cmake] float mode SOFT - ilp32, default
"%CMAKE_EXE%" -GNinja -DBOARD=hpm5300evk -DHPM_BUILD_TYPE=flash_xip ^
    -DCMAKE_BUILD_TYPE=debug %RV_OPTS% -B "%BUILD_DIR%" -S "%APP_DIR%"
if errorlevel 1 (
    echo [ERROR] cmake configure failed
    exit /b 1
)

if defined GENONLY goto done

echo.
echo [ninja] build
"%NINJA_DIR%\ninja.exe" -C "%BUILD_DIR%"
if errorlevel 1 (
    echo [ERROR] build failed
    exit /b 1
)

:done
echo.
echo [ok] build dir  : %BUILD_DIR%
echo [ok] SES project: %BUILD_DIR%\segger_embedded_studio\hr_node.emProject
endlocal
