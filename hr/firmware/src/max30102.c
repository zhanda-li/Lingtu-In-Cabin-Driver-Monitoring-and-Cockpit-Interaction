/*
 * MAX30102 驱动实现 —— 寄存器级 + DMA/中断链采集，不含算法。
 *
 * 算法（心率/血氧）**不在这里**：本工程板子只负责把原始 PPG 波送出去，
 * 由 PC 侧算。理由见 README.md「为什么算法不在板子上」。
 *
 * 所有函数都不打印 —— 打印归 main.c，这样驱动能在没有串口的场合复用。
 *
 * ── 采集路径的形状（照 imu_project/user_app/src/mpu6050.c）──────────────
 * 主循环 1 ms 一拍 max30102_dma_kick() 起头，之后**相位推进全在 IRQn_HDMA 的
 * 传输完成中断里**，链永不自续（理由见 max30102.h 的「采集架构」）。
 * ISR 把解码好的样本推进 SPSC 环形缓冲，主循环在串口有空位时才弹出来发走。
 */
#include "board.h"
#include "max30102.h"

#include "hpm_i2c_drv.h"
#include "hpm_gpio_drv.h"
#include "hpm_dmav2_drv.h"
#include "hpm_dmamux_drv.h"
#include "hpm_mchtmr_drv.h"

/* ⚠️ 必须是 hpm_dmav2_drv.h（本 SoC 是 DMAV2）。引成 hpm_dma_drv.h
 * （DMAv1）**不会报错**，只是把寄存器写到别的偏移上，症状是"什么都没发生"。 */
#define HR_I2C_DMAMUX_CH  DMA_SOC_CHN_TO_DMAMUX_CHN(BOARD_APP_I2C_DMA, MAX30102_DMA_CH)

/* ========================================================================
 * 1. 单寄存器读写（阻塞，只在开机与诊断路径上用）
 * ======================================================================== */
hpm_stat_t max30102_read_reg(max30102_t *dev, uint8_t reg, uint8_t *val)
{
    uint8_t reg_buf[1] = { reg };
    hpm_stat_t stat = i2c_master_write(dev->base, dev->addr, reg_buf, 1);

    if (stat != status_success) {
        return stat;
    }
    return i2c_master_read(dev->base, dev->addr, val, 1);
}

hpm_stat_t max30102_write_reg(max30102_t *dev, uint8_t reg, uint8_t val)
{
    uint8_t buf[2] = { reg, val };

    return i2c_master_write(dev->base, dev->addr, buf, 2);
}

hpm_stat_t max30102_read_ptrs(max30102_t *dev, uint8_t *wr, uint8_t *ovf, uint8_t *rd)
{
    uint8_t reg_buf[1] = { MAX30102_REG_FIFO_WR_PTR };
    uint8_t buf[3] = { 0, 0, 0 };
    hpm_stat_t stat = i2c_master_write(dev->base, dev->addr, reg_buf, 1);

    if (stat != status_success) {
        return stat;
    }
    /* 0x04/0x05/0x06 连号 + 自动地址递增，一次连读就拿全。
     * （不能用 i2c_master_read 逐寄存器读 —— 那中间会重新起地址相位，
     *   而且 DMA 那条路上必须让芯片自己推进指针。） */
    stat = i2c_master_read(dev->base, dev->addr, buf, 3);
    if (stat != status_success) {
        return stat;
    }
    if (wr  != NULL) *wr  = buf[0];
    if (ovf != NULL) *ovf = buf[1];
    if (rd  != NULL) *rd  = buf[2];
    return status_success;
}

/* ========================================================================
 * 2. I2C 总线恢复（与 can_project/src/mpu6050.c:48 同一段，见头文件注释）
 * ======================================================================== */
