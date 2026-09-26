/*
 * 板端心率算法 —— `ui/serial_hr.py` 的 `_HrTracker` 的**逐行镜像**。
 * 口径、常数、运算顺序的来源与理由全在 `hr_algo.h` 的文件头；这里只写"为什么
 * 这一行非得这么写"。
 *
 * 🔴 **`ui/serial_hr.py` 是唯一真相源。** 改常数/改判据要改那边，再把值搬过来；
 *    这边自己调一个数，两边就会静默地对不上，而"对不上"本身看不出是哪边错了。
 *
 * 离线验证走 `_scratch/_hr_algo_host.c`：一个只 include 本文件和 `<std*.h>/<math.h>`
 * 的宿主驱动，用 MSVC（`_scratch/_cl.bat`）把它编成 x86 可执行文件**直接跑真 C**，
 * 再配 `_scratch/_hr_board_ab.py` 与 PC 侧逐样本对拍。
 *
 * ⚠️ 原来计划的是写一份 numpy 镜像代替它。**那个方案被否掉了**：镜像是第二份
 *    手写转写、它自己也会错，而"两份手写的东西互相对齐"证明不了任何一份是对的。
 *    编真 C 把这一整类错拿掉。
 */
#include "hr_algo.h"

#include <math.h>
#include <string.h>

/* ============================================================================
 * 带通系数 —— **硬编码，不许在运行时算**（理由见 hr_algo.h 第 1 条）
 * ============================================================================
 * 生成方式（在 PC 上跑一次，`ui/serial_hr.py` 的 `_make_bp()`）：
 *
 *     for s in _make_bp():
 *         for k in ('b0','b1','b2','a1','a2'):
 *             print(float.hex(getattr(s, k)))
 *
 * ⚠️ 是 **`float.hex()` 的精确字面量**（C99 十六进制浮点），不是十进制的
 *    `repr()` —— 后者看着一样、但一行 17 位有效数字抄错一位没人看得出来。
 */
typedef struct {
    double b0, b1, b2, a1, a2;
} hr_bq_t;

static const hr_bq_t HR_BQ[3] = {
    {   /* hp @0.65 Hz, Q = 0.54119610（4 阶巴特沃斯高通第 1 节）*/
        .b0 =  0x1.ed2ed7908e143p-1,
        .b1 = -0x1.ed2ed7908e143p+0,
        .b2 =  0x1.ed2ed7908e143p-1,
        .a1 = -0x1.ecfa2e2871d90p+0,
        .a2 =  0x1.dac701f1549f1p-1,
    },
    {   /* hp @0.65 Hz, Q = 1.30656296（4 阶巴特沃斯高通第 2 节）*/
        .b0 =  0x1.f7e9bc7834c73p-1,
        .b1 = -0x1.f7e9bc7834c73p+0,
        .b2 =  0x1.f7e9bc7834c73p-1,
        .a1 = -0x1.f7b3edc059fe4p+0,
        .a2 =  0x1.f03f16601f205p-1,
    },
    {   /* lp @3.5 Hz, Q = 0.7071（巴特沃斯低通，单节就是最平的）*/
        .b0 =  0x1.55d95069552d0p-7,
        .b1 =  0x1.55d95069552d0p-6,
        .b2 =  0x1.55d95069552d0p-7,
        .a1 = -0x1.b0e4ff1c7293dp+0,
        .a2 =  0x1.7727933f7a7a8p-1,
    },
};

/* 前向声明。`hr_reset_beats`（复位那一节）要调 `hr_nn_break_impl`，而后者在下面
 * NN 那一节 —— 挪上去会打乱"常数 → 工具 → 直流 → NN → 间隔 → 逐样本 → 出数"
 * 这个与 `ui/serial_hr.py` 对应的顺序，所以就地声明。 */
static void hr_nn_break_impl(hr_algo_t *a);

/* ============================================================================
 * 小工具
 * ============================================================================ */

/* 升序插入排序。只用在 ≤8 个和 ≤93 个的小数组上（中位数、MAD、NN 的差），
 * 犯不上为它拉一个 qsort 进来。 */
static void hr_sort_u32(uint32_t *v, uint32_t n)
{
    for (uint32_t i = 1; i < n; i++) {
        uint32_t t = v[i];
        uint32_t j = i;
        while (j > 0 && v[j - 1] > t) {
            v[j] = v[j - 1];
            j--;
        }
        v[j] = t;
    }
}

/* ============================================================================
 * 复位
 * ============================================================================ */

