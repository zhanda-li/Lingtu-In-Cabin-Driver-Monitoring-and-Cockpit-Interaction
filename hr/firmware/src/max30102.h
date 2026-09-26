/*
 * MAX30102 心率传感器驱动（HPM5300EVK / I2C0，PB02=SCL，PB03=SDA）
 *
 * ── 来源 ────────────────────────────────────────────────────────────────
 * 寄存器地址、位域取值、初始化序列取自 Maxim 的参考固件 MAXREFDES117#
 * （本机那份在 dms_project/max30102信息/1786340113841543/测试程序/
 * "MH-ET LIVE MAX30102 STM32"/.../Nucleo_MAX30102/MAX30102/MAX30102.cpp:113
 * 的 maxim_max30102_init()）。那份是 mbed C++ 外壳，跟平台无关的只有寄存器
 * 读写 —— 所以本文件是**重写**不是移植：I2C 原语换成 SDK 的
 * i2c_master_write / i2c_master_read，其余序列照抄。
 *
 * ── 与参考固件**故意不同**的两处 ────────────────────────────────────────
 * 1. 中断使能位全关（0x02 = 0x00、0x03 = 0x00）。参考固件开 PPG_RDY|A_FULL
 *    是为了让 INT 引脚把 MCU 从睡眠里叫醒；本板 INT **没接线**（跟 IMU 一样
 *    只接四根），开了只会在芯片内部挂一个没人清的状态位。本工程改成
 *    **1 ms 节拍触发 + DMA 突发读 FIFO 指针**（2026-09-26 从 0.5 ms 阻塞轮询
 *    改过来，理由见下面「采集架构」）。
 * 2. FIFO 回卷**关**（0x08 = 0x0F 的 bit4 = 0）。开着回卷时 FIFO 满了会静默
 *    覆盖最老的样本、而且 OVF_COUNTER 不计数 —— 丢数据丢得看不出来。关掉之后
 *    满了就停，OVF_COUNTER(0x05) 逐样本累加，主循环据此报"我们没跟上"。
 *
 * ── 采集架构（2026-09-26 改，照 can_project / imu_project 的 mpu6050.c）────
 * 从"主循环阻塞轮询"换成 **DMA + 中断链 + SPSC 环形缓冲**：
 *
 *   主循环 1 ms 一拍 ─▶ PTR_TX(写 0x04) ─TC─▶ PTR_RX(读 3 字节 =
 *                       WR_PTR,OVF_COUNTER,RD_PTR) ─TC─┬ n==0 ─▶ IDLE
 *                                                      └ n>0 ─▶ FIFO_TX(写 0x07)
 *                                                               ─TC─▶ FIFO_RX
 *                                                               ─TC─▶ 推环形缓冲
 *
 * 相位推进**全部在 IRQn_HDMA 的传输完成中断里**；链永不自续 —— 每拍由主循环
 * 起头（这点与 IMU **故意不同**：IMU 是"总线永不空闲"自由跑，靠软件去重把
 * 2.5 kHz 压回 1 kHz；而 MAX30102 的 FIFO_DATA 每读一次都会推进芯片内部的读
 * 指针，指针不前进时重读会把读指针推过写指针，而回卷是关着的 ⟹ 一旦推歪只能
 * 靠重新初始化，正是这次要消灭的那个级联）。
 *
 * 三个 DMA 缓冲**必须** ATTR_PLACE_AT_NONCACHEABLE：本 SoC 的 L1 D-Cache 在
 * start.S 里是无条件打开的，用普通静态数组当 DMA 目标会读到旧值（症状是
 * "数据像上一批的"，极难查）。
 *
 * ── 与上游 mpu6050.c 的两处**有意不抄** ──────────────────────────────────
 * · 那边有 `dma_error` 标志但设了从没被读过（死状态），我们真的用它触发恢复。
 * · 那边 `push_to_ring` 用 `static` 局部变量做软去重、不可重入 —— 我们不需要
 *   去重（FIFO 里每一个都是真样本，重读在架构上已被消除）。
 *
 * ── 接线（与 MPU6050 完全一样，用户 2026-09-26 已接好）───────────────────
 *   VCC → 3.3V   GND → GND   SDA → PB03   SCL → PB02
 *   ⚠️ VCC 决定 I2C 电平：模块自带的电平转换是按 VCC 做的，接 5V 时总线也会
 *      被抬到 5V，而 HPM5300 的 IO 是 3.3V —— 所以**必须接 3.3V**。
 *   ⚠️ 模块自带 10K 上拉，不要再外挂一组（并联会把上升沿拉坏）。
 *
 * ── FIFO 数据格式（SpO2 模式，MODE=0x03）────────────────────────────────
 *   一个样本 6 字节：[0..2] = RED，[3..5] = IR，各 18 bit 左对齐在 3 字节里。
 *   3 字节拼成 24 bit 之后必须 & 0x03FFFF 抹掉高 6 位 —— 那 6 位是无效位，
 *   不抹的话读数会随环境光残留随机跳。
 */
