"""支路二的面部几何量：EAR / MAR / 头姿 → 统计量 → P(fatigue)。

**这是支路二从 `_scratch/live_face.py` 提炼出来的正式模块。**
提炼的理由不是"整洁"，是两件具体的事：

1. `src/fuse.py` 要同进程跑支路一和支路二，而它**不能 import `_scratch/` 下的东西**——
   `_scratch/live_face.py` 的最后一行是裸的 `main()`，import 就会直接开摄像头。
2. 离线（`tools/fit_branch2.py` 拟合模型）和在线（`src/fuse.py` 推理）
   **必须用同一套特征函数**。两边各写一份的话，特征定义稍有偏差，模型会静默降级——
   表现是"离线 65.7%，现场一坐上去全错"，而且查起来非常痛苦。

所以这里的规则是：**几何量、归一化、统计量全部住在这里，谁都不许另写一份。**

── 支路二到底在测什么 ──────────────────────────────────────────────
支路一（`src/live.py`）测的是**姿态周期性**：疲劳 = pitch 前倾-回弹。它看不见眼睛。
支路二补的就是这一块：眼睑闭合、嘴巴张开。两者分工写在 `probe_b2.py:9-10`：
「支路二只回答'眼睛和嘴累不累'，分心交给支路一」。

── 支路二的验证状态：已通过（2026-09-23）────────────────────────────
此前它一直卡在"那 71.4% 是来自眼睛还是来自头动"上，所以屏上横幅写着 `[NOT VALIDATED]`。
2026-09-23 凌晨的实时会话（`_scratch/_face_live_20260922_235417.csv`）把它验通了：

    r(EAR_norm, pitch)      = +0.02   （离线跨片段是 −0.56）
    r(PERCLOS, 头动范围)     = +0.03   （离线 95 段是 +0.61）
    头不动且在中位姿态的窗      110/302，PERCLOS 中位 0.386、最高 1.000
    空格标记 29.8 s：标记期 PERCLOS 0.694 vs 未标记 0.193（3.6×），同期头动仅 8.2°

── 一个必须记住的能力边界：疲劳时脸会丢 ──────────────────────────────
2026-09-23 按类别扫过人脸检出率（`_scratch/_face_detect_rate.py`）：

    normal  100.0%     glance  99.6%（2 段<3%，转头转出去了）
    phone    99.6%（6 段 0%，手把脸挡死）    fatigue  **80.3%（最低 39.9%）**

**疲劳片段中位只有 80.3%**——点头低头时检测器找不到脸。这意味着支路二在
"头低得很厉害"的时候是瞎的。但这不是致命的：那种时刻支路一正在报 L2/L3，
而且闸门（见 `src/fuse.py`）本来就会把支路二静音。支路二的真正价值区间是
**"头还立着、但眼睛已经在闭"**——那正是支路一还没有证据的时候。
"""
import collections
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import config as C


# ── 关键点（照抄 probe_ear.py 的对跖点配对，别重挑）──────────────────
# 眼睛用三对上下眼睑点，取均值再除以内外眼角距 —— 尺度无关，所以距离变化不影响。
EYE = {
    "l": dict(corner=(33, 133),
              pairs=((145, 159), (144, 160), (153, 158))),
    "r": dict(corner=(362, 263),
              pairs=((386, 374), (385, 373), (387, 380))),
}
MOUTH = dict(corner=(61, 291), inner=(13, 14), outer=(12, 15))
NEED = sorted({*EYE["l"]["corner"], *[p for pr in EYE["l"]["pairs"] for p in pr],
               *EYE["r"]["corner"], *[p for pr in EYE["r"]["pairs"] for p in pr],
               *MOUTH["corner"], *MOUTH["inner"], *MOUTH["outer"]})

# ── 参数 ────────────────────────────────────────────────────────────
ROLL_WIN = 10.0          # 归一化基线窗（秒）
NORM_Q = 75.0            # 基线取窗内 75 分位（不是中位！理由见 norm_by_time）
BLINK_THR = 0.80         # p75 基线下、把正常段闭眼占比标到 5% 得到的阈值
                         # （p50 时代是 0.84 —— 换归一化必须重标定，不能沿用）