/* 把"攒搏动"这一步清空 —— 对应 PC 的 `_HrTracker._reset_beats`。
 * ⚠️ **滤波器状态一起清**（不清的话它自己的历史还往下淌，前几拍照样是脏的）；
 *    `beats` 计数器**故意不清**（它是"这个算法一共数了多少下"，清掉就看不出
 *    "手指上来之前噪声数了多少"）；`peak_y`/`peak_ms` 也**不清** —— PC 那边
 *    就没清，镜像就是镜像。 */
static void hr_reset_beats(hr_algo_t *a)
{
    a->ibi_n = 0;
    a->ibi_head = 0;
    a->have_last_beat = false;
    a->have_last_ibi = false;
    hr_nn_break_impl(a);
    a->pi_n = 0;
    a->pi_i = 0;
    for (int k = 0; k < 3; k++) {
        a->x1[k] = a->x2[k] = a->y1[k] = a->y2[k] = 0.0;
    }
    a->env = 0.0;
    a->above = false;
}

void hr_algo_reset(hr_algo_t *a)
{
    /* 全零就是"刚上电"：所有布尔量零值 = "没有"，所有 count = 0，所有累加和 = 0。
     * `dc_i`/`pi_i`/`ibi_head` 这些索引也是 0 = 从环的开头写起。 */
    memset(a, 0, sizeof(*a));
}

/* ============================================================================
 * 直流滑窗（**整数**，见 hr_algo.h 第 2 条）
 * ============================================================================
 * 返回最近 1 秒的均值。窗口没满时除以实际个数 —— 这一条和 PC 的
 * `self.dc_sum / len(self.dc_win)` 一致（那边也是除以 len，不是 maxlen）。
 */
static double hr_dc_push(hr_algo_t *a, uint32_t ir)
{
    if (a->dc_n == HR_FINGER_DC_WIN) {
        a->dc_sum -= a->dc_win[a->dc_i];
    } else {
        a->dc_n++;
    }
    a->dc_win[a->dc_i] = ir;
    a->dc_sum += ir;
    a->dc_i = (a->dc_i + 1u) % HR_FINGER_DC_WIN;
    return (double)a->dc_sum / (double)a->dc_n;
}

/* ============================================================================
 * NN 环（RMSSD 的输入）
 * ============================================================================
 * 连续性判据是**精确的整数比较**：这一段的起点 == 上一段的终点。见 hr_algo.h
 * 里 `HR_NN_NEED_MS` 上面那段 —— 不判的话相邻两项的差不是 NN 差，RMSSD 会
 * **算错却看着很合理**。
 */
static void hr_nn_break_impl(hr_algo_t *a)
{
    a->nn_n = 0;
    a->nn_head = 0;
    a->nn_span_ms = 0;
    a->nn_seeded = false;
    a->nn_end_ms = 0;
}

static void hr_nn_break(hr_algo_t *a)
{
    if (a->nn_seeded || a->nn_n) {
        a->nn_breaks++;
    }
    hr_nn_break_impl(a);
}

static void hr_nn_push(hr_algo_t *a, uint32_t ibi_ms, uint32_t end_ms)
{
    uint32_t start_ms = end_ms - ibi_ms;
    if (a->nn_seeded && start_ms != a->nn_end_ms) {
        /* 到不了这儿（被拒的间隔已经在调用方 break 过了），留着是**保险**：
         * 连续性一旦漏掉，RMSSD 会算错但看着很合理，是这套东西里最难发现的
         * 一类错。 */
        hr_nn_break(a);
    }
    if (!a->nn_seeded) {
        a->nn_n = 0;
        a->nn_head = 0;
        a->nn_span_ms = 0;
        a->nn_seeded = true;
    }
    /* 环满 = 理论上不该发生（HR_NN_MAX 那条 #if 卡住了）。真发生就丢最老的，
     * 那会让跨度掉到门槛以下 ⟹ RMSSD 变 `--`，是**安全**的降级，不是错数。 */
    if (a->nn_n == HR_NN_MAX) {
        a->nn_span_ms -= a->nn[a->nn_head];
        a->nn_head = (a->nn_head + 1u) % HR_NN_MAX;
        a->nn_n--;
    }
    a->nn[(a->nn_head + a->nn_n) % HR_NN_MAX] = (uint16_t)ibi_ms;
    a->nn_n++;
    a->nn_span_ms += ibi_ms;
    a->nn_end_ms = end_ms;
    /* 只留"刚好过门槛"的那一小段：跨度够了就从头丢，丢到不够为止。
     * **和 PC 是同一条规则**，否则交叉校验比的是两个不同的量。 */
    while (a->nn_n >= 2 &&
           (a->nn_span_ms - a->nn[a->nn_head]) >= HR_NN_NEED_MS) {
        a->nn_span_ms -= a->nn[a->nn_head];
        a->nn_head = (a->nn_head + 1u) % HR_NN_MAX;
        a->nn_n--;
    }
}

