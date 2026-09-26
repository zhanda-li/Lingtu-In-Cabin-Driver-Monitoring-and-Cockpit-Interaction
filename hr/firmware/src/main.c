/*
 * 心率节点固件 —— HPM5300EVK + MAX30102（I2C0）→ UART0 @115200
 *
 * 数据流：
 *   MAX30102 FIFO（100 Hz、18 bit、RED+IR）
 *     → DMA + 中断链取到**两条**环形缓冲（1 ms 一拍起头，相位推进在 ISR 里）
 *         ├─ 串口环：串口有空位时才弹出、按行打原始计数
 *         └─ 算法环：主循环**无条件**排空 → hr_algo_push()
 *     → PC 侧 dms_project/ui/serial_hr.py 算心率 / RMSSD / PI
 *     → 网页端 dms_project/ui/web/index.html 的「心率（实时）」格显示
 *   （板端自己也算一份，只从这里那个 H 行出去，见下）
 *
 * ── 串口协议（每行一个前缀，PC 侧按前缀分派；行尾 \r\n）──────────────────
 *   #<text>              状态/横幅，人读的，PC 侧只记日志
 *   D,<t_ms>,<red>,<ir>  一个样本（100 Hz）
 *   H,<t_ms>,<hr>,<rmssd>,<pi>   板端自算的三个量（1 Hz）。`--` = 量不出来。
 *                        ⚠️ 这三个数**只给 SES 终端和交叉校验看，不上网页** ——
 *                        页面上那一格认的是 PC 侧 `serial_hr.py` 的那份
 *                        （它多了频谱兜底、五道门、化石修复，都验过）。
 *                        **`D,` 行一个字节都不许动**：`serial_hr.py` 那边是
 *                        `if len(f) != 4: bad_lines += 1`，多一段当场全变坏行。
 *   E,<code>,<text>      错误。code 1=芯片没答话/初始化失败
 *                              2=FIFO 溢出（我们没跟上，中间有样本丢了）
 *                              3=I2C 读失败（会重建链路）
 *
 * 为什么每行带 t_ms：就算样本不丢，PC 侧也要靠它把 IBI 算准（几十 ms 的分辨率）。
 * 为什么带 red：心率只用 IR。red 一起打出来是为了血氧（SpO2 需要 R =
 * (Red_AC/Red_DC)/(IR_AC/IR_DC)），以及"两个通道是否同步受扰"的诊断。
 *
 * ── 2026-09-26 改造：从阻塞轮询换成 DMA + ISR（照 imu_project）──────────
 * 改造前是 0.5 ms 阻塞轮询：2000 次/秒 × 每次 4 个总线相位 ≈ 8000 笔/秒、
 * 总线占用 ~36%；而且**任何一次读失败都会 up=false → 整个 max30102_init()
 * 重跑**，重初始化期间 D 流出现空洞 → PC 侧丢拍。这次改成：
 *   · 1 ms 一拍、DMA 突发读（一次拿全 WR/RD 指针 + 溢出计数，总线相位砍半）
 *   · 相位推进在 IRQn_HDMA 里，主循环只起头 + 取货
 *   · 失败只计连败，**连续 20 拍**才升级成重建链路（瞬时抖动不再打洞）
 *   · D 流改成"串口有空位才从环形缓冲取"，不再走有损的 print_nb 丢弃路径
 */
#include "board.h"
#include "hpm_i2c.h"
#include "hpm_csr_drv.h"
#include "hpm_gpio_drv.h"

#include <stdio.h>

#include "hr_algo.h"
#include "max30102.h"
#include "print_nb.h"

/* 标称采样率，用于横幅与 #cfg 上报。真正的采样周期在 max30102.h 里
 * （MAX30102_SAMPLE_PERIOD_MS），时间戳游标按那个步进。 */
#define SAMPLE_RATE_HZ      (100U)

/* 主循环节拍。FIFO 每 10 ms 进一个样本，1 ms 一拍 = 10 倍过采样。
 * 注意实际节拍会被串口拖慢到 ~2.4 ms（一行 D 是 27 B 的硬时间），
 * 那仍然是 4 倍过采样 —— 见循环开头的配速重基准。 */
#define TICK_PERIOD_US      (1000U)

