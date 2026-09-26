/*
 * 心率算法（板端）：从 MAX30102 的原始 IR 计数算出心率 / HRV-RMSSD / PI。
 *
 * ── 它为什么存在 ────────────────────────────────────────────────────────
 * 算法原来**全在 PC 上**（`ui/serial_hr.py` 的 `_HrTracker`），板子只往外吐原始
 * 计数。用户要「在 segger 串口再来三列输出这个」—— 而串口是**单向**的，PC 上
 * 算出来的数回灌不进 SES 那个终端。所以只能在板子上再算一遍，另起一行 `H,`。
 *
 * 🔴 **两边各算各的，谁也不许"修正"谁。** 页面上的数**只认 PC 那份**（它多了
 *    频谱兜底、五道门、化石修复，都验过）；板端这份只出现在串口和交叉校验报告里。
 *    验收 4.4 会把两边的 `hr`/`rmssd`/`pi` 并排打出来，**对不上就如实报，
 *    不许调常数去凑**。
 *
 * ── 与 `ui/serial_hr.py` 的关系：这是**镜像**，不是"重新设计" ─────────────
 * 每一个常数、每一处运算顺序都是从那边逐字抄过来的。抄错一处不会崩，只会
 * **安静地差一点** —— 所以配套 `_scratch/_hr_algo_host.c`（宿主驱动，直接跑真 C）
 * 和 `_scratch/_hr_board_ab.py`（三级逐样本比对）。
 *
 * ⚠️ **本文件不许 include 任何 SDK 头**（只用 `<stdint.h>/<stdbool.h>/<math.h>`）。
 *    理由：宿主驱动要能**直接编这个文件**（`_scratch/_cl.bat`，MSVC x64），
 *    SDK 头一进来就编不了了，离线对拍这条路当场断掉。这也是这份算法核心
 *    被单独拆成一个 .c 的原因。
 *
 * ── 三条硬技术要求（缺一条就白做）────────────────────────────────────────
 * 1. **带通系数硬编码**（见 .c 底部那张表）。不让板端跑 `sinf/cosf`、也不让 PC 跑
 *    `math.cos` 当场算 —— libm 与 numpy 差 1 ulp 是个永远说不清的变量。系数在 PC
 *    上算一次、`float.hex()` 出精确字面量写进两边；`_check_hr_algo.py` 有一条断言
 *    卡死"三节系数必须与字面量逐位相同"，否则有人动了 `BP_LOW_HZ` 板端会**静默**失配。
 * 2. **直流滑窗用整数**（`uint32_t dc_win[HR_FINGER_DC_WIN]` + `uint64_t dc_sum`）。
 *    PC 侧是 float64 累加**整数**（严格精确）；板端照抄成 `float` 会变成随机游走
 *    —— 15 秒 σ≈19 counts、十小时 σ≈950 counts，**而且永远追不回来**（滑窗只减掉
 *    "该减的"，减不掉已经积累的舍入误差）。用整数之后两边逐位一致、且零浮点。
 * 3. **滤波器状态用 `double`、运算顺序逐字照抄、并显式关掉 FMA 收缩**
 *    （`-ffp-contract=off`，见 CMakeLists）。现在默认软浮点、rv32imac 没有 F 扩展，
 *    硬件上不会真收缩 —— **但这条不该靠"目标恰好没有 FMA"来保证**：哪天切到 `hf`
 *    那份（ilp32d，有 F/D）结果就会变，而且是只在某些样本上差一点的那种变。
 */
#ifndef HR_ALGO_H
#define HR_ALGO_H

#include <stdint.h>
#include <stdbool.h>