/* ============================================================================
 * 间隔与搏动登记
 * ============================================================================ */

/* ⚠️ 插入位置只有这一处：满了先丢最老的（`head` 前进、`n` 减一），再统一按
 *    `(head + n) % KEPT` 算写入点。**不要**给"没满"单开一个分支 —— 两个分支
 *    重复同一段索引运算，改一处忘一处就是静默错位。 */
static void hr_register_beat(hr_algo_t *a, uint32_t t_ms)
{
    a->beats++;
    if (a->have_last_beat) {
        /* ⚠️ `t_ms` 是**入队时**在 ISR 里按 `s_ts_next += 10` 分配的，理论上
         *    差值恒为 10 的倍数；但链路恢复/时间戳追赶之后可能出现大的跳变，
         *    所以用带符号减法（天然处理 32 位回绕）再判范围，别直接无符号相减。 */
        int32_t ibi_ms = (int32_t)t_ms - (int32_t)a->last_beat_ms;
        if (ibi_ms >= HR_MIN_IBI_MS && ibi_ms <= HR_MAX_IBI_MS) {
            if (a->ibi_n == HR_BEATS_KEPT) {
                a->ibi_head = (a->ibi_head + 1u) % HR_BEATS_KEPT;
                a->ibi_n--;
            }
            a->ibis[(a->ibi_head + a->ibi_n) % HR_BEATS_KEPT] = (uint16_t)ibi_ms;
            a->ibi_n++;
            a->last_ibi_ms = t_ms;
            a->have_last_ibi = true;
            hr_nn_push(a, (uint32_t)ibi_ms, t_ms);
        } else {
            /* 这一拍被判成"漏检或多检" ⟹ **连续性到此为止**。 */
            a->rejected_ibi++;
            hr_nn_break(a);
        }
    }
    a->last_beat_ms = t_ms;
    a->have_last_beat = true;
}

/* ============================================================================
 * 逐样本推进
 * ============================================================================ */

/* 这一份把 PC `push()` 里"带通 → PI 窗 → 包络 → 峰判据"那一段整个搬过来。
 * ⚠️ PC 那个 `push()` 在 `thr <= 0` 时**提前 return**，而手指/settle 逻辑在它
 *    **外面**（`SerialHr._feed`）—— 所以这里也必须把两件事拆开，见 `hr_algo_push`。 */
static void hr_step_filter(hr_algo_t *a, uint32_t t_ms, double x)
{
    double y = x;
    for (int k = 0; k < 3; k++) {
        const hr_bq_t *c = &HR_BQ[k];
        /* ⚠️ 括号必须与 `ui/serial_hr.py` 的左结合**逐字一致**，并且靠
         *    `-ffp-contract=off` 保证编译器不把 `a*b+c` 收成 FMA —— 否则
         *    在某些样本上差一点，而且是那种查不出来的差。 */
        double o = ((((c->b0 * y) + (c->b1 * a->x1[k])) + (c->b2 * a->x2[k]))
                    - (c->a1 * a->y1[k])) - (c->a2 * a->y2[k]);
        a->x2[k] = a->x1[k];
        a->x1[k] = y;
        a->y2[k] = a->y1[k];
        a->y1[k] = o;
        y = o;
    }

    /* PI 的交流窗：**不抽取、100 Hz 满速**，和 PC 的 `pi_ac` 一个口径。
     * ⚠️ 环写满就覆盖最老的那一格，所以**读的时候**要绕回去才是写入顺序 ——
     *    浮点求和与次序有关，见 `hr_algo_ac_rms`（那里是唯一读它的地方）。
     *    写这一侧不用维护 head。 */
    a->pi_ac[a->pi_i] = y;
    if (a->pi_n < HR_PI_AC_WIN) {
        a->pi_n++;
    }
    a->pi_i = (a->pi_i + 1u) % HR_PI_AC_WIN;

    /* 包络：只往上跟得快、往下衰减慢（标准的峰值保持） */
    double m = fabs(y);
    a->env = (m > a->env) ? m : a->env * HR_ENV_DECAY;

    double thr = HR_PEAK_FRAC * a->env;
    if (thr <= 0.0) {
        return;
    }

    if (y > thr) {
        if (!a->above) {
            a->above = true;
            a->peak_y = y;
            a->peak_ms = t_ms;
        } else if (y > a->peak_y) {
            a->peak_y = y;
            a->peak_ms = t_ms;
        }
    } else if (a->above) {
        /* **只在"从阈值上方跌回下方"那一刻登记**，登记的是**峰顶时刻** ——
         * 穿越时刻会晚几十毫秒，而 IBI 要的就是峰顶之间的时间。 */
        a->above = false;
        hr_register_beat(a, a->peak_ms);
    }
}