void max30102_i2c_bus_recovery(void)
{
    const uint32_t scl_ioc  = IOC_PAD_PB02;
    const uint32_t sda_ioc  = IOC_PAD_PB03;
    const uint32_t port     = GPIO_GET_PORT_INDEX(scl_ioc);
    const uint8_t  scl_pin  = GPIO_GET_PIN_INDEX(scl_ioc);
    const uint8_t  sda_pin  = GPIO_GET_PIN_INDEX(sda_ioc);

    HPM_IOC->PAD[scl_ioc].FUNC_CTL = IOC_PB02_FUNC_CTL_GPIO_B_02;
    HPM_IOC->PAD[scl_ioc].PAD_CTL  = IOC_PAD_PAD_CTL_OD_SET(1)
                                   | IOC_PAD_PAD_CTL_PE_SET(1)
                                   | IOC_PAD_PAD_CTL_PS_SET(1);

    HPM_IOC->PAD[sda_ioc].FUNC_CTL = IOC_PB03_FUNC_CTL_GPIO_B_03;
    HPM_IOC->PAD[sda_ioc].PAD_CTL  = IOC_PAD_PAD_CTL_OD_SET(1)
                                   | IOC_PAD_PAD_CTL_PE_SET(1)
                                   | IOC_PAD_PAD_CTL_PS_SET(1);

    gpio_set_pin_output_with_initial(HPM_GPIO0, port, scl_pin, 1);
    gpio_set_pin_input(HPM_GPIO0, port, sda_pin);

    for (int i = 0; i < 9; i++) {
        gpio_write_pin(HPM_GPIO0, port, scl_pin, 0);
        board_delay_us(10);
        gpio_write_pin(HPM_GPIO0, port, scl_pin, 1);
        board_delay_us(10);
        if (gpio_read_pin(HPM_GPIO0, port, sda_pin)) break;
    }

    gpio_set_pin_output(HPM_GPIO0, port, sda_pin);
    gpio_write_pin(HPM_GPIO0, port, sda_pin, 0);
    board_delay_us(5);
    gpio_write_pin(HPM_GPIO0, port, scl_pin, 1);
    board_delay_us(5);
    gpio_write_pin(HPM_GPIO0, port, sda_pin, 1);
    board_delay_us(5);

    i2c_reset(BOARD_APP_I2C_BASE);
    init_i2c_pins(BOARD_APP_I2C_BASE);
}

/* ========================================================================
 * 3. 复位 / 身份 / 初始化序列（与改造前逐字相同）
 * ======================================================================== */
hpm_stat_t max30102_reset(max30102_t *dev)
{
    hpm_stat_t stat = max30102_write_reg(dev, MAX30102_REG_MODE_CONFIG, 0x40);
    uint8_t mode = 0xFF;

    if (stat != status_success) {
        return stat;
    }

    /* 等复位位自清。**不要用固定 delay 代替这个轮询**：LDO 没稳时芯片会把
     * 复位位一直举着，固定等 1 ms 之后照样能写下配置，但配置被复位吃掉，
     * 症状是"配置看起来成功、读数全 0"。 */
    for (int i = 0; i < 100; i++) {
        board_delay_us(200);
        if (max30102_read_reg(dev, MAX30102_REG_MODE_CONFIG, &mode) != status_success) {
            continue;   /* 复位期间 NACK 是正常的，不算失败 */
        }
        if ((mode & 0x40) == 0) {
            return status_success;
        }
    }
    return status_timeout;
}

hpm_stat_t max30102_read_part_id(max30102_t *dev, uint8_t *id)
{
    return max30102_read_reg(dev, MAX30102_REG_PART_ID, id);
}