YAWN_THR = 0.60          # MAR 高于它算张嘴。**标定记录（2026-09-23）**：
                         #   不捂嘴哈欠(yawn_open 5 段) 最长连续张嘴 3.20~4.40 s
                         #   说话(talking 5 段)         最长连续张嘴 0.00~0.87 s
                         #   → 在 0.60 上间隔 +2.33 s。判据本质是「说话是尖峰、哈欠是平台」：
                         #   talking 的 MAR p90 只有 0.36~0.49，而 yawn_open 的 p50 就有 0.64~0.73。
                         #   ⚠️ 捂嘴哈欠（_ear_raw.npz 的 yawn 组）在 0.60 上 0/5 触发，
                         #   最长只有 1.27 s —— 就是它让 `_ear.txt:178` 得出"MAR 分不开"的
                         #   错误结论（拿捂嘴当正例，见 probe_ear.py:311 的自述）。
                         #   驾驶场景下手在方向盘上，捂嘴不是目标场景，但仍是一条局限。
YAWN_MIN = 2.0           # 张嘴持续这么久才算哈欠（原 1.5）。
                         # 改 2.0 是为了两侧余量均衡：比 talking 最长 0.87 s 高 1.13 s，
                         # 比 yawn_open 最短 3.20 s 低 1.20 s。5/5 正例仍全部触发。
NOD_DROP, NOD_MIN = 12.0, 0.5    # |pitch − 本段中位| 超过 12° 且持续 0.5 s 算一次点头
WIN_SEC = 17.0           # 实时统计的滑动窗（秒）。**原来是 30.0，2026-09-23 改的。**
                         # 理由：离线 `clip_features` 的"窗口"就是**整段片段**，实测
                         # 96 段训练片段中位 17.1 s（范围 5.9~31.1），而在线取 30 s
                         # 比训练时长了 1.75 倍。PERCLOS 是窗内均值，窗越长方差越小，
                         # 过 `StandardScaler` 后幅度被系统性压小 —— LR 系数 +0.859 挂的
                         # 就是这个被压小的量，等于把模型钝化。取中位数是"最不坏的单点"：
                         # 离线那边根本没有一个固定的窗长（每段各是各的），只能对齐中位。
                         # ⚠️ 这个改动动了 `_scratch/live_face.py` 验证时用的窗长，
                         # 所以那批绝对值（PERCLOS 0.386 等）会平移。定性结论
                         # （PERCLOS 涨而 dPITCH 不动）与窗长无关，但数字要重跑一遍。
HIST_SEC = ROLL_WIN + WIN_SEC    # 实时缓冲该留多长（秒）—— 见 window_features。
                                 # 恰好 = 基线窗 + 统计窗：窗口里**每一个**采样点
                                 # 往前看 ROLL_WIN 秒都还在缓冲内，基线历史不截断，
                                 # 这才是和离线对齐的充要条件，不是随便取的余量。

# 逻辑回归实际用的特征列。**哈欠不在里面**：训练集只有
# normal/glance/phone/fatigue 四组，yawn/talking/yawn_open 从不进 LR，
# 所以 YAWN/min 这一列在 96 段训练片段上恒等于 0，系数也就是 0.000
# （tools/ablate_feats.py 实测：4 特征与 3 特征的平衡准确率完全同为 65.7%，
#  错判的是同一批 21 段）。哈欠改由 src/fuse.py 里的独立规则处理。
FEATURE_NAMES = ("perclos", "brate", "nod")


def _d(P, a, b):
    return float(np.linalg.norm(P[a] - P[b]))


def points(lm, w, h):
    """mediapipe 归一化关键点 -> 像素坐标字典（只取 NEED 里用得到的）。"""
    return {j: np.array([lm[j].x * w, lm[j].y * h]) for j in NEED}