/* 芯片没答话之后多久重试一次。用户可能先给板子上电、再插传感器模块，
 * 所以这里必须能自愈，而不是开机失败就永远停在那儿。 */
#define RETRY_PERIOD_US     (1000000U)

/* 相位卡多久算卡住。1 ms 节拍下正常每一拍都该回到 IDLE，20 ms 已经很宽松。 */
#define PHASE_STUCK_MS      (20U)

/* 链路活着（I2C 每次都答话）但**一个样本都没有**多久算异常。
 * 无手指时芯片照样在 100 Hz 采样，所以 2 秒没有样本只能是芯片状态不对。 */
#define SAMPLE_TIMEOUT_MS   (2000U)

/* 连续多少拍失败就升级成"重建链路"。1 ms 名义节拍 ≈ 20 ms，实际约 50 ms
 * （串口拖慢后一拍约 2.4 ms）—— 够滤掉瞬时抖动，又短到人感觉不出来。 */
#define ESCALATE_TICKS      (20U)

/* 一拍最多补几行。串口积压太久（比如 PC 刚打开端口）时会一次弹出很多样本，
 * 不限个数的话一拍能跑掉几十毫秒，把相位看门狗和配速全带偏。 */
#define POP_BURST_MAX       (4U)

static hpm_i2c_context_t s_i2c_ctx;
static max30102_t        s_dev;

/* ── 板端心率算法（第二份实现，见 hr_algo.h 开头）────────────────────────
 * 🔴 它的结果**不上网页**。页面上的数只认 PC 那份（多了频谱兜底、五道门、
 *    化石修复，都验过）。这一份的用途只有一个：让这三个数出现在 SES 的
 *    串口终端里（用户点名要的），以及给交叉校验提供可并排比较的第二列。 */
static hr_algo_t s_algo;

/* 最近一次喂给算法的样本时刻（**样本钟**）。`hr_algo_emit_due` 用它做 1 Hz
 * 节流 —— 用样本钟而不是 `hr_now_ms()` 是为了让离线放录时能复现同一串节拍。
 * `s_algo_seen` 用来压掉"一个样本都还没来"时那一行空 `H,0,--,--,--`。 */
static uint32_t s_algo_last_ms;
static bool     s_algo_seen;

static uint32_t s_cpu_freq;
static uint32_t s_cycles_per_tick;
static uint32_t s_cycles_retry;

/*
 * 把三个量格式化成 `H` 行的三列。**全定点，不用 `%f`** —— 两个理由：
 *   · 省下 newlib 浮点 printf 的几 KB（`%f` 会把整套浮点格式化拖进来）；
 *   · 输出可逐字节比对，离线 A/B 能直接比字符串而不必先解析成浮点。
 *
 * ⚠️ 舍入是**四舍五入（.5 进位）**，Python 的 `round()` 是**银行家舍入**（.5 取偶）。
 *    两者只在正好落在 .5 上时才不同，而实测那些值不落在 .5 上；真要卡在 tie 上
 *    也就是最后一位差 1。A/B 脚本比的是"解析成数之后差 ≤ 半个最低位"，不是字符串相等。
 *
 * 量不出来就给 `--`（**绝不拿 0 顶替**：0 是个合法读数）。
 */
static void hr_format_row(const hr_algo_t *a, char *b_hr, char *b_rr, char *b_pi)
{
    double v;

    if (hr_algo_hr(a, &v)) {
        uint32_t x10 = (uint32_t)(v * 10.0 + 0.5);
        snprintf(b_hr, 12, "%u.%u", (unsigned)(x10 / 10U), (unsigned)(x10 % 10U));
    } else {
        snprintf(b_hr, 12, "--");
    }
    if (hr_algo_rmssd(a, &v)) {
        snprintf(b_rr, 12, "%u", (unsigned)(uint32_t)(v + 0.5));
    } else {
        snprintf(b_rr, 12, "--");
    }
    if (hr_algo_pi(a, &v)) {
        uint32_t x100 = (uint32_t)(v * 100.0 + 0.5);
        snprintf(b_pi, 12, "%u.%02u", (unsigned)(x100 / 100U),
                 (unsigned)(x100 % 100U));
    } else {
        snprintf(b_pi, 12, "--");
    }
}