hpm_stat_t max30102_init(max30102_t *dev, uint8_t *part_id_seen)
{
    hpm_stat_t stat;
    uint8_t id = 0;

    if (part_id_seen != NULL) {
        *part_id_seen = 0;
    }

    /*
     * 软复位这一步要**重试几次**。理由：总线刚被恢复过（9 个 SCL 脉冲 +
     * i2c_reset）之后，芯片的第一笔地址相位经常不应答 —— 实测
     * `E,1,init stat=2003`（2003 = status_group_i2c*1000+3 = no_addr_hit），
     * 隔一拍再来就过了。芯片内部 1.8V LDO 在掉电重启后需要一点时间。
     * 复位写是幂等的（就是往 MODE_CONFIG 写 0x40），重试没有副作用。
     */
    for (int attempt = 0; ; attempt++) {
        stat = max30102_reset(dev);
        if (stat == status_success || attempt >= 4) {
            break;
        }
        board_delay_ms(2);
    }
    if (stat != status_success) {
        return stat;
    }

    /*
     * PART_ID 是**唯一**能分辨"总线通了但对面不是这颗芯片/没供电"的检查。
     * 不查到就往下走的话，后面每一次寄存器写都会"成功返回"（I2C 只保证波形
     * 对，不保证对面有芯片），最后表现成"配置全对、数据恒 0"。
     */
    stat = max30102_read_part_id(dev, &id);
    if (stat != status_success) {
        return stat;
    }
    if (part_id_seen != NULL) {
        *part_id_seen = id;
    }
    if (id != MAX30102_PART_ID_EXPECTED) {
        return status_fail;
    }

    /* 顺序照 MAXREFDES117：先清 FIFO 指针，再写 FIFO/MODE/SPO2 配置，
     * 最后 LED 电流。电流写早了会被随后的模式切换重新分配。
     * ⚠️ 清 FIFO 指针这一步在恢复路径上是**必须**的：断链期间 FIFO 里攒下的
     * 是垃圾，不清掉会被当成真样本发出去。 */
    stat = max30102_write_reg(dev, MAX30102_REG_FIFO_WR_PTR, 0x00);
    if (stat != status_success) return stat;
    stat = max30102_write_reg(dev, MAX30102_REG_OVF_COUNTER, 0x00);
    if (stat != status_success) return stat;
    stat = max30102_write_reg(dev, MAX30102_REG_FIFO_RD_PTR, 0x00);
    if (stat != status_success) return stat;

    stat = max30102_write_reg(dev, MAX30102_REG_INTR_ENABLE_1, 0x00);
    if (stat != status_success) return stat;
    stat = max30102_write_reg(dev, MAX30102_REG_INTR_ENABLE_2, 0x00);
    if (stat != status_success) return stat;

    stat = max30102_write_reg(dev, MAX30102_REG_FIFO_CONFIG, MAX30102_FIFO_CFG);
    if (stat != status_success) return stat;
    stat = max30102_write_reg(dev, MAX30102_REG_SPO2_CONFIG, MAX30102_SPO2_CFG);
    if (stat != status_success) return stat;

    stat = max30102_write_reg(dev, MAX30102_REG_LED1_PA, MAX30102_LED_PA);
    if (stat != status_success) return stat;
    stat = max30102_write_reg(dev, MAX30102_REG_LED2_PA, MAX30102_LED_PA);
    if (stat != status_success) return stat;
    /* PILOT_PA 只在接近检测/多 LED 槽模式下用得到，本工程不用；写它是因为
     * 参考固件写了、且地址 0x10 在任何模式下都无害。留着可少一处"和参考
     * 设计不一致"。 */
    stat = max30102_write_reg(dev, MAX30102_REG_PILOT_PA, 0x7F);
    if (stat != status_success) return stat;

    /* MODE 放最后：写下去的那一刻 LED 才开始闪、FIFO 才开始进数，
     * 前面所有配置必须已经在位。 */
    stat = max30102_write_reg(dev, MAX30102_REG_MODE_CONFIG, MAX30102_MODE_SPO2);
    if (stat != status_success) return stat;

    return status_success;
}

/* ========================================================================
 * 4. 采集：DMA 四相位状态机
 * ======================================================================== */

/* 三个 DMA 缓冲**必须**非 cacheable —— 见 max30102.h 的说明。 */
static uint8_t s_dma_tx[1]   ATTR_PLACE_AT_NONCACHEABLE;
static uint8_t s_dma_ptr[3]  ATTR_PLACE_AT_NONCACHEABLE;
static uint8_t s_dma_fifo[MAX30102_FIFO_DEPTH * MAX30102_BYTES_PER_SAMPLE]
                          ATTR_PLACE_AT_NONCACHEABLE;

/* ── 环形缓冲（SPSC：ISR 生产 / 主循环消费）── */
typedef struct {
    uint32_t red;
    uint32_t ir;
    uint32_t t_ms;
} hr_frame_t;

static hr_frame_t        s_ring[MAX30102_RING_DEPTH];
static volatile uint32_t s_ring_head;      /* ISR 写 */
static volatile uint32_t s_ring_tail;      /* 主循环写 */
static volatile uint32_t s_ring_drop;      /* 满时丢掉的帧数 */

/* ── 算法专用环（ISR 生产 / 主循环消费，同样 SPSC）──
 * 只存 `ir` 和 `t_ms`：算法不用红光。`t_ms` 与串口那一条**逐位相同**
 * （同一个 `s_ts_next`，在自增之前读出来给两边用）。
 * **纯整数，ISR 里零浮点。** 理由见 max30102.h 的 `MAX30102_ALGO_RING_DEPTH`。 */