def ear_of(P):
    """EAR = 上下眼睑距离均值 / 内外眼角距离，双眼取平均。尺度无关。"""
    out = []
    for e in ("l", "r"):
        c1, c2 = EYE[e]["corner"]
        w = _d(P, c1, c2)
        if w < 1e-6:
            continue
        v = float(np.mean([_d(P, a, b) for a, b in EYE[e]["pairs"]]))
        out.append(v / w)
    return float(np.mean(out)) if out else np.nan


def mar_of(P):
    """MAR = (内唇距 + 外唇距)/2 / 嘴角距。"""
    c1, c2 = MOUTH["corner"]
    w = _d(P, c1, c2)
    if w < 1e-6:
        return np.nan
    return float(np.mean([_d(P, *MOUTH["inner"]), _d(P, *MOUTH["outer"])])) / w


def euler_of(M):
    """4x4 面部变换矩阵 → (pitch, yaw, roll) 度。不用 solvePnP。

    ⚠️ pitch 是第一行那个式子。`arctan2(-R[2,0], sy)` 是 **yaw** ——
    2026-09-23 写 `_scratch/_face_detect_rate.py` 时抄错过一次，
    量出来的"pitch"其实是左右转头。改这里之前先确认下标。
    """
    R = np.asarray(M, dtype=float)[:3, :3]
    sy = float(np.hypot(R[0, 0], R[1, 0]))
    return np.degrees([np.arctan2(R[2, 1], R[2, 2]),      # pitch
                       np.arctan2(-R[2, 0], sy),          # yaw
                       np.arctan2(R[1, 0], R[0, 0])])     # roll


# ── 时序工具（按时间戳，不按帧数）────────────────────────────────────
def norm_by_time(ts, vals, win, q=NORM_Q):
    """逐点用「它自己往前 win 秒」的 **q 分位** 做基线。按时间选窗，不按帧数。

    ── 为什么是分位数，且为什么是 75 而不是 50 ──────────────────────────
    基线要落在"睁眼"区间，所以分位数必须**高于闭眼占比**：
        p50 只撑到 50% 闭眼，p75 撑到 75%
    实测（2026-09-22 那场标了 11 次闭眼的会话，闭眼占了近一半时间）：
        p50 只检出 4/11 —— 基线被闭眼自己拽塌了，闭得越多越读不出来
        p75 检出 10/11，且离线 95 段的 phone 假闭眼几乎没变差
    这条对疲劳检测是要命的：真实疲劳就是高频闭眼，p50 是**自我抑制**的。

    也不用峰值跟踪（睁眼快跟上、闭眼慢下滑）：它对向上的噪声尖峰过敏，
    转头时 landmark 抖出的尖峰会把基线抬上去，离线 glance 段的假闭眼
    从 0.67 s 恶化到 1.6 s。分位数对双边的离群都钝，更稳。

    按时间选窗的原因：摄像头实际帧率随曝光漂移（这台实测 ~6~11 fps，名义 15）。
    按帧数算出来的「10 秒基线」实际是 15 秒，「30 秒窗」实际是 45 秒，
    眨眼频率还会被系统性低估 1.5 倍 —— 而且帧率每次录像都不一样，
    测一个固定值去补也没用。唯一稳的就是拿时间戳选。

    ⚠️ 因果性：基线的历史长度直接影响结果。离线是在**整段片段**上算的，
    实时若只喂 30 秒缓冲，窗口前 10 秒的基线就被截断了（历史不足）。
    实测同一段会话，"窗内基线"与"全历史基线"的单窗 PERCLOS 最大差 0.343。
    所以实时缓冲要留 HIST_SEC = WIN_SEC + ROLL_WIN = 27 秒：
    前 10 秒给基线热身，最后 WIN_SEC = 17 秒才拿去算统计。
    ⚠️ 这个 27 是**充要条件**不是余量 —— 统计窗里每个样本都要有自己的
    完整 10 秒基线史。（2026-09-23 把 WIN_SEC 从 30 改成 17，40 是旧值。）
    """
    ts, vals = np.asarray(ts, float), np.asarray(vals, float)
    out = np.empty(len(vals))
    j = 0
    for i in range(len(vals)):
        lo = ts[i] - win
        while ts[j] < lo:
            j += 1
        w = vals[j:i + 1]
        w = w[np.isfinite(w)]
        out[i] = np.percentile(w, q) if len(w) else np.nan
    return out