static uint32_t now_ms(void)
{
    return (uint32_t)(hpm_csr_get_core_mcycle() / (s_cpu_freq / 1000U));
}

static void print_banner(void)
{
    printf("\n");
    printf("====================================================\n");
    printf(" MAX30102 heart-rate node   HPM5300EVK / HPM5361\n");
    printf("====================================================\n");
    printf("  built        : %s %s\n", __DATE__, __TIME__);
    printf("  cpu freq     : %u Hz\n", (unsigned)s_cpu_freq);
    printf("  i2c0         : SCL=PB02 SDA=PB03 400kHz  addr=0x%02X\n",
           (unsigned)MAX30102_ADDR_7BIT);
    printf("  console      : UART0 115200 (FT2232 channel B)\n");
    printf("  sample rate  : %u Hz, %u bits, RED+IR (SpO2 mode)\n",
           (unsigned)SAMPLE_RATE_HZ, 18U);
    printf("  registers    : spo2=0x%02X fifo=0x%02X led=0x%02X\n",
           (unsigned)MAX30102_SPO2_CFG, (unsigned)MAX30102_FIFO_CFG,
           (unsigned)MAX30102_LED_PA);
    printf("  acquire      : DMA ch%u + IRQn_HDMA, tick %u us, ring %u\n",
           (unsigned)MAX30102_DMA_CH, (unsigned)TICK_PERIOD_US,
           (unsigned)MAX30102_RING_DEPTH);
    printf("  stream       : D,<t_ms>,<red>,<ir>   (100 Hz, 无损)\n");
    printf("                 H,<t_ms>,<hr>,<rmssd>,<pi>   (1 Hz, 板端自算)\n");
    printf("----------------------------------------------------\n");
}

/*
 * ── 总线体检（诊断用）───────────────────────────────────────────────────
 * 把 PB02/PB03 临时切成 GPIO 输入，各读两次电平，然后把 I2C 功能装回去。
 *
 * 为什么需要：串口上的 `E,1,init stat=3` 只说"超时"，而超时的来路有好几种 ——
 * 线没接、插错脚、被短路按住、对面没供电 —— **从这一行里分不出来**。
 * 2026-09-26 现场就卡在这儿：用户按完手指模块失联，重插、RESET、整板断电全无效，
 * 手上没有万用表，只能靠板子自己把这两条线的电平报出来。
 *
 * 判读（这两条线**两边都有上拉**：EVK pinmux 的内部上拉 + 模块自带 10 kΩ）：
 *   pull off 读 11 → 外部上拉在 → 模块的 I2C 侧连着呢
 *   pull off 里出现 0 → 那条线**没有外部上拉**：线不通 / 插到 GND / 被主动按住
 *   pull on  里出现 0 → 连我们自己的上拉都拉不起来 → 被死死按住（对地短路）
 * 为什么要读两次：只读一次分不出"没人拉高"和"被按住拉低"——那是两种病。
 *
 * 只在失败路径上调用：**成功路径上一次都不碰这两条线**。
 * （放在失败分支里是有意的：若放在 max30102_init 之前，正常但临界的总线可能
 *   被这一次倒腾弄坏 → 每秒失败一次 → 永远起不来。）
 */