typedef struct {
    uint32_t ir;
    uint32_t t_ms;
} hr_arng_t;

static hr_arng_t         s_arng[MAX30102_ALGO_RING_DEPTH];
static volatile uint32_t s_arng_head;      /* ISR 写 */
static volatile uint32_t s_arng_tail;      /* 主循环写 */
static volatile uint32_t s_arng_drop;      /* 满时丢掉的样本数 */

/* ── 时间戳游标 ──
 * 第 k 个发出去的样本，t_ms 恒等于 base + 10*k：**构造性单调**，与批次大小、
 * ISR 延迟、调度抖动全都无关。这比"读完 FIFO 取 now 再回推"强在：回推只在
 * 一切正常时才单调，而恰恰在故障恢复时它最容易和上一批撞成相等或更小 ——
 * PC 侧把 t_ms 往回走判成**板子复位**（ui/serial_hr.py:844）。
 * ⚠️ 这个游标**任何恢复路径都不许清零**（清零 = 对 PC 假装复位过一次）。 */
static volatile uint32_t s_ts_next;

typedef enum {
    HR_DMA_IDLE = 0,
    HR_DMA_PTR_TX,      /* DMA 写 1 字节：寄存器指针 = 0x04 */
    HR_DMA_PTR_RX,      /* DMA 读 3 字节：WR_PTR, OVF_COUNTER, RD_PTR */
    HR_DMA_FIFO_TX,     /* DMA 写 1 字节：寄存器指针 = 0x07 */
    HR_DMA_FIFO_RX,     /* DMA 读 n*6 字节 */
} hr_dma_phase_t;

static max30102_t * volatile s_dev;
static volatile hr_dma_phase_t s_phase = HR_DMA_IDLE;
static volatile uint32_t s_phase_ms;        /* 进入当前相位的板子毫秒 */
static volatile uint8_t  s_fifo_n;          /* FIFO_RX 要读几个样本 */
static volatile uint32_t s_ovf;             /* 最近一次读到的 OVF_COUNTER */
static volatile uint8_t  s_raw_wr;          /* DMA 读回来的两个指针原始值（诊断） */
static volatile uint8_t  s_raw_rd;
static volatile uint32_t s_last_sample_ms;
static volatile uint32_t s_fail_streak;
/* 注意写法：`const char *volatile` = **指针本身** volatile（ISR 会改它），
 * 不是 `volatile const char *`（那成了"指向 volatile 字符"，赋值给普通
 * const char* 会被 -Wdiscarded-qualifiers 警告）。 */
static const char *volatile s_last_fail = "";

static uint32_t s_mchtmr_per_ms = 24000U;   /* attach 时按实际时钟重算 */

static uint32_t hr_now_ms(void)
{
    return (uint32_t)(mchtmr_get_count(HPM_MCHTMR) / s_mchtmr_per_ms);
}

/* ── 计一次失败：状态机回 IDLE，等主循环重试或升级 ──
 * 只有连续 20 拍真失败才会升级成"重建链路"，所以这里**不**动 s_dev、不碰
 * 初始化 —— 瞬时抖动不该把数据流打出空洞（这正是改造前那个级联的病根）。 */
static void hr_fail(const char *why)
{
    s_phase      = HR_DMA_IDLE;
    s_fail_streak++;
    s_last_fail  = why;
}

static void hr_arng_push(uint32_t ir, uint32_t t_ms)
{
    uint32_t next = (s_arng_head + 1U) & (MAX30102_ALGO_RING_DEPTH - 1U);

    if (next == s_arng_tail) {
        s_arng_drop++;
        return;
    }
    s_arng[s_arng_head].ir   = ir;
    s_arng[s_arng_head].t_ms = t_ms;
    s_arng_head = next;
}