/* 手指闸 + off→on 之后的静默窗口。判据与 PC 的 `SerialHr._feed` **完全相同**。 */
static void hr_step_finger(hr_algo_t *a, double dc)
{
    bool on = (dc >= HR_FINGER_DC_MIN);
    bool was_on = a->finger_on;
    a->finger_on = on;

    if (!on) {
        a->settle_left = 0;
        return;
    }
    if (!was_on) {
        a->settle_left = HR_FINGER_DC_WIN;
    }
    if (a->settle_left > 0) {
        a->settle_left--;
        if (a->settle_left == 0) {
            hr_reset_beats(a);
        }
    }
}

void hr_algo_push(hr_algo_t *a, uint32_t t_ms, uint32_t ir)
{
    a->last_sample_ms = t_ms;
    double dc = hr_dc_push(a, ir);
    a->dc_mean = dc;
    hr_step_filter(a, t_ms, (double)ir - dc);
    hr_step_finger(a, dc);          /* 顺序是刻意的：PC 也是 push 完才判手指 */
}

/* ============================================================================
 * 出数
 * ============================================================================ */

static bool hr_ibi_fresh(const hr_algo_t *a)
{
    if (!a->have_last_ibi) {
        return false;
    }
    /* 两边都是**样本钟**。用带符号减法处理回绕；跨过回绕时差是个大负数，
     * 会被判成"不新鲜"，那是安全的降级。 */
    int32_t age = (int32_t)a->last_sample_ms - (int32_t)a->last_ibi_ms;
    return age <= HR_IBI_FRESH_MS;
}

static uint32_t hr_ibi_median_ms(const hr_algo_t *a)
{
    if (a->ibi_n == 0) {
        return 0;
    }
    uint32_t t[HR_BEATS_KEPT];
    uint32_t n = a->ibi_n;
    for (uint32_t i = 0; i < n; i++) {
        t[i] = a->ibis[(a->ibi_head + i) % HR_BEATS_KEPT];
    }
    hr_sort_u32(t, n);
    /* ⚠️ 取 `t[n/2]`，**不是** `t[(n-1)/2]` —— PC 那边是 `s[len(s)//2]`，
     *    两者在偶数长度下差一格，会把心率整体挪一点。 */
    return t[n / 2];
}

double hr_algo_ibi_spread(const hr_algo_t *a)
{
    uint32_t n = a->ibi_n;
    if (n < HR_MIN_BEATS) {
        return -1.0;                 /* -1 = 判不了（PC 那边返回 None） */
    }
    uint32_t v[HR_BEATS_KEPT];
    for (uint32_t i = 0; i < n; i++) {
        v[i] = a->ibis[(a->ibi_head + i) % HR_BEATS_KEPT];
    }
    hr_sort_u32(v, n);
    uint32_t med = v[n / 2];
    if (med == 0) {
        return -1.0;
    }
    /* ⚠️ MAD 用**原来的顺序**过一遍再排序 —— 顺序其实不影响结果（abs 之后再排），
     *    但照抄 PC 的形状，免得以后有人"顺手优化"掉一个看不见的东西。 */
    uint32_t d[HR_BEATS_KEPT];
    for (uint32_t i = 0; i < n; i++) {
        uint32_t x = a->ibis[(a->ibi_head + i) % HR_BEATS_KEPT];
        d[i] = (x > med) ? (x - med) : (med - x);
    }
    hr_sort_u32(d, n);
    return (double)d[n / 2] / (double)med;
}

