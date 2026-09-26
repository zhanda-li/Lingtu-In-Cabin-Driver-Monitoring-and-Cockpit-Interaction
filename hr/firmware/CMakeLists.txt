# Copyright (c) 2026
# SPDX-License-Identifier: BSD-3-Clause
#
# 心率节点固件（HPM5300EVK / HPM5361, RISC-V rv32imac）
#   MAX30102 走 I2C0（PB02/PB03），样本从 UART0 @115200 出板子。
#
# 工程生成（就是 start_gui 背后跑的那条命令，这里记下来以便命令行复现）：
#
#   cmake.exe -GNinja -DBOARD=hpm5300evk -DHPM_BUILD_TYPE=flash_xip \
#             -DCMAKE_BUILD_TYPE=debug -B <builddir> <this-dir>
#
# 需要环境变量 HPM_SDK_BASE 和 GNURISCV_TOOLCHAIN_PATH（见 tools/project_generator/preset.bat）
#
# 产出：
#   <builddir>/                                 build.ninja（可直接 ninja 编译）
#   <builddir>/segger_embedded_studio/hr_node.emProject  （SES 打开它烧录）

cmake_minimum_required(VERSION 3.13)

# ---------------------------------------------------------------------------
# CONFIG_HPM_I2C —— 必须放在 find_package 之前
#
# components/CMakeLists.txt:28 是 `add_subdirectory_ifdef(CONFIG_HPM_I2C i2c)`：
# 不设这个变量，components/i2c 根本不参与编译，而 hpm_i2c_context_t 就定义在
# components/i2c/hpm_i2c.h:68。结果是 hpm_i2c_get_default_init_context /
# hpm_i2c_initialize 全部 undefined —— 报错停在链接期，看着像"驱动没链上"，
# 其实是整个组件没被加进来。
#
# 注意 hpm_i2c_drv.h（drivers/inc 下那个）一直都在，它提供的是寄存器级
# i2c_master_write / i2c_master_read；缺的是 components 这一层。两者名字像，别混。
# ---------------------------------------------------------------------------
set(CONFIG_HPM_I2C 1)

find_package(hpm-sdk REQUIRED HINTS $ENV{HPM_SDK_BASE})

project(hr_node)

sdk_app_inc(src)
sdk_app_src(src/max30102.c)
sdk_app_src(src/hr_algo.c)
sdk_app_src(src/main.c)

# ---------------------------------------------------------------------------
# libm —— 2026-09-26 起**必须链**（`hr_algo.c` 里有一个 `sqrt`）。
#
# 这条推翻了本文件原来那句"热路径里一个浮点都没有"。新的口径是：
#   · 采集热路径（DMA ISR → 两条环）**仍然一个浮点都没有**（纯整数搬运）；
#   · 算法路径**每个样本约 2000 cycle 软浮点**（三节双二阶），100 Hz 下
#     占 480 MHz 的 0.04% —— 零头都算不上，所以**不切硬浮点**（rv32imac
#     本来也没有 F 扩展）。
# ---------------------------------------------------------------------------
sdk_link_libraries(m)

# 关掉 FMA 收缩。**理由不是"怕目标有 FMA"** —— rv32imac 没有，现在收缩不了；
# 理由是**不能靠"目标恰好没有"来保证语义**：哪天切到 hf 那份（ilp32d，有 F/D），
# GCC 会把 `a*b+c` 收成一条 fma，结果在**某些样本上差一点**（那种查不出来的差），
# 而 `ui/serial_hr.py` 的镜像实现和离线 A/B 全都会跟着失配。
# 见 hr_algo.h 文件头第 3 条。只加在算法这一个文件上：采集路径没有浮点，
# 别的文件也不该因为这一条被顺手改变代码生成。
set_source_files_properties(src/hr_algo.c
    PROPERTIES COMPILE_OPTIONS "-ffp-contract=off")

generate_ide_projects()