static void hr_ring_push(uint32_t red, uint32_t ir)
{
    uint32_t next = (s_ring_head + 1U) & (MAX30102_RING_DEPTH - 1U);
    uint32_t t    = s_ts_next;

    /* 算法环**先**推，而且**在串口拥塞判断之前** —— 这两条都是刻意的：
     *   · 先推：串口那个环满的时候算法照样拿到样本（它存在的全部理由）。
     *   · 顺序上"重复 t_ms"比"缺一个样本"轻：串口堵住时 `s_ts_next` 不推进
     *     （既有行为，`D` 行一个字节没动），于是算法环里会连着出现几个**相同
     *     t_ms** 的样本 —— 算法那一侧把它们看成"间隔 0 ms"，被范围闸拒掉 ⟹
     *     NN 连续段断掉（RMSSD 退回 `--`）。**缺样本**则会喂给双二阶一个
     *     不均匀的采样间隔，那是安静地算错，比退回 `--` 坏得多。 */
    hr_arng_push(ir, t);

    if (next == s_ring_tail) {
        s_ring_drop++;
        return;
    }
    s_ring[s_ring_head].red  = red;
    s_ring[s_ring_head].ir   = ir;
    s_ring[s_ring_head].t_ms = t;
    s_ts_next += MAX30102_SAMPLE_PERIOD_MS;
    s_ring_head = next;
}

/* ── DMA 通道装载 ──
 * 每次都重新 dma_setup_handshake(..., true)：`true` = 立刻使能这一拍。
 * `en_infiniteloop` 由 dma_default_handshake_config() 置 false —— 链是**软件**
 * 串的，不是硬件循环（MAX30102 不能自由跑，理由见 max30102.h）。 */
static hpm_stat_t hr_dma_setup_tx(uint32_t src, uint32_t size)
{
    dma_handshake_config_t cfg;

    dma_default_handshake_config(BOARD_APP_I2C_DMA, &cfg);
    cfg.ch_index       = MAX30102_DMA_CH;
    cfg.dst            = (uint32_t)&BOARD_APP_I2C_BASE->DATA;
    cfg.dst_fixed      = true;
    cfg.src            = src;
    cfg.src_fixed      = false;
    cfg.data_width     = DMA_TRANSFER_WIDTH_BYTE;
    cfg.size_in_byte   = size;
    cfg.interrupt_mask = DMA_INTERRUPT_MASK_HALF_TC;   /* = 只关半传输，TC 留着 */
    return dma_setup_handshake(BOARD_APP_I2C_DMA, &cfg, true);
}

static hpm_stat_t hr_dma_setup_rx(uint32_t dst, uint32_t size)
{
    dma_handshake_config_t cfg;

    dma_default_handshake_config(BOARD_APP_I2C_DMA, &cfg);
    cfg.ch_index       = MAX30102_DMA_CH;
    cfg.dst            = dst;
    cfg.dst_fixed      = false;
    cfg.src            = (uint32_t)&BOARD_APP_I2C_BASE->DATA;
    cfg.src_fixed      = true;
    cfg.data_width     = DMA_TRANSFER_WIDTH_BYTE;
    cfg.size_in_byte   = size;
    cfg.interrupt_mask = DMA_INTERRUPT_MASK_HALF_TC;
    return dma_setup_handshake(BOARD_APP_I2C_DMA, &cfg, true);
}

/* 相位先置好再起 I2C —— 传输可能在 i2c_master_start_dma_* 返回前就完成，
 * ISR 靠 s_phase 认路。 */
static bool hr_start_ptr_tx(void)
{
    hpm_stat_t stat;

    s_dma_tx[0] = MAX30102_REG_FIFO_WR_PTR;    /* 0x04/0x05/0x06 连号，一次读完 */
    stat = hr_dma_setup_tx(
        core_local_mem_to_sys_address(BOARD_RUNNING_CORE, (uint32_t)s_dma_tx), 1);
    if (stat != status_success) {
        hr_fail("dma cfg ptr tx");
        return false;
    }
    s_phase    = HR_DMA_PTR_TX;
    s_phase_ms = hr_now_ms();
    stat = i2c_master_start_dma_write(s_dev->base, s_dev->addr, 1);
    if (stat != status_success) {
        hr_fail("i2c ptr tx");
        return false;
    }
    return true;
}

static bool hr_start_ptr_rx(void)
{
    hpm_stat_t stat = hr_dma_setup_rx(
        core_local_mem_to_sys_address(BOARD_RUNNING_CORE, (uint32_t)s_dma_ptr), 3);

    if (stat != status_success) {
        hr_fail("dma cfg ptr rx");
        return false;
    }
    s_phase    = HR_DMA_PTR_RX;
    s_phase_ms = hr_now_ms();
    stat = i2c_master_start_dma_read(s_dev->base, s_dev->addr, 3);
    if (stat != status_success) {
        hr_fail("i2c ptr rx");
        return false;
    }
    return true;
}