#ifndef MAX30102_H
#define MAX30102_H

#include <stdint.h>
#include <stdbool.h>

#include "hpm_common.h"
#include "hpm_i2c.h"

#ifdef __cplusplus
extern "C" {
#endif

/* ============ 从机地址与身份 ============ */
#define MAX30102_ADDR_7BIT          (0x57)  /* 8-bit 写 = 0xAE / 读 = 0xAF */
#define MAX30102_PART_ID_EXPECTED   (0x15)  /* 读回来不是它 = 芯片没答话 */

/* ============ 寄存器（MAXREFDES117 的 REG_* 同名）============ */
#define MAX30102_REG_INTR_STATUS_1  (0x00)
#define MAX30102_REG_INTR_STATUS_2  (0x01)
#define MAX30102_REG_INTR_ENABLE_1  (0x02)
#define MAX30102_REG_INTR_ENABLE_2  (0x03)
#define MAX30102_REG_FIFO_WR_PTR    (0x04)
#define MAX30102_REG_OVF_COUNTER    (0x05)
#define MAX30102_REG_FIFO_RD_PTR    (0x06)
#define MAX30102_REG_FIFO_DATA      (0x07)
#define MAX30102_REG_FIFO_CONFIG    (0x08)
#define MAX30102_REG_MODE_CONFIG    (0x09)
#define MAX30102_REG_SPO2_CONFIG    (0x0A)
#define MAX30102_REG_LED1_PA        (0x0C)  /* RED */
#define MAX30102_REG_LED2_PA        (0x0D)  /* IR  */
#define MAX30102_REG_PILOT_PA       (0x10)
#define MAX30102_REG_TEMP_INTEGER   (0x1F)
#define MAX30102_REG_TEMP_FRACTION  (0x20)
#define MAX30102_REG_TEMP_CONFIG    (0x21)
#define MAX30102_REG_REV_ID         (0xFE)
#define MAX30102_REG_PART_ID        (0xFF)

/* ============ 配置取值（改这里，不要再散到 main.c 里）============ */
#define MAX30102_MODE_SPO2          (0x03)  /* RED + IR 两个 LED，6 字节/样本 */

/* 0x0A：ADC 量程 4096nA | 采样率 100 Hz | 脉宽 411µs（18 bit，分辨率最好）。
 * 采样率决定 PC 侧算法的输入速率 —— Maxim 的参考算法就是按 100 Hz 写的
 * （algorithm.h 里 FS=100、BUFFER_SIZE=500，5 秒一算）。要改这里，
 * PC 侧 `ui/serial_hr.py` 的 SAMPLES_PER_SEC 必须跟着改。 */
#define MAX30102_SPO2_CFG           (0x27)

/* 0x08：不平均(000) | 回卷关(bit4=0) | 几乎满阈值 15(1111)。
 * ⚠️ 回卷关是本工程的有意选择，理由见文件头第 2 条。 */
#define MAX30102_FIFO_CFG           (0x0F)

/* LED 电流：步进 0.2 mA，0x24 = 7.2 mA（Maxim 参考设计取值，手指测量够用）。
 * 手指按上去 IR 直流还不到 20000 counts 时，**先调这一个旋钮**。 */
#define MAX30102_LED_PA             (0x24)

/* FIFO 一个样本的字节数（SpO2 模式固定 6）与最大可读样本数（32 深）。 */
#define MAX30102_BYTES_PER_SAMPLE   (6U)
#define MAX30102_FIFO_DEPTH         (32U)

/* DMA 通道。取 0 与 imu_project 一致（ch0 的 CHANREQCTRL 语义最干净，
 * 且本工程没有别的 DMA 用户）。 */
#ifndef MAX30102_DMA_CH
#define MAX30102_DMA_CH             (0U)
#endif

/* 环形缓冲深度。**必须是 2 的幂**（取模用 & 而不是 %）。
 * 128 帧 = 1.28 s：填充 100 帧/秒，而排空最多 1000 帧/秒（受串口拥塞闸门限制，
 * 实际约 400 帧/秒），余量 10 倍以上，正常永不溢出。 */
#define MAX30102_RING_DEPTH         (128U)

/* 芯片的采样周期。0x0A（SPO2_CFG）= 0x27 就是 100 Hz，时间戳游标按它步进。
 * ⚠️ 改 SPO2_CFG 就得同步改这里**和** PC 侧 ui/serial_hr.py 的 SAMPLES_PER_SEC。 */
#define MAX30102_SAMPLE_PERIOD_MS   (10U)

/* ── 算法专用环深度（第二条 SPSC 环）──
 * 同上**必须是 2 的幂**。128 项 × 8 B = 1 KB RAM。
 *
 * ⚠️ 这个数和 `MAX30102_RING_DEPTH` **碰巧都是 128，但两者没有关系**：
 *    串口那个的大小是"能容忍 PC 多久不读"（消费速率受串口拥塞闸门限制），
 *    这个的大小是"主循环多久能卡住"（消费是**无条件**的、每个 tick 都排空）。
 *    以后调那一个，别顺手把这个也改了。 */
#define MAX30102_ALGO_RING_DEPTH    (128U)

/* 时间戳游标最多允许落后真时间多少毫秒（只在环形缓冲真空了时才往前拽，
 * 见 max30102_ts_sync）。取 100 ms：正常积压远小于它，故障空洞远大于它。 */
#define MAX30102_TS_MAX_LAG_MS      (100U)

typedef struct {
    I2C_Type *base;   /* = hpm_i2c_context_t.base */
    uint16_t  addr;   /* 7-bit */
} max30102_t;

typedef struct {
    uint32_t red;     /* 18 bit，0..262143 */
    uint32_t ir;      /* 18 bit，0..262143 */
} max30102_sample_t;

/* DMA 链 + 环形缓冲的运行时统计。全部在 IRQn_HDMA 关闭的临界区内读，
 * 调用方拿到的是一个自洽的快照。 */
typedef struct {
    uint8_t     ovf;             /* 最近一次读到的 OVF_COUNTER（0x05） */
    uint8_t     raw_wr;          /* DMA 读回来的 WR_PTR 原始值 */
    uint8_t     raw_rd;          /* DMA 读回来的 RD_PTR 原始值 */
    uint32_t    no_sample_ms;    /* 距上一个样本过去了多久（**同一个时钟**算的） */
    uint32_t    fail_streak;     /* 连续失败的拍数；一次成功即清零 */
    uint32_t    ring_drop;       /* 环形缓冲满而丢掉的帧数（串口堵住才会涨） */
    const char *last_fail;       /* 最近一次失败的来源（静态字符串，可为空串） */
} max30102_dma_stats_t;

/* ⚠️ no_sample_ms 在**驱动内部**相减，不外露样本时刻 —— 这样主循环不需要
 * 自己有个毫秒时钟。两个时钟（mcycle 与 mchtmr）的换算只要有一点偏差，
 * 相减就会得到负数（无符号下是个天文数字），2026-09-26 就是这么踩到的。 */

/* ── 单寄存器读写（阻塞，只在开机和诊断路径上用）── */
hpm_stat_t max30102_read_reg(max30102_t *dev, uint8_t reg, uint8_t *val);
hpm_stat_t max30102_write_reg(max30102_t *dev, uint8_t reg, uint8_t val);

/* FIFO 三个连号寄存器（0x04 WR_PTR / 0x05 OVF / 0x06 RD_PTR）**阻塞**一次读完。
 * 热路径一律走 DMA —— 这个只在诊断时用：当 DMA 链说"FIFO 是空的"时，
 * 得能分辨"芯片真没采样"和"我们的 DMA 读没搬进数据"。 */
hpm_stat_t max30102_read_ptrs(max30102_t *dev, uint8_t *wr, uint8_t *ovf, uint8_t *rd);

/*
 * I2C 总线恢复：把 SCL 当 GPIO 敲 9 个脉冲 + 一个手动 STOP，然后重新挂回 I2C
 * 功能。**必须在 hpm_i2c_initialize() 之前调用** —— 上电时 MAX30102 内部的
 * 1.8V LDO 还没稳，或者上一次运行是硬复位、SDA 被从机拉死在低电平，这两种
 * 情况下 I2C 控制器会一直等到超时。本函数与 can_project/src/mpu6050.c:48 的
 * mpu6050_i2c_bus_recovery() 是同一段代码（同一组引脚），有意重复而不是跨工程
 * 引用 —— 两个工程各自自包含。
 */
void max30102_i2c_bus_recovery(void);

/* 软复位（0x09 = 0x40，位自清）。复位后要等 ≥ 1 ms 再访问其它寄存器。 */
hpm_stat_t max30102_reset(max30102_t *dev);

/* 读 PART_ID（0xFF）。读回来的值由调用方判断，本函数不替它下结论。 */
hpm_stat_t max30102_read_part_id(max30102_t *dev, uint8_t *id);

/* 初始化序列（软复位 + 校验 PART_ID + 写配置表 + 清 FIFO 指针）。
 * 每一步失败都原样返回码，调用方负责重试 —— 模块晚插上时能自愈。
 *
 * *part_id_seen：**无论成败都写**（成功=校验通过的那个值，失败="芯片实际答
 * 的那一个"，读不到时是 0）。调用方不要靠它的值得出成败，成败只看返回码 ——
 * 它的用途是让开机横幅把"对面到底答了什么"打出来，否则总线不通时只有一个
 * 干巴巴的失败码。 */
hpm_stat_t max30102_init(max30102_t *dev, uint8_t *part_id_seen);

/* ============ 采集路径（DMA + 中断链 + 环形缓冲）============
 *
 * 用法（main.c 里的形状）：
 *
 *   max30102_dma_attach(&dev);                  // 初始化成功后挂一次
 *   for (;;) {
 *       while (max30102_sample_pop(&f)) {        // 串口有地方才取
 *           print_nb("D,%u,%u,%u\n", f.t_ms, f.red, f.ir);
 *       }
 *       if (max30102_dma_phase_is_idle()) {
 *           max30102_dma_kick();                 // 1 ms 一拍
 *       }
 *       ...
 *   }
 *
 * 相位推进全部在 IRQn_HDMA 里完成，主循环只负责"起头"和"取货"。
 */

/* 挂 DMA：配 DMAMUX、开 IRQn_HDMA、把状态机复位到 IDLE。
 * **每次 max30102_init() 成功之后都必须重挂一次** —— 总线恢复路径里的
 * i2c_reset() 会把控制器的 DMA 使能位清掉。 */
void max30102_dma_attach(max30102_t *dev);

/* 拆 DMA（关通道 + 关控制器 DMA 请求 + 相位回 IDLE）。重建链路之前必须先拆，
 * 否则残余的 DMA 请求会在 hpm_i2c_initialize() 之后乱触发。**不碰时间戳游标**。 */
void max30102_dma_detach(void);

/* 起一拍（只在 IDLE 时有效；非 IDLE 直接返回 false，防重入）。
 * 失败（I2C 忙 / 地址不应答）返回 false，下一拍再来。 */
bool max30102_dma_kick(void);

/* 当前相位是不是 IDLE。 */
bool max30102_dma_phase_is_idle(void);

/* 当前相位已经停留了多少毫秒（主循环用它做看门狗）。 */
uint32_t max30102_dma_phase_stuck_ms(void);

/* 强制把状态机打回 IDLE 并数一次失败（看门狗超时时调用）。 */
void max30102_dma_abort(void);

/* 从环形缓冲取一个样本。**取到就出队**，所以只在真的要发的时候调
 * （主循环的闸门：`!uart_tx_congested() && max30102_sample_pop(&f, &t)`）。 */
bool max30102_sample_pop(max30102_sample_t *out, uint32_t *t_ms);

/* 从**算法专用环**取一个样本（出队）。与上面那个是两条独立的流：
 * 这个环**不受串口拥塞影响**，所以主循环要**无条件**排空它、喂给 `hr_algo_push()`。
 *
 * 🔴 为什么非要有第二条环：算法必须看到**每一个**样本。三节双二阶是按
 *    `fs = 100 Hz` 定死系数的，喂进一个"有效采样率不对的不均匀流"会让
 *    0.65 / 3.5 Hz 两个拐点整体漂掉 —— **输出不崩、只是安静地错**。
 *    共用一条环就得把取货从拥塞闸门里拿出来，那会把 `D` 流从"1.28 s 内无损"
 *    变成"过了就丢"，正是那条不许动的路。1 KB RAM 买断这个耦合，划算。
 *
 * ⚠️ 只回 `ir`：算法不用红光（SpO₂ 没做）。 */
bool max30102_algo_pop(uint32_t *t_ms, uint32_t *ir);

/* 算法环满而丢掉的样本数（诊断）。正常恒 0 —— 非 0 说明主循环卡住了 1.28 s 以上。 */
uint32_t max30102_algo_drops(void);

/* 时间戳游标的追赶闸门。主循环每拍调一次（不用每拍都很准，慢几拍也无所谓）：
 * 环形缓冲真空了、且游标落后真时间超过 MAX30102_TS_MAX_LAG_MS 时，把它往前
 * 拽到当前时刻。**只往前**，所以对 PC 侧来说不是复位，是一段如实的时间空洞。 */
void max30102_ts_sync(void);

/* 读一份统计快照。 */
void max30102_dma_get_stats(max30102_dma_stats_t *out);

/* 清零连续失败计数（升级成功之后调）。 */
void max30102_dma_clear_fail(void);

/* 丢掉**两个**环里所有还没被取走的样本（串口的 + 算法的）。
 * **只在升级/重初始化之后调**：那段空洞里的样本已经落在别的时基上了。
 * ⚠️ 清的只是**待取的原始样本**，不碰算法自身的滤波器状态 —— 那由 `hr_algo_t`
 *    持有，链路重建**不该**重置它（和 `s_ts_next` 不清是同一个道理：重建不是
 *    板子复位，滤波器的历史仍然有效）。 */
void max30102_ring_flush(void);

/*
 * 从断链里恢复（照 imu_project/src/mpu6050.c:412 的 mpu6050_i2c_recover()，
 * 四步顺序不能换）：
 *   拆 DMA 通道 + 关控制器 DMA  →  总线恢复（9 个 SCL 脉冲）
 *   →  hpm_i2c_initialize()  →  **重挂 DMAMUX**
 * 最后一步漏掉是必然失败的（imu 那边踩过）。恢复完要重跑 max30102_init()。
 */
hpm_stat_t max30102_i2c_recover(hpm_i2c_context_t *i2c_ctx);

#ifdef __cplusplus
}
#endif

#endif /* MAX30102_H */