#ifdef __cplusplus
extern "C" {
#endif

/* ============================================================================
 * 共享常数 —— 🔴 **必须与 `ui/serial_hr.py` 逐字相同**
 * ============================================================================
 * 改这里不同时改那边，两边就会静默地对不上，而"对不上"本身看不出是哪边错了。
 * 每个数在 `ui/serial_hr.py` 里都有一大段推导，**别在这儿重复推导、也别在这儿
 * 自己调** —— 要调去调 PC 那边，然后把值搬过来。
 */

/* 采样率。板端由 `MAX30102_SAMPLE_PERIOD_MS` 决定（100 Hz）。 */
#define HR_FS_HZ                (100)

/* 手指在位的判据：最近 1 秒 IR 均值 ≥ 它。**量出来的**：空载 IR ≈ 8450。 */
#define HR_FINGER_DC_WIN        (100)          /* = 1 s @100 Hz */
#define HR_FINGER_DC_MIN        (20000.0)

/* 带通 0.65 ~ 3.5 Hz（4 阶巴特沃斯高通两节 + 一节低通）。 */
#define HR_BP_LOW_HZ            (0.65)
#define HR_BP_HIGH_HZ           (3.5)

/* 峰值判据：包络的 45%，只在"从上方跌回下方"那一刻登记，登记的是**峰顶时刻**。 */
#define HR_PEAK_FRAC            (0.45)
#define HR_ENV_DECAY            (0.995)

/* 单个间隔的允许范围（**整数毫秒**）。330 = 180 BPM、1600 = 37 BPM。 */
#define HR_MIN_IBI_MS           (330)
#define HR_MAX_IBI_MS           (1600)

/* 中位数窗口与出数的最少间隔数（4 个间隔 = 至少 5 次心跳、约 4 秒）。 */
#define HR_BEATS_KEPT           (8)
#define HR_MIN_BEATS            (4)

/* 间隔离散度（MAD/中位间隔）上限。⚠️ 这个闸**分不开好和坏**（详见
 * `ui/serial_hr.py` 的 `MAX_IBI_SPREAD` 那段），PC 侧靠频谱兜底补的，板端
 * **没有兜底** —— 所以 `H` 行的 `hr` 会经常是 `--`，那是与 PC 一致的诚实行为。 */
#define HR_MAX_IBI_SPREAD       (0.20)

/* 主路时效：最后一个**被采纳**的间隔距今超过它就不出数（治"化石"）。 */
#define HR_IBI_FRESH_MS         (4000)

/* 交流幅度下限。**唯一的绝对尺度判据** —— 见 `ui/serial_hr.py` 的 `AC_MIN_RMS`。
 * ⚠️ PC 侧量它的函数 `ac_rms()` 用的是 **25 Hz / 10 秒**那个缓冲；板端没有那个
 *    缓冲（它是给频谱兜底用的），用的是 PI 那个 **3 秒 / 100 Hz** 窗。
 *    同一个频带、同一个量（RMS），所以阈值可以搬 —— 但两者**不是同一个随机变量**，
 *    交叉校验时可能一边出一个不出，那是这个差异、不是 bug。 */
#define HR_AC_MIN_RMS           (20.0)

/* ---- RMSSD ---- */
/* 连续 NN 跨度门槛。用户点名要的「只等 30s 稳定之后才输出，前 30 秒显示 --」。 */
#define HR_NN_NEED_MS           (30000)
/* NN 环深。**必须 ≥ 理论上限** 30000/330 + 1 = 92，取 128 留余量。
 * 下面那条 `#if` 把"改了 HR_MIN_IBI_MS 就得同时看这里"变成编译期错误。 */
#define HR_NN_MAX               (128)
#if (HR_NN_NEED_MS / HR_MIN_IBI_MS + 2) > HR_NN_MAX
#error "HR_NN_MAX 小于连续 NN 的理论上限 —— 环会静默回卷，RMSSD 会算错但看着合理"
#endif

/* ---- PI ---- */
/* 交流窗 = 3 秒 @100 Hz。直流用那个 1 秒整数均值。 */
#define HR_PI_AC_WIN            (300)
/* 不满这么多不给 PI（照抄 `ac_rms` 的"不该把它当没搏动"）。 */
#define HR_PI_AC_MIN_N          (32)
/* PI 低到这个数就提示「请调整手指按压位置」。
 * 取值、推导和三条警告在 `ui/serial_hr.py` 的 `PI_LOW_PCT`（那里是唯一真相源，
 * 别在这儿重推）—— 一句摘要：取好按压下沿 0.092 与漂移档上沿 0.069 的几何
 * 中点，两侧等比例余量 1.15×。
 * ⚠️ 临床上的"PI<0.3% 灌注差"在这套硬件上**不适用**（好按压本来就在 0.1~0.3%）。
 * ⚠️ 板端**不用**这个常数出数（`H` 行不打提示文案，那活是 PC 侧的）。
 *    留着是为了 A/B 时能一眼看出"这一行的 PI 该不该触发提示"。 */
#define HR_PI_LOW_PCT           (0.08)

/* ---- `H,` 行的 1 Hz 节流 ----
 * **用样本钟而不是 mchtmr**，决定性的理由是**离线可复现**：PC 侧 `spec_bpm` 用
 * 墙钟节流，离线放 75 秒模拟只花几十毫秒，于是永远命中缓存、打出一串假值
 * （`_hr_fossil.py` 第一版就栽在这儿）。板端若用 mchtmr，离线把一段 15 秒录放
 * 一遍时 mchtmr 只走几毫秒，1 Hz 节流命中 0~1 次，**A/B 比对直接做不了**。
 * （样本钟在链路挂掉时也以 ~1 s/s 前进 —— `max30102_ts_sync` 把它锚在 mchtmr 上。） */
#define HR_EMIT_PERIOD_MS       (1000)
/* 空洞超过它就重基准，不追积压（否则一次长空洞之后会连打好几行）。 */
#define HR_EMIT_REBASE_MS       (3000)

/* ============================================================================
 * 状态
 * ============================================================================
 * 全部是 POD，没有指针、没有动态分配 —— 这样可以整体 `memset` 清零复位。
 */
typedef struct {
    /* ---- 直流滑窗（**整数**，见文件头第 2 条）---- */
    uint32_t dc_win[HR_FINGER_DC_WIN];
    uint64_t dc_sum;
    uint32_t dc_n;
    uint32_t dc_i;                /* 下一个要覆盖的位置（环形） */
    double   dc_mean;             /* 最近一次的 1 秒均值（手指闸与 PI 分母都用它） */

    /* ---- 手指闸 / settle ---- */
    bool     finger_on;
    uint32_t settle_left;         /* 刚按上之后的"静默样本"还差几个 */

    /* ---- 带通（三节双二阶）---- */
    double   x1[3], x2[3], y1[3], y2[3];

    /* ---- 包络与峰判据 ---- */
    double   env;
    bool     above;
    double   peak_y;
    uint32_t peak_ms;

    /* ---- 间隔 ---- */
    uint32_t ibis[HR_BEATS_KEPT]; /* 环形，最多 BEATS_KEPT 个 */
    uint32_t ibi_n;
    uint32_t ibi_head;
    uint32_t last_beat_ms;
    bool     have_last_beat;
    uint32_t last_ibi_ms;         /* 最近一次**被采纳**的间隔的终点时刻 */
    bool     have_last_ibi;
    uint32_t beats;               /* 累计登记搏动次数（诊断） */

    /* ---- 连续 NN 环（RMSSD 的输入）---- */
    uint16_t nn[HR_NN_MAX];       /* 整数毫秒；最长间隔 1600 装得下 */
    uint32_t nn_n;
    uint32_t nn_head;
    uint32_t nn_span_ms;          /* 这一段 NN 的滑动和 = Σ 各间隔 */
    bool     nn_seeded;           /* 环里是不是一段"从某拍起连续"的 NN */
    uint32_t nn_end_ms;           /* 这段最后一个 NN 的**终点** */

    /* ---- PI 的交流窗（带通之后、100 Hz）---- */
    double   pi_ac[HR_PI_AC_WIN];
    uint32_t pi_n;
    uint32_t pi_i;

    /* ---- `H,` 行的节流游标（样本钟）---- */
    uint32_t emit_t_ms;
    bool     emit_seeded;

    /* ---- 最近一次喂进来的样本时刻（时效判据用）---- */
    uint32_t last_sample_ms;

    /* ---- 统计（诊断用，不影响任何出数）---- */
    uint32_t rejected_ibi;        /* 被范围闸拒掉的间隔个数 */
    uint32_t nn_breaks;           /* 连续性断了多少次 */
} hr_algo_t;

/* ============================================================================
 * 对外
 * ============================================================================ */

/* 全清并复位到"刚上电"。**链路重建（`max30102_dma_attach`）不要调它** ——
 * 那段时间在样本钟上是一段如实的空洞，跟 `s_ts_next` 不清是同一个道理。 */
void hr_algo_reset(hr_algo_t *a);

/* 喂**一个样本**。⚠️ 必须是 ISR 推入环形缓冲的**每一个**样本，不能只在串口
 * 出队处调 —— 见 `max30102.h` 里算法环那一段：被跳过的样本会让双二阶看到
 * "有效采样率不对的不均匀流"，两个拐点整体漂掉，**输出不崩、只是安静地错**。
 *
 * `t_ms` 是板子给这个样本分配的时间戳（**和 `D,` 行那一列是同一个数**）。 */
void hr_algo_push(hr_algo_t *a, uint32_t t_ms, uint32_t ir);

/* 这一拍该不该打一行 `H`。**用样本钟节流**，理由见 `HR_EMIT_PERIOD_MS`。 */
bool hr_algo_emit_due(hr_algo_t *a, uint32_t t_ms);

/* 三个量。返回 false = 这一拍量不出来（调用方打 `--`，**绝不拿 0 顶替**）。
 *
 * `hr` 一位小数（对齐 PC 的 `round(bpm,1)`）；`rmssd_ms` 整数毫秒（`t_ms` 的分辨率
 * 就是 1 ms，再细是编数）；`pi_pct` 两位小数。 */
bool hr_algo_hr(const hr_algo_t *a, double *hr_bpm);
bool hr_algo_rmssd(const hr_algo_t *a, double *rmssd_ms);
bool hr_algo_pi(const hr_algo_t *a, double *pi_pct);

/* 裸量，给交叉校验和诊断用（界面上不出现）。 */
double hr_algo_ac_rms(const hr_algo_t *a);     /* 3 秒窗、带通后交流 RMS */
double hr_algo_ibi_spread(const hr_algo_t *a); /* MAD/中位，返回 -1 = 判不了 */
uint32_t hr_algo_nn_span_ms(const hr_algo_t *a);

#ifdef __cplusplus
}
#endif

#endif /* HR_ALGO_H */