double hr_algo_ac_rms(const hr_algo_t *a)
{
    uint32_t n = a->pi_n;
    if (n == 0) {
        return 0.0;
    }
    /* ⚠️ **必须按"写入顺序"遍历，不能按数组下标顺序。** 浮点加法不满足结合律，
     *    而 PC 那边是个 deque —— 它永远是写入顺序。这个环写满之后 `pi_ac[0]`
     *    是中间某一次写入，按下标遍历 = 换了一个求和次序 = 结果差最后几个 ulp。
     *    差得极小，但会让"逐位相同"这条判据失效 —— 而逐位相同正是这个文件
     *    存在的全部理由（见 hr_algo.h 文件头）。
     *    环满时 `pi_i` 就是最老的那一格 ⟹ 从它开始绕一圈正好是写入顺序；
     *    没满时 `pi_i == pi_n`、下标 0 就是最老的，直接从头走。 */
    uint32_t base = (n == HR_PI_AC_WIN) ? a->pi_i : 0u;
    double s = 0.0;
    for (uint32_t i = 0; i < n; i++) {
        s += a->pi_ac[(base + i) % HR_PI_AC_WIN];
    }
    double m = s / (double)n;
    double q = 0.0;
    for (uint32_t i = 0; i < n; i++) {
        double d = a->pi_ac[(base + i) % HR_PI_AC_WIN] - m;
        q += d * d;
    }
    return sqrt(q / (double)n);
}

uint32_t hr_algo_nn_span_ms(const hr_algo_t *a)
{
    return a->nn_span_ms;
}

bool hr_algo_hr(const hr_algo_t *a, double *hr_bpm)
{
    /* 这一条不是 PC `bpm()` 的一部分，而是 PC `snapshot()` 出口那几道闸的镜像
     * —— 目的是让 `H` 行的 `hr` **等于网页上那一格**，交叉校验才有的比。
     * ⚠️ 板端**没有频谱兜底**，所以 PC 能出数而板端 `--` 是正常的。 */
    if (!a->finger_on || a->settle_left > 0) {
        return false;
    }
    if (!hr_ibi_fresh(a)) {
        return false;
    }
    if (a->ibi_n < HR_MIN_BEATS) {
        return false;
    }
    double spr = hr_algo_ibi_spread(a);
    if (spr < 0.0 || spr > HR_MAX_IBI_SPREAD) {
        return false;
    }
    uint32_t med = hr_ibi_median_ms(a);
    if (med == 0) {
        return false;
    }
    /* ⚠️ PC 那边是 `60.0 / med_s`，而 `med_s` 是**两个 `t_ms/1000.0` 相减**
     *    （不是 `(t2−t1)/1000.0`），所以两边差 ~1e-16 的相对量。保留一位小数
     *    看不出来；真要逐位比，差异出在这儿。 */
    double bpm = 60.0 / ((double)med / 1000.0);
    if (hr_algo_ac_rms(a) < HR_AC_MIN_RMS) {
        return false;
    }
    *hr_bpm = bpm;
    return true;
}

bool hr_algo_rmssd(const hr_algo_t *a, double *rmssd_ms)
{
    if (!a->finger_on || a->settle_left > 0) {
        return false;
    }
    if (a->nn_span_ms < HR_NN_NEED_MS || a->nn_n < 2) {
        return false;
    }
    /* 整条路零浮点直到最后那个 sqrt：差的平方和是**精确整数**，所以只要 PC
     * 用同一串整数毫秒做同样的差，两边逐位相同。 */
    uint64_t s = 0;
    uint32_t prev = a->nn[a->nn_head];
    for (uint32_t i = 1; i < a->nn_n; i++) {
        uint32_t cur = a->nn[(a->nn_head + i) % HR_NN_MAX];
        int32_t d = (int32_t)cur - (int32_t)prev;
        s += (uint64_t)((int64_t)d * (int64_t)d);
        prev = cur;
    }
    *rmssd_ms = sqrt((double)s / (double)(a->nn_n - 1u));
    return true;
}

bool hr_algo_pi(const hr_algo_t *a, double *pi_pct)
{
    if (!a->finger_on || a->settle_left > 0) {
        return false;
    }
    if (a->pi_n < HR_PI_AC_MIN_N) {
        return false;               /* 判不了 ≠ 灌注是 0 */
    }
    double dc = a->dc_mean;
    if (dc <= 0.0) {
        return false;
    }
    double ac = hr_algo_ac_rms(a);
    *pi_pct = ac / dc * 100.0;
    return true;
}

bool hr_algo_emit_due(hr_algo_t *a, uint32_t t_ms)
{
    if (!a->emit_seeded) {
        a->emit_seeded = true;
        a->emit_t_ms = t_ms;
        return true;                /* 头一个样本就打一行：SES 里立刻看得见格式 */
    }
    int32_t d = (int32_t)t_ms - (int32_t)a->emit_t_ms;
    if (d < (int32_t)HR_EMIT_PERIOD_MS) {
        return false;
    }
    if (d > (int32_t)HR_EMIT_REBASE_MS) {
        a->emit_t_ms = t_ms;        /* 空洞太大：重基准，不追积压 */
    } else {
        a->emit_t_ms += HR_EMIT_PERIOD_MS;
    }
    return true;
}