static bool hr_start_fifo_tx(void)
{
    hpm_stat_t stat;

    s_dma_tx[0] = MAX30102_REG_FIFO_DATA;
    stat = hr_dma_setup_tx(
        core_local_mem_to_sys_address(BOARD_RUNNING_CORE, (uint32_t)s_dma_tx), 1);
    if (stat != status_success) {
        hr_fail("dma cfg fifo tx");
        return false;
    }
    s_phase    = HR_DMA_FIFO_TX;
    s_phase_ms = hr_now_ms();
    stat = i2c_master_start_dma_write(s_dev->base, s_dev->addr, 1);
    if (stat != status_success) {
        hr_fail("i2c fifo tx");
        return false;
    }
    return true;
}

static bool hr_start_fifo_rx(void)
{
    hpm_stat_t stat = hr_dma_setup_rx(
        core_local_mem_to_sys_address(BOARD_RUNNING_CORE, (uint32_t)s_dma_fifo),
        (uint32_t)s_fifo_n * MAX30102_BYTES_PER_SAMPLE);

    if (stat != status_success) {
        hr_fail("dma cfg fifo rx");
        return false;
    }
    s_phase    = HR_DMA_FIFO_RX;
    s_phase_ms = hr_now_ms();
    stat = i2c_master_start_dma_read(s_dev->base, s_dev->addr,
                                     (uint32_t)s_fifo_n * MAX30102_BYTES_PER_SAMPLE);
    if (stat != status_success) {
        hr_fail("i2c fifo rx");
        return false;
    }
    return true;
}

static void hr_push_samples(uint8_t n)
{
    for (uint8_t i = 0; i < n; i++) {
        const uint8_t *b = &s_dma_fifo[i * MAX30102_BYTES_PER_SAMPLE];

        /* 3 字节拼 24 bit 之后 & 0x03FFFF：高 6 位是无效位，不抹掉读数会
         * 随环境光残留随机跳（见 max30102.h 的 FIFO 数据格式）。 */
        uint32_t red = (((uint32_t)b[0] << 16) | ((uint32_t)b[1] << 8) | b[2]) & 0x03FFFFu;
        uint32_t ir  = (((uint32_t)b[3] << 16) | ((uint32_t)b[4] << 8) | b[5]) & 0x03FFFFu;

        hr_ring_push(red, ir);
    }
    s_last_sample_ms = hr_now_ms();
}

/* ── DMA 传输完成中断：相位推进全在这里 ── */
SDK_DECLARE_EXT_ISR_M(IRQn_HDMA, hr_dma_isr)
void hr_dma_isr(void)
{
    uint32_t status = dma_check_transfer_status(BOARD_APP_I2C_DMA, MAX30102_DMA_CH);

    if (status & (DMA_CHANNEL_STATUS_ERROR | DMA_CHANNEL_STATUS_ABORT)) {
        hr_fail("dma err");
        return;
    }
    if (!(status & DMA_CHANNEL_STATUS_TC)) {
        return;                     /* 半传输之类：不关我们的事 */
    }
    if (s_phase == HR_DMA_IDLE || s_dev == NULL) {
        return;                     /* 初始化期间的野中断 */
    }

    I2C_Type *i2c = s_dev->base;

    /* 照 IMU：起下一相位之前先清控制器状态、关掉 DMA 请求，
     * 否则 i2c_master_start_dma_* 会在旧的 CMPL 位上空转。 */
    i2c_clear_status(i2c, i2c_get_status(i2c));
    i2c_dma_disable(i2c);

    switch (s_phase) {
    case HR_DMA_PTR_TX:
        (void)hr_start_ptr_rx();
        break;

    case HR_DMA_PTR_RX: {
        uint8_t wr = (uint8_t)(s_dma_ptr[0] & 0x1FU);
        uint8_t rd = (uint8_t)(s_dma_ptr[2] & 0x1FU);
        uint8_t n;

        s_ovf    = s_dma_ptr[1];
        s_raw_wr = wr;
        s_raw_rd = rd;

        /* ⚠️ 这里**不能**写成 (wr - rd) & 0x1F。回卷是关着的（见 max30102.h），
         * FIFO 满了之后读写指针一起冻在差 32 的位置，而 32 & 0x1F == 0 ——
         * 会被读成"空"，从此再也不去读，卡死。 */
        n = (uint8_t)((wr >= rd) ? (wr - rd)
                                 : (MAX30102_FIFO_DEPTH - rd + wr));

        if (n == 0U) {
            s_phase       = HR_DMA_IDLE;
            s_fail_streak = 0;              /* 链路是活的，只是这一拍没新数据 */
        } else {
            s_fifo_n = n;
            (void)hr_start_fifo_tx();
        }
        break;
    }

    case HR_DMA_FIFO_TX:
        (void)hr_start_fifo_rx();
        break;

    case HR_DMA_FIFO_RX:
        hr_push_samples(s_fifo_n);
        s_phase       = HR_DMA_IDLE;
        s_fail_streak = 0;
        break;

    default:
        s_phase = HR_DMA_IDLE;
        break;
    }
}