static void bus_probe(void)
{
    static const uint32_t k_ioc[2]  = { IOC_PAD_PB02, IOC_PAD_PB03 };   /* 0=SCL 1=SDA */
    static const uint32_t k_func[2] = { IOC_PB02_FUNC_CTL_GPIO_B_02,
                                        IOC_PB03_FUNC_CTL_GPIO_B_03 };
    uint8_t lv_on[2], lv_off[2];

    for (int k = 0; k < 2; k++) {
        uint32_t port = GPIO_GET_PORT_INDEX(k_ioc[k]);
        uint8_t  pin  = GPIO_GET_PIN_INDEX(k_ioc[k]);

        HPM_IOC->PAD[k_ioc[k]].FUNC_CTL = k_func[k];
        gpio_set_pin_input(HPM_GPIO0, port, pin);

        /* 我们的上拉开：拉不起来 = 有东西在按住它 */
        HPM_IOC->PAD[k_ioc[k]].PAD_CTL = IOC_PAD_PAD_CTL_PE_SET(1)
                                       | IOC_PAD_PAD_CTL_PS_SET(1);
        board_delay_us(100);
        lv_on[k] = gpio_read_pin(HPM_GPIO0, port, pin) ? 1U : 0U;

        /* 我们的上拉关：这时还读到高，就只可能是**外部**上拉（模块那 10 kΩ）*/
        HPM_IOC->PAD[k_ioc[k]].PAD_CTL = 0;
        board_delay_us(100);
        lv_off[k] = gpio_read_pin(HPM_GPIO0, port, pin) ? 1U : 0U;
    }

    /* 装回 I2C 功能。**不调 i2c_reset()**：那会清掉 hpm_i2c_initialize() 配好的
     * 控制器寄存器，体检一次就把总线废掉，正是上面注释里要躲的那个坑。 */
    init_i2c_pins(BOARD_APP_I2C_BASE);

    print_nb("#bus,scl=%u sda=%u (pull on) scl=%u sda=%u (pull off)\n",
             (unsigned)lv_on[0], (unsigned)lv_on[1],
             (unsigned)lv_off[0], (unsigned)lv_off[1]);
}

/*
 * ── 开机一次性诊断（只跑两趟，各一行 # 行）──────────────────────────────
 * 第一次初始化成功之后立刻（`#dia1`）、再过约 1.5 s（`#dia2`）各打印一次：
 * 用**阻塞 I2C** 把配置寄存器和 FIFO 三指针读回来，同时附上 DMA 链最近一次
 * 读到的指针原始值。
 *
 * 为什么值得专门写它：DMA 链报告"FIFO 是空的"时，有两种**完全同形**的可能 ——
 *   ① 芯片真的没在采样；
 *   ② 我们的 DMA 读根本没把数据搬进缓冲（缓冲里还是初值 0，于是 wr==rd==0）。
 * 从 D 流上一个字都看不出来。阻塞读一遍就是仲裁：
 *   两次里只要出现过 wr != 0，或者 dia2 的 wr 比 dia1 大 → 芯片在采样 → 是②
 *   两次都是 wr==0 且 rd==0                            → 芯片没采样 → 是①
 */
static void diag_dump(const char *tag, const max30102_dma_stats_t *st)
{
    uint8_t wr = 0, ovf = 0, rd = 0;
    uint8_t id = 0, mode = 0, fcfg = 0, scfg = 0, led = 0;
    hpm_stat_t s1 = max30102_read_ptrs(&s_dev, &wr, &ovf, &rd);

    (void)max30102_read_reg(&s_dev, MAX30102_REG_PART_ID, &id);
    (void)max30102_read_reg(&s_dev, MAX30102_REG_MODE_CONFIG, &mode);
    (void)max30102_read_reg(&s_dev, MAX30102_REG_FIFO_CONFIG, &fcfg);
    (void)max30102_read_reg(&s_dev, MAX30102_REG_SPO2_CONFIG, &scfg);
    (void)max30102_read_reg(&s_dev, MAX30102_REG_LED1_PA, &led);

    print_nb("#dia%s,blk=%d wr=%u ovf=%u rd=%u,dma wr=%u rd=%u,"
             "id=0x%02X mode=0x%02X fifo=0x%02X spo2=0x%02X led=0x%02X\n",
             tag, (int)s1, (unsigned)wr, (unsigned)ovf, (unsigned)rd,
             (unsigned)st->raw_wr, (unsigned)st->raw_rd,
             (unsigned)id, (unsigned)mode, (unsigned)fcfg,
             (unsigned)scfg, (unsigned)led);
}

/*
 * 把链路拉起来：必要时先重建 I2C（含总线恢复），再跑初始化序列，最后挂 DMA。
 * 返回 true = 可以开始收样本了。
 *
 * *i2c_up 是进出两用：进来 false 时先走 max30102_i2c_recover()；成功才置 true。
 * 开机时控制器已经起好了（=true），这一分支不会重复动它。
 */