def runs_sec(ts, x, mask_fn):
    """满足 mask_fn 的连续段的**真实时长（秒）**。帧率会漂，除以 15 是错的。"""
    tsa = np.asarray(ts, float)
    out, cur, t0_ = [], False, 0.0
    for i, v in enumerate(x):
        if np.isfinite(v) and mask_fn(v):
            if not cur:
                cur, t0_ = True, tsa[i]
        elif cur:
            cur = False
            out.append(float(tsa[i] - t0_))
    if cur:
        out.append(float(tsa[-1] - t0_))
    return out


def yawn_seconds(ts, mar):
    """这段里最长的一次"张嘴"持续了多少秒（0 表示没有）。

    ★ 哈欠的判别量是**持续**，不是峰值 —— 这是整条哈欠路线的关键，
      也是 2026-09-23 才搞清楚的：说话会出现比哈欠更高的 MAR 尖峰
      （talking max 0.777 vs yawn_open p90 最低 0.727，单帧上完全重叠），
      但说话**张不久**（最长 0.87 s），哈欠张得久（最短 3.20 s）。

    ⚠️ **返回值在阈值附近是不稳定的，别当测量值用。** 判据是"MAR 连续
      高于 YAWN_THR 多久"，所以一段 MAR 恰好贴着 0.60 徘徊的片段，会在
      两次检测器运行之间给出差别很大的数 —— 不是差几个百分点，是**整段
      连续区间分裂与否**。实测 yawn_open_03：242 帧里有 **20 帧**落在
      0.60±0.02（10.93 s 那帧 0.5890，差 0.011），离线报 3.20 s、在线报
      5.53 s，而两趟的 MAR 在同一时间戳上只差到第三位小数。
      同批片段里 yawn_open_00/01 各只有 4/227、4/186 帧贴阈值，
      talking_00 是 **0/198**（MAR 最高 0.537）—— 也就是说**说话侧有真实
      余量，哈欠侧这一段没有**。
      结论：**判决稳（3.20 和 5.53 都 ≥ YAWN_MIN=2.0），数字不稳。**
      所以 —— 别把 yawn_sec 写进报告当"哈欠持续了 X 秒"，只写触发与否；
      要一个稳的量就改用滚动均值峰值（标定时它给的是 0.747 vs 0.551）。
    """
    return max(runs_sec(ts, mar, lambda v: v > YAWN_THR) or [0.0])


# ── 特征：离线与在线唯一的那份定义 ───────────────────────────────────
def _features(ts, ear, mar, pitch, en=None):
    """四个统计量。离线片段与实时窗口**都调这个**，不许另写。

    除数一律用**真实时长**。曾经的实时路径里 brate 除以真实窗长、
    而 yawns/nods 除以常量 WIN_SEC/60 —— 同一个窗里两种口径，
    今天看不出问题（哈欠列恒 0），但那是留了一个静默降级的雷。

    `en` 参数是给实时路径用的：`window_features` 已经在**全缓冲**上算好了
    归一化 EAR，必须传进来复用。不传的话这里会拿**当前这段 ts/ear** 重算一遍
    基线 —— 于是同一个窗里 `perclos` 走全缓冲、`brate` 走切片内，两个口径。
    这正是本模块要消灭的那类静默降级，所以留了个口子而不是让它自己重算。
    """
    ts = np.asarray(ts, float)
    dur = float(ts[-1] - ts[0])
    if dur < 5:
        return None
    if en is None:
        en = ear / np.maximum(norm_by_time(ts, ear, ROLL_WIN), 1e-6)
    pitch = np.asarray(pitch, float)
    mid = float(np.median(pitch[np.isfinite(pitch)])) if np.isfinite(pitch).any() else np.nan
    blinks = len(runs_sec(ts, en, lambda v: v < BLINK_THR))
    nods = len([d for d in runs_sec(ts, pitch, lambda v: abs(v - mid) > NOD_DROP)
                if d >= NOD_MIN])
    yawns = len([d for d in runs_sec(ts, mar, lambda v: v > YAWN_THR)
                 if d >= YAWN_MIN])
    return dict(perclos=float(np.mean(en < BLINK_THR)),
                brate=blinks / dur * 60.0,
                nod=nods / dur * 60.0,
                yawn=yawns / dur * 60.0,          # 哈欠**不入模型**（见 FEATURE_NAMES），
                                                  # 只为 tools/ablate_feats.py 的消融保留
                yawn_sec=yawn_seconds(ts, mar),
                dur=dur)