/* ========================================================================
 * 5. 对 main.c 暴露的采集 API
 * ======================================================================== */
void max30102_dma_attach(max30102_t *dev)
{
    uint32_t mchtmr_hz = clock_get_frequency(clock_mchtmr0);

    if (mchtmr_hz >= 1000U) {
        s_mchtmr_per_ms = mchtmr_hz / 1000U;
    }

    s_dev = dev;

    dma_disable_channel(BOARD_APP_I2C_DMA, MAX30102_DMA_CH);
    i2c_dma_disable(BOARD_APP_I2C_BASE);
    dmamux_config(BOARD_APP_I2C_DMAMUX, HR_I2C_DMAMUX_CH, BOARD_APP_I2C_DMA_SRC, true);

    /* 两条环形缓冲都清空。**时间戳游标不清** —— 见 s_ts_next 的注释。 */
    s_ring_head = s_ring_tail = 0;
    s_ring_drop = 0;
    s_arng_head = s_arng_tail = 0;
    s_arng_drop = 0;

    s_phase          = HR_DMA_IDLE;
    s_fifo_n         = 0;
    s_phase_ms       = hr_now_ms();
    s_last_sample_ms = s_phase_ms;
    s_fail_streak    = 0;
    s_last_fail      = "";

    intc_m_enable_irq_with_priority(IRQn_HDMA, 1);
}

bool max30102_dma_kick(void)
{
    if (s_dev == NULL || s_phase != HR_DMA_IDLE) {
        return false;               /* 上一拍还没走完，防重入 */
    }
    return hr_start_ptr_tx();
}

void max30102_dma_detach(void)
{
    intc_m_disable_irq(IRQn_HDMA);
    dma_disable_channel(BOARD_APP_I2C_DMA, MAX30102_DMA_CH);
    i2c_dma_disable(BOARD_APP_I2C_BASE);
    s_phase = HR_DMA_IDLE;
    s_dev   = NULL;
    intc_m_enable_irq(IRQn_HDMA);
    /* ⚠️ s_ts_next 在这里也**不动** —— 重建链路不是板子复位。 */
}

bool max30102_dma_phase_is_idle(void)
{
    return (s_phase == HR_DMA_IDLE);
}

uint32_t max30102_dma_phase_stuck_ms(void)
{
    return hr_now_ms() - s_phase_ms;
}

void max30102_dma_abort(void)
{
    intc_m_disable_irq(IRQn_HDMA);
    dma_disable_channel(BOARD_APP_I2C_DMA, MAX30102_DMA_CH);
    i2c_dma_disable(BOARD_APP_I2C_BASE);
    i2c_clear_status(BOARD_APP_I2C_BASE, i2c_get_status(BOARD_APP_I2C_BASE));
    intc_m_enable_irq(IRQn_HDMA);

    hr_fail("phase stuck");
}

bool max30102_sample_pop(max30102_sample_t *out, uint32_t *t_ms)
{
    uint32_t tail;
    hr_frame_t f;

    /* SPSC 临界区：ISR 在写 head，不关中断会读到"读了一半"的一对值
     * （照 imu_project 的 mpu6050_ring_pop）。 */
    intc_m_disable_irq(IRQn_HDMA);
    if (s_ring_head == s_ring_tail) {
        intc_m_enable_irq(IRQn_HDMA);
        return false;
    }
    tail = s_ring_tail;
    f    = s_ring[tail];
    s_ring_tail = (tail + 1U) & (MAX30102_RING_DEPTH - 1U);
    intc_m_enable_irq(IRQn_HDMA);

    if (out != NULL) {
        out->red = f.red;
        out->ir  = f.ir;
    }
    if (t_ms != NULL) {
        *t_ms = f.t_ms;
    }
    return true;
}