static bool bring_up(bool *i2c_up)
{
    hpm_stat_t stat;
    uint8_t    id = 0;

    if (!*i2c_up) {
        /* max30102_i2c_recover 内含总线恢复 + hpm_i2c_initialize + 重挂 DMAMUX，
         * 四步顺序不能换（见 max30102.h）。 */
        stat = max30102_i2c_recover(&s_i2c_ctx);
        if (stat != status_success) {
            print_nb("E,3,i2c_initialize stat=%d\n", (int)stat);
            bus_probe();
            return false;
        }
        *i2c_up = true;
    }

    stat = max30102_init(&s_dev, &id);
    if (stat == status_success) {
        max30102_dma_attach(&s_dev);
        printf("  max30102 up  : PART_ID=0x%02X (expected 0x%02X)\n",
               (unsigned)id, (unsigned)MAX30102_PART_ID_EXPECTED);
        print_nb("#cfg,sr=%u,led=0x%02X,spo2=0x%02X\n",
                 (unsigned)SAMPLE_RATE_HZ,
                 (unsigned)MAX30102_LED_PA,
                 (unsigned)MAX30102_SPO2_CFG);
        return true;
    }

    /* 原始返回码 + 芯片实际答的 PART_ID 一起给出：0x00/0xFF 说明
     * 对面没答话（没供电 / SDA SCL 反了 / VCC 电平不对），
     * 别的值说明答话的是另一颗芯片。 */
    print_nb("E,1,init stat=%d part_id=0x%02X\n", (int)stat, (unsigned)id);
    /* 紧随其后把两条线的真实电平报出来 —— "超时"这个词本身
     * 分不出是线没通还是被按住，见 bus_probe() 的注释。 */
    bus_probe();
    return false;
}