def clip_features(npz, key, need=FEATURE_NAMES):
    """从 `_ear_raw.npz` 里取一段片段的特征向量（离线：拟模型 / 消融用）。

    ⚠️ 返回 None 的两种原因要分清，别混成一句"样本不够"：
      · 字段缺失或长度不齐 —— 是**数据**问题（当前 106 段里有 10 段是这种）
      · 有效时长短于 5 秒 —— 是**片段**问题
    调用方（tools/fit_branch2.py）会把两者分别打出来，否则
    "用了 96 段"这个数字看起来像是随手丢的。
    """
    def g(f):
        k = f"{key}|{f}"
        return npz[k] if k in npz.files else None

    e, eu, ts, mar = g("ear"), g("euler"), g("t"), g("mar")
    if e is None or eu is None or ts is None or mar is None:
        return None, "缺字段"
    if not (len(eu) == len(e) == len(ts) == len(mar)):
        n = {len(e), len(eu), len(ts), len(mar)}
        return None, f"长度不齐 {sorted(n)}"
    m = np.isfinite(e) & np.isfinite(eu[:, 0])
    if not m.any():
        return None, "没有有效帧"
    f = _features(np.asarray(ts, float)[m], np.asarray(e, float)[m],
                  np.asarray(mar, float)[m], eu[m, 0])
    if f is None:
        return None, "有效时长 < 5 s"
    return [f[k] for k in need], None


def window_features(ts, ear, mar, pitch, win_sec=WIN_SEC):
    """实时路径的唯一入口：一段（HIST_SEC 长的）缓冲 → 统计量 + 诊断量。

    ★ 基线在**全缓冲**上算，统计只在**最后 win_sec 秒**做。
      这是 2026-09-23 修正的一处离在线口径差：早先直接把切片喂给
      `norm_by_time`，于是切片里前 10 秒的基线历史不足 —— 和离线
      "整段片段上算基线"不是同一个东西。缓冲留 HIST_SEC = WIN_SEC + ROLL_WIN
      秒就对齐了（现在是 27.0 = 17.0 + 10.0；这个和不是安全余量，是
      **充要条件**：窗口里每一个样本都要有自己的完整 10 秒基线历史）。

    返回 None = 还没热身（缓冲跨度不足 ROLL_WIN 秒）。
    调用方此时**必须**把支路二的票作废，不能拿 NaN 去喂模型。
    """
    ts = np.asarray(ts, float)
    if len(ts) < 3 or (ts[-1] - ts[0]) < ROLL_WIN:
        return None
    ear, mar = np.asarray(ear, float), np.asarray(mar, float)
    pitch = np.asarray(pitch, float)
    en = ear / np.maximum(norm_by_time(ts, ear, ROLL_WIN), 1e-6)
    s = ts >= ts[-1] - win_sec
    if s.sum() < 3:
        return None
    # ★ en[s] 必须传进去复用：不传的话 _features 会拿**这个切片**重算一遍基线，
    #   于是 perclos 走全缓冲、brate 走切片内 —— 同一个窗两个口径。
    st = _features(ts[s], ear[s], mar[s], pitch[s], en=en[s])
    if st is None:
        return None
    ps = pitch[s]
    d_pitch = (float(np.nanpercentile(ps, 95) - np.nanpercentile(ps, 5))
               if np.isfinite(ps).sum() > 10 else float("nan"))
    st.update(en_now=float(en[-1]), d_pitch=d_pitch, n_win=int(s.sum()),
              n_frames=int(s.sum()))
    return st