void max30102_ts_sync(void)
{
    uint32_t now = hr_now_ms();

    /* 只往前拽，而且必须"环形缓冲真空了"才拽：缓冲里还压着货的时候游标落后
     * 是正常的（那是没发完的积压），这时候拽一下会让还没发的样本凭空跳一段。
     * 真空了还落后，说明那段时间**根本没有样本**（传感器掉了/刚恢复）——
     * 这段空洞就该如实反映成时间轴往前跳一格。 */
    intc_m_disable_irq(IRQn_HDMA);
    if (s_ring_head == s_ring_tail &&
        (int32_t)(now - s_ts_next) > (int32_t)MAX30102_TS_MAX_LAG_MS) {
        s_ts_next = now;
    }
    intc_m_enable_irq(IRQn_HDMA);
}

void max30102_dma_get_stats(max30102_dma_stats_t *out)
{
    if (out == NULL) {
        return;
    }
    intc_m_disable_irq(IRQn_HDMA);
    out->ovf         = (uint8_t)s_ovf;
    out->raw_wr      = s_raw_wr;
    out->raw_rd      = s_raw_rd;
    out->fail_streak = s_fail_streak;
    out->ring_drop   = s_ring_drop;
    out->last_fail   = s_last_fail;
    /* **只在驱动内部相减**（同一个 mchtmr 时钟），见头文件那句警告。
     * 截到 60 s：这个数只用来判"多久没样本了"，真等久了报个上限就够。 */
    {
        uint32_t d = hr_now_ms() - s_last_sample_ms;
        out->no_sample_ms = (d > 60000U) ? 60000U : d;
    }
    intc_m_enable_irq(IRQn_HDMA);
}

void max30102_dma_clear_fail(void)
{
    intc_m_disable_irq(IRQn_HDMA);
    s_fail_streak = 0;
    s_last_fail   = "";
    intc_m_enable_irq(IRQn_HDMA);
}

bool max30102_algo_pop(uint32_t *t_ms, uint32_t *ir)
{
    uint32_t tail;
    hr_arng_t f;

    intc_m_disable_irq(IRQn_HDMA);
    if (s_arng_head == s_arng_tail) {
        intc_m_enable_irq(IRQn_HDMA);
        return false;
    }
    tail = s_arng_tail;
    f    = s_arng[tail];
    s_arng_tail = (tail + 1U) & (MAX30102_ALGO_RING_DEPTH - 1U);
    intc_m_enable_irq(IRQn_HDMA);

    if (t_ms != NULL) {
        *t_ms = f.t_ms;
    }
    if (ir != NULL) {
        *ir = f.ir;
    }
    return true;
}

uint32_t max30102_algo_drops(void)
{
    uint32_t d;

    intc_m_disable_irq(IRQn_HDMA);
    d = s_arng_drop;
    intc_m_enable_irq(IRQn_HDMA);
    return d;
}

void max30102_ring_flush(void)
{
    intc_m_disable_irq(IRQn_HDMA);
    s_ring_tail = s_ring_head;
    s_arng_tail = s_arng_head;
    intc_m_enable_irq(IRQn_HDMA);
}

hpm_stat_t max30102_i2c_recover(hpm_i2c_context_t *i2c_ctx)
{
    hpm_stat_t stat;

    /* 四步，顺序照 imu_project/user_app/src/mpu6050.c:412 的
     * mpu6050_i2c_recover()。**最后一步重挂 DMAMUX 不能省** —— 那边踩过：
     * 少了它，I2C 起来了但 DMA 请求永远不来，表现成"恢复成功但没数据"。 */
    dma_disable_channel(BOARD_APP_I2C_DMA, MAX30102_DMA_CH);
    i2c_dma_disable(BOARD_APP_I2C_BASE);

    max30102_i2c_bus_recovery();          /* 内含 i2c_reset() + init_i2c_pins() */

    stat = hpm_i2c_initialize(i2c_ctx);
    if (stat != status_success) {
        return stat;
    }

    dmamux_config(BOARD_APP_I2C_DMAMUX, HR_I2C_DMAMUX_CH, BOARD_APP_I2C_DMA_SRC, true);

    return status_success;
}
