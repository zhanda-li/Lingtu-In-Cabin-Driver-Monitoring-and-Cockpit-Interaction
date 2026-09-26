/*
 * print_nb.h —— 非阻塞串口打印（拥塞即丢弃）
 *
 * ── 为什么需要它 ─────────────────────────────────────────────────────────
 * 本工程的 printf 走 SDK 的 debug_console，**每一步都是忙等**：
 *   components/debug_console/hpm_debug_console.c:143  _write() 逐字节
 *   uart_send_byte() 忙等到 FIFO 收下，末尾还 uart_flush() 再忙等一次。
 *
 * 115200 8N1 下，一行 40 字符 ≈ 3.5 ms。而 100 Hz 发布的整个周期只有 10 ms
 * —— 一行 printf 就吃掉 35% 的预算（main.c:216 已经把这条写进注释了）。
 * 所以**周期路径里一次 printf 都不能有**，否则测出来的抖动指标是自己造成的。
 *
 * print_nb() 的做法：先看 TX FIFO 占用，超过一半就**直接返回 0 不打印**，
 * 否则逐字节塞进 FIFO（塞不进去也返回）—— 全程不等待。
 *
 * ⚠️ 代价：**输出是可丢的**。拥塞时整行丢掉，串口上会出现缺行。
 *    所以凡是"必须一条不落"的数据，都不能走串口 —— 本工程里那类数据走 CAN
 *    （帧由适配器硬件 ACK，PC 侧逐字节比对，见 attitude_probe.py）。
 *    串口在这里只承担**诊断**职责：标定状态、K_T、统计快照。
 *
 * ── 用法 ─────────────────────────────────────────────────────────────────
 *   #include "print_nb.h"
 *   print_nb("K_T=%.4f\n", k);          // 与 printf 同签名，返回值是打印字节数
 *
 * 来源：imu_project/user_app/src/main.c:93-106（上游是 static 函数，
 * 这里改成 static inline 放进头文件，方便多处包含而不产生重复符号）。
 * 上游背景见 imu_project/README.md:465-474「printf 阻塞导致陀螺数据累积偏移」。
 */
#ifndef PRINT_NB_H
#define PRINT_NB_H

#include <stdarg.h>
#include <stdint.h>
#include <stdio.h>

#include "hpm_common.h"
#include "hpm_uart_drv.h"
#include "board.h"

#ifdef __cplusplus
extern "C" {
#endif

/* TX FIFO 占用超过一半 → 视为拥塞。留一半余量给"突发一整行"用。 */
static inline bool uart_tx_congested(void)
{
    return uart_get_data_count_in_tx_fifo(BOARD_CONSOLE_UART_BASE)
           > (UART_SOC_FIFO_SIZE / 2);
}

/*
 * 返回实际写入的字节数；拥塞或格式化失败返回 0。
 * ⚠️ 它不是"尽量打印"而是"要么整行、要么不打印"—— 半行输出比不输出更难读。
 */
static inline int print_nb(const char *fmt, ...)
{
    if (uart_tx_congested()) {
        return 0;
    }

    char buf[256];
    va_list a;
    va_start(a, fmt);
    int len = vsnprintf(buf, sizeof(buf), fmt, a);
    va_end(a);

    if (len <= 0 || len >= (int)sizeof(buf)) {
        return 0;   /* 格式化失败或超长：宁可不打，也不打半行 */
    }

    for (int i = 0; i < len; i++) {
        /* 与 _write() 同样的处理：'\n' 前补 '\r'，否则终端里会阶梯状错行 */
        if (buf[i] == '\n') {
            if (uart_send_byte(BOARD_CONSOLE_UART_BASE, '\r') != status_success) {
                return 0;
            }
        }
        if (uart_send_byte(BOARD_CONSOLE_UART_BASE, (uint8_t)buf[i]) != status_success) {
            return 0;
        }
    }
    return len;
}

#ifdef __cplusplus
}
#endif

#endif /* PRINT_NB_H */