def feature_vector(stats, need=FEATURE_NAMES):
    """统计量 dict → 模型要的定长向量。顺序必须与 FEATURE_NAMES 一致。"""
    return [float(stats[k]) for k in need]


# ── 实时缓冲 ────────────────────────────────────────────────────────
class FaceBranch:
    """支路二的实时状态：(t, ear, mar, pitch) 缓冲 → 统计量。

    与 `_scratch/live_face.py:578-671` 的主循环同源。抽成类而不是继续散在主循环里，
    是因为那 741 行里最容易出错的**不是几何量，是缓冲与统计的时序** ——
    而时序错误不会崩，只会让数字慢慢偏，散在循环里没法单独测。

    ★ 四路必须装在**同一个 deque** 里。
      `live_face.py:622` 已经写过这条：分成三个 deque，某帧检不到脸就会错位，
      而闭眼的时候正好最容易丢帧 —— 错位了还看不出来，因为数值都还在合理范围内。
      也不按**帧数**裁剪：这台摄像头实测 6~11 fps 漂，按帧数裁出来的"40 秒缓冲"
      实际是 60~100 秒。只有按时间裁才保证缓冲真的是 hist_sec 秒。

    ★ 就绪分两级，不是一个布尔量。
        `ready()`  span >= ROLL_WIN   基线有历史了，够在屏上画 EAR_norm
        `full()`   span >= HIST_SEC   **窗口整个落在缓冲内**，这才敢喂模型
      差这一级的理由见 `window_features` 的 docstring：基线是全缓冲的 p75，
      而离线是在整段片段上算的。缓冲不满时窗口前段的基线历史被截断，
      和训练口径就不是同一个东西了 —— 正是模块开头说的那种"静默降级"。
      喂早了的代价不是报错，是概率整体偏低然后你以为模型不行。

    ★ 闸门关闭时调用方应该 `clear()`，不要让它自己判断。
      因为"闸门"是支路一的概念（见 `src/fuse.py`），这里不该知道它。
    """

    def __init__(self, hist_sec=HIST_SEC):
        self.hist_sec = float(hist_sec)
        self.buf = collections.deque()
        self.n = 0                      # 收到的帧数（含没检到脸的）

    def push(self, t, ear, mar, pitch):
        """塞一帧。**没检到脸时也要塞 NaN**，不要跳过。

        跳过的话 `perclos` 的分母就只剩"检到脸的帧"，等于把"看不见"从统计里
        抹掉了；塞 NaN 则 `norm_by_time` / `runs_sec` 会 mask 掉它，
        而 `en < BLINK_THR` 对 NaN 为 False —— 记成"没闭眼"，偏保守。
        `live_face.py:624` 就是这么做的，保持一致。
        """
        self.buf.append((float(t), float(ear), float(mar), float(pitch)))
        self.n += 1
        cut = float(t) - self.hist_sec
        # 至少留两点，否则 span 恒为 0、ready() 永假
        while len(self.buf) > 2 and self.buf[1][0] < cut:
            self.buf.popleft()

    def clear(self):
        """闸门关闭时调用。不清的话闸门一重开，缓冲里还是关闭期间那些
        被头姿污染的 EAR —— 30 秒的 PERCLOS 窗带着污染帧，重开瞬间就误报。"""
        self.buf.clear()

    @property
    def span(self):
        return 0.0 if len(self.buf) < 2 else self.buf[-1][0] - self.buf[0][0]

    def ready(self):
        return self.span >= ROLL_WIN

    def full(self):
        return self.span >= self.hist_sec

    def warm_left(self):
        """还差多少秒才 full()。屏上照这个显示倒计时。"""
        return max(0.0, self.hist_sec - self.span)

    def arrays(self):
        B = np.array(self.buf, float)
        return B[:, 0], B[:, 1], B[:, 2], B[:, 3]

    def snapshot(self):
        """统计量 + 诊断量，缓冲不够就 None。**绝不要拿 NaN 去喂模型。**"""
        if len(self.buf) < 3:
            return None
        t, e, m, p = self.arrays()
        return window_features(t, e, m, p)