int main(void)
{
    bool     up        = false;
    bool     i2c_up    = false;
    uint8_t  ovf_last  = 0;
    uint32_t drop_last = 0;
    uint32_t algo_drop_last = 0;
    uint8_t  dia_stage = 0;     /* 开机一次性诊断：0=待做 1=已打 dia1 2=做完 */
    uint32_t dia_t0    = 0;

    board_init();

    s_cpu_freq        = clock_get_frequency(clock_cpu0);
    s_cycles_per_tick = s_cpu_freq / (1000000U / TICK_PERIOD_US);
    s_cycles_retry    = s_cpu_freq / (1000000U / RETRY_PERIOD_US);

    print_banner();

    /*
     * ── I2C0 起板 ────────────────────────────────────────────────────────
     * 顺序照 can_project/src/imu_node.c:271-277，三处都不能换位：
     *
     * · 分频必须在 board_init_i2c_clock() **之前** —— 那个函数内部会
     *   clock_get_frequency(clock_i2c0) 把频率交给调用方，先读后设读到的是旧值。
     *   SDK 原版的 init_i2c0_clock()（boards/hpm5300evk/clock.c:80）只有
     *   clock_add_to_group，没有这一行；少了它不会报错（hpm_i2c_initialize 按
     *   实际频率自适应），只是 400 kHz 偏成一个别的数 —— 属于"不崩所以查不出来"。
     * · 总线恢复必须在 hpm_i2c_initialize() **之前**（理由见 max30102.h）。
     */
    clock_set_source_divider(clock_i2c0, clk_src_pll0_clk0, 10);   /* → 96 MHz */
    uint32_t i2c_clk_hz = board_init_i2c_clock(BOARD_APP_I2C_BASE);
    init_i2c_pins(BOARD_APP_I2C_BASE);

    hpm_i2c_get_default_init_context(&s_i2c_ctx);
    s_i2c_ctx.base              = BOARD_APP_I2C_BASE;
    s_i2c_ctx.init_config.speed = i2c_speed_400khz;

    max30102_i2c_bus_recovery();

    hpm_stat_t stat = hpm_i2c_initialize(&s_i2c_ctx);
    if (stat != status_success) {
        /* 起不来也**不停机**：下面 !up 那条路会走 max30102_i2c_recover()，
         * 每个重试周期重建一次。改造前这里是 for(;;) 死等，等于把"能自愈"
         * 的承诺做废了一半。 */
        print_nb("E,3,i2c_initialize stat=%d\n", (int)stat);
        printf("  >> i2c_initialize failed (%d), will retry in loop.\n", (int)stat);
    } else {
        i2c_up = true;
        printf("  i2c0 up      : %u Hz bus clock\n", (unsigned)i2c_clk_hz);
    }

    s_dev.base = s_i2c_ctx.base;
    s_dev.addr = MAX30102_ADDR_7BIT;

    uint64_t next = hpm_csr_get_core_mcycle();

    for (;;) {
        /*
         * ── 配速（放在循环**最前面**）────────────────────────────────────
         * 放最前面是因为：身体里任何一条 continue 都会跳过循环末尾的等待。
         * 改造前 main.c:240/:258 的 continue 就是这么把配速整个跳掉的。
         * 放前面之后，"只有这一处等待"成了结构上的事实，不靠人记得。
         *
         * 重基准：一行 D 是 27 B ≈ 2.4 ms 的硬时间，塞不进 1 ms 的预算，
         * 所以正常情况下每一拍都会略微落后。不重基准的话 next 会一路累积着
         * 落后（经典的死亡螺旋，越忙越慢）；超过 3 拍就直接对齐到当前时刻。
         */
        while (hpm_csr_get_core_mcycle() < next) {
        }
        next += s_cycles_per_tick;
        if (hpm_csr_get_core_mcycle() > next + 3U * s_cycles_per_tick) {
            next = hpm_csr_get_core_mcycle();
        }

        /*
         * ── 1. 发 D 行：**串口有空位才从环形缓冲取** ────────────────────
         * 这是"无损"的关键：print_nb() 拥塞时整行丢（它自己的头文件写着
         * "凡是必须一条不落的数据都不能走串口"）。所以闸门放在**取**这一步
         * —— 串口没空位就让它留在环形缓冲里，而不是取出来再丢掉。
         * 判据用的就是 print_nb 内部那个 uart_tx_congested()。
         */
        {
            max30102_sample_t f;
            uint32_t          t_ms;
            uint32_t          lines = 0;

            while (!uart_tx_congested() && max30102_sample_pop(&f, &t_ms)) {
                print_nb("D,%u,%u,%u\n",
                         (unsigned)t_ms, (unsigned)f.red, (unsigned)f.ir);
                if (++lines >= POP_BURST_MAX) {
                    break;
                }
            }
        }

        /* 时间戳游标的追赶闸门（只在环形缓冲真空了时才往前拽）。 */
        max30102_ts_sync();

        /*
         * ── 1b. 排空算法环（**无条件**，不看串口拥塞）────────────────────
         * 算法必须看到每一个样本，理由见 max30102.h 的 `max30102_algo_pop`。
         * 这里**不设 burst 上限**：环里最多 128 个，一次排空最坏也就 128 次
         * 软浮点滤波（约 0.4 ms），而留积压的代价是让算法看到一段时间轴错位
         * 的流 —— 那正是加这条环要避免的事。
         */
        {
            uint32_t at, air;
            while (max30102_algo_pop(&at, &air)) {
                hr_algo_push(&s_algo, at, air);
                s_algo_last_ms = at;
                s_algo_seen    = true;
            }
        }

        /* 算法环满过 = 主循环卡住超过 1.28 s。和 ring drop 分开报，
         * 否则"丢了多少"这件事在串口上还是各说一半。 */
        {
            uint32_t ad = max30102_algo_drops();
            if (ad != algo_drop_last) {
                print_nb("E,2,algo drop %u\n", (unsigned)ad);
                algo_drop_last = ad;
            }
        }

        /*
         * ── 1c. 1 Hz 打一行 `H` ──────────────────────────────────────────
         * `H,<t_ms>,<hr>,<rmssd>,<pi>`。**量不出来一律 `--`，绝不用 0 顶替**
         * —— 0 是个合法读数，拿它表示"没有"就再也分不出这两种了。
         * 节流用样本钟（见 hr_algo.h 的 `HR_EMIT_PERIOD_MS`）。
         * 走 print_nb（拥塞就丢、不等）：约 30 B 摊到 1000 ms 是 0.26% 的
         * 串口预算，不值得为它阻塞，丢了靠 t_ms 也能看出缺了哪一秒。
         */
        if (s_algo_seen && hr_algo_emit_due(&s_algo, s_algo_last_ms)) {
            char b_hr[12], b_rr[12], b_pi[12];

            hr_format_row(&s_algo, b_hr, b_rr, b_pi);
            print_nb("H,%u,%s,%s,%s\n", (unsigned)s_algo_last_ms, b_hr, b_rr, b_pi);
        }

        if (!up) {
            if (bring_up(&i2c_up)) {
                up        = true;
                ovf_last  = 0;
                drop_last = 0;      /* attach 里把两条环形缓冲和丢帧计数一起清了 */
                algo_drop_last = 0;
                if (dia_stage == 0) {
                    max30102_dma_stats_t d;
                    max30102_dma_get_stats(&d);
                    diag_dump("1", &d);
                    dia_stage = 1;
                    dia_t0    = now_ms();
                }
            } else {
                /* 等满一个重试周期再试。next 直接重新基准到"现在 + 1 s"，
                 * 不做补偿（突发重试等于把失败当成积压去追，没意义）。 */
                next = hpm_csr_get_core_mcycle() + s_cycles_retry;
            }
            continue;
        }

        max30102_dma_stats_t st;

        max30102_dma_get_stats(&st);

        /* 开机诊断的第二份（隔 1.5 s 再读一遍指针，看它有没有往前走）。 */
        if (dia_stage == 1 && (now_ms() - dia_t0) >= 1500U) {
            diag_dump("2", &st);
            dia_stage = 2;
        }

        /* ── 2. 起下一拍；卡住了就按失败计 ── */
        if (max30102_dma_phase_is_idle()) {
            (void)max30102_dma_kick();
        } else if (max30102_dma_phase_stuck_ms() > PHASE_STUCK_MS) {
            print_nb("E,3,phase stuck %u ms\n", (unsigned)max30102_dma_phase_stuck_ms());
            max30102_dma_abort();
        }

        /* ── 3. 溢出：回卷关着（见 max30102.h），每 +1 = 真丢了一个样本 ── */
        if (st.ovf != ovf_last) {
            print_nb("E,2,ovf %u\n", (unsigned)st.ovf);
            ovf_last = st.ovf;
        }

        /* 环形缓冲丢帧 = 串口堵住了（PC 那边没在读）。它和 ovf 是两回事：
         * ovf 是芯片 FIFO 满了，这个是我们的缓冲满了。两个都得报，
         * 否则"丢了多少"这件事在串口上会各说一半。 */
        if (st.ring_drop != drop_last) {
            print_nb("E,2,ring drop %u\n", (unsigned)st.ring_drop);
            drop_last = st.ring_drop;
        }

        /* ── 4. 升级：连败到线，或者链路活着却久不出样本 ── */
        if (st.fail_streak >= ESCALATE_TICKS) {
            print_nb("E,3,retry exhausted %u %s\n",
                     (unsigned)st.fail_streak,
                     (st.last_fail != NULL) ? st.last_fail : "");
        } else if (st.no_sample_ms > SAMPLE_TIMEOUT_MS) {
            print_nb("E,3,no sample %u ms\n", (unsigned)st.no_sample_ms);
        } else {
            continue;               /* 一切正常，这一拍到此为止 */
        }

        /* 走到这儿 = 要重建链路。顺序：拆 DMA → 恢复 I2C → 重跑初始化 → 重挂。 */
        max30102_dma_detach();

        if (max30102_i2c_recover(&s_i2c_ctx) == status_success) {
            i2c_up = true;
            if (bring_up(&i2c_up)) {
                /* 空洞里的样本是在**另一个时基**上攒的，别混进新流里。
                 * 时间戳游标不清零 —— 它会由 ts_sync 往前拽一格，
                 * 对 PC 侧就是一段如实的时间空洞，不是"板子复位了"。 */
                max30102_ring_flush();
                max30102_dma_clear_fail();
                up        = true;
                ovf_last  = 0;
                drop_last = 0;
                algo_drop_last = 0;
                continue;
            }
        }

        /* 重建不成功：退回"未就绪"，按 1 s 的节奏重试（保留原有的自愈节奏）。 */
        max30102_ring_flush();
        up     = false;
        i2c_up = false;
        next   = hpm_csr_get_core_mcycle() + s_cycles_retry;
    }
}