# ── 提取器 ──────────────────────────────────────────────────────────
class FaceExtractor:
    """一帧 BGR → 面部几何量字典，没检测到脸返回 None。

    与 `src/pose.py` 的 `PoseExtractor` 是同一套封装风格，有三个点必须一致：

    1. **时间戳单调守卫（必须）**。mediapipe 的图拒绝倒退的时间戳，报的是
       `ValueError: Input timestamp must be monotonically increasing`。
       `PoseExtractor` 早就有这个守卫，而支路二在 `_scratch/live_face.py` 里
       每个进程只跑一轮，所以一直没暴露——2026-09-23 写 `_face_detect_rate.py`
       连续扫多段时才撞上（第二段从 0 重新计时）。
       回放路径尤其要注意：`src/fuse.py` 连放两段视频，两段都从 media_time=0 开始。

    2. **没检测到脸时返回 None，不要沿用上一帧**。调用方会塞 NaN 进缓冲，
       而 `norm_by_time` / `runs_sec` 自己会 mask 掉非有限值 —— 这与
       `PoseExtractor` 对低置信点"沿用上一帧"的做法**故意不同**：
       那里沿用的是单个关键点的坐标，这里是整帧的几何量，沿用会凭空造出
       一段"眼睛一直睁着"的假数据。

    3. **`close()` 正常不要调用**。理由与 `PoseExtractor.close()` 完全相同，
       见那边的注释：mediapipe 1.0.1 的析构固定 42 秒，每个实例一次。
       现在融合程序有两个 landmarker 实例，所以这条比以前更要命。
    """

    def __init__(self, model_path=None, running_mode="VIDEO", num_faces=1):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        path = Path(model_path) if model_path else (C.MODELS_DIR / "face_landmarker.task")
        if not path.exists():
            raise FileNotFoundError(
                f"找不到模型文件 {path}\n"
                f"从 https://storage.googleapis.com/mediapipe-models/face_landmarker/"
                f"face_landmarker/float16/latest/face_landmarker.task 下载后放进 models/")
        self._landmarker = vision.FaceLandmarker.create_from_options(
            vision.FaceLandmarkerOptions(
                base_options=mp_python.BaseOptions(model_asset_path=str(path)),
                running_mode=(vision.RunningMode.VIDEO if running_mode == "VIDEO"
                              else vision.RunningMode.IMAGE),
                num_faces=num_faces,
                output_face_blendshapes=False,          # 用不到，省时间
                output_facial_transformation_matrixes=True,
            ))
        self.running_mode = running_mode
        # 全进程单调递增，跨视频也不能重置（同 PoseExtractor._last_ts）
        self._last_ts = -1

    def detect(self, bgr, timestamp_ms, w=None, h=None):
        """一帧 BGR + 时间戳(ms) → dict 或 None。

        返回 ear / mar / pitch / yaw / roll / P（像素坐标，给 HUD 画点用）。
        """
        import cv2
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        img = self._mp.Image(image_format=self._mp.ImageFormat.SRGB,
                             data=np.ascontiguousarray(rgb))
        ts = int(timestamp_ms)
        if ts <= self._last_ts:
            ts = self._last_ts + 1
        self._last_ts = ts

        if self.running_mode == "VIDEO":
            res = self._landmarker.detect_for_video(img, ts)
        else:
            res = self._landmarker.detect(img)

        if not res.face_landmarks:
            return None
        if w is None or h is None:
            h, w = bgr.shape[:2]
        P = points(res.face_landmarks[0], w, h)
        out = dict(ear=ear_of(P), mar=mar_of(P), P=P)
        if res.facial_transformation_matrixes:
            pitch, yaw, roll = euler_of(res.facial_transformation_matrixes[0])
            out.update(pitch=float(pitch), yaw=float(yaw), roll=float(roll))
        else:
            out.update(pitch=np.nan, yaw=np.nan, roll=np.nan)
        return out

    def close(self):
        """显式释放。**正常不要调用** —— 固定 42 秒，见 PoseExtractor.close()。"""
        try:
            self._landmarker.close()
        except Exception:
            pass
        self._landmarker = None
