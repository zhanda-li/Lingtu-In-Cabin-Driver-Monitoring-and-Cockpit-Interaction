"""L4：支路二**真人会话**判决 —— 读 `fuse.csv`，判「响应来自眼睛还是来自头动」。

── 为什么非要真人，且非要单独一个脚本 ──────────────────────────────
`runs/fuse_replay_full.txt` 自己把话写死了：

    支路二在这些片段上一次都没出数 —— 片段比 HIST_SEC=27 s 短，缓冲永远不满。
    所以下面的检查 2/3 是**结构性通过**，不是验证。

即：闸门开合、级别轨迹、哈欠规则都验到了，**唯独支路二本身一次没跑过**。
它要 `fb.full()`（缓冲跨度 ≥ 27 s）才第一次开口（`src/fuse.py:577`），
而闸门一关就 `fb.clear()`（`:591`）—— 中途扭一次头，27 秒热身全部清零。
所以只能是真人坐住、不间断跑够 27 秒以上。

── 为什么不直接复用 `_scratch/live_face.py:177 analyze()` ──────────
那份判决是验通支路二的原班工具，四节结构照搬没问题，但**不能直接用**：

1. 它读自己那套列（`t/ear/mar/pitch/en/prob/mark`），与 `fuse.csv` 不同名。
2. 它末尾是**裸 `main()`**（不是 `if __name__`），`import` 就会开摄像头。
   所以这里是把骨架**抄过来**，不是 import。
3. 它没有 `fuse.csv` 独有、而恰恰是这个问题**最强信号**的几列：
   `gate` / `p_fat` / `l2` / `ema_normal`。只有 `gate==1` 且 `p_fat` 有限
   的那些拍，支路二才**真的开过口** —— 判据点就该落在这里，
   而不是落在「整段所有帧」上。

── 判法（四节，各节都写明「什么情况下这一节不算数」）────────────────
【0】结构性：支路二到底跑起来没有（这一节不过，后面三节全部作废）
【1】自我否证：闸门开的帧里 r(EAR_norm, pitch)
【2】归因：p_fat 跟眼睛走还是跟头走；再按「头不动 **且** 在中位姿态」分层
【3】标记期：操作者亲口标记的「我在闭眼」那几段 —— 最硬的一条

用法：
    python tools/analyze_fuse_l4.py fuse.csv
    python tools/analyze_fuse_l4.py fuse.csv --png runs/fuse_l4.png
    python tools/analyze_fuse_l4.py fuse.csv --win-thr frames   # 旧滤网口径对照
"""
import argparse
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from face import BLINK_THR, ROLL_WIN, norm_by_time, runs_sec   # noqa: E402
from replay_fuse import read_log                              # noqa: E402

# 本脚本**必须**的列。缺任何一列都说明这份 CSV 是旧版 fuse.py 写的 ——
# 那时既没有绝对 pitch 也没有标记，判决的【1】【2】【3】都做不出来。
# 与其拿 d_pitch 凑一个看起来像结论的东西，不如直接报错、让人回去重跑。
NEED = ("t", "pitch", "ear", "mar", "mark", "gate", "p_fat", "l2", "l1",
        "l_fused", "en_now", "perclos")


def _r(x, y):
    """相关。两列都要求非空且方差非零，否则给 NaN 而不是崩掉。

    会话里常有「某个量整段是常数」的情况（闸门从没开过 → p_fat 全空、
    头纹丝不动 → pitch 方差≈0），这时 corrcoef 会给 nan 并打 RuntimeWarning。
    判决表上要的是一眼看懂的 `-`，不是一屏警告。
    """
    m = np.isfinite(x) & np.isfinite(y)
    if m.sum() < 8:
        return np.nan, int(m.sum())
    a, b = x[m], y[m]
    if a.std() < 1e-12 or b.std() < 1e-12:
        return np.nan, int(m.sum())
    return float(np.corrcoef(a, b)[0, 1]), int(m.sum())


def n_true_runs(mask):
    """布尔序列里 True 的连续段数。"""
    m = np.asarray(mask, bool)
    if m.size == 0:
        return 0
    return int(np.sum(m[1:] & ~m[:-1]) + (1 if m[0] else 0))


def longest_true_run(mask, t):
    """最长连续 True 段的**真实秒数** → (秒, 起, 止)。

    这一条是【0】的核心：闸门必须**连续**开着攒满 HIST_SEC 秒，支路二才会
    第一次开口。所以「最长连续闸门开多久」直接回答「热身有没有可能完成」。
    按 t 的差值算，不按帧数乘常数 —— 帧率会漂，这是本项目反复踩的坑。
    """
    m = np.asarray(mask, bool)
    t = np.asarray(t, float)
    best = (0.0, np.nan, np.nan)
    i, n = 0, len(m)
    while i < n:
        if not m[i]:
            i += 1
            continue
        j = i
        while j + 1 < n and m[j + 1]:
            j += 1
        d = float(t[j] - t[i])
        if d > best[0]:
            best = (d, float(t[i]), float(t[j]))
        i = j + 1
    return best


def main():
    ap = argparse.ArgumentParser(
        description="支路二真人 L4 会话判决（读 fuse.csv）")
    ap.add_argument("csv", help="live_fuse.bat 写出来的 fuse.csv")
    ap.add_argument("--png", default=None, help="判决图输出路径（不给就不画）")
    ap.add_argument("--win-thr", choices=("span", "frames", "none"),
                    default="span",
                    help="滑窗滤网口径：span=按采样跨度（默认，与 live_face 一致）"
                         " frames=旧口径（按名义 15 fps 的帧数） none=不筛")
    ap.add_argument("--still", type=float, default=6.0,
                    help="「头不动」判据：窗内 pitch 极差上限（度）")
    ap.add_argument("--neut", type=float, default=5.0,
                    help="「在中位姿态」判据：窗中位 pitch 与基准之差上限（度）")
    args = ap.parse_args()

    from face import HIST_SEC

    c = read_log(args.csv)
    if not c or "t" not in c:
        print(f"读不出日志（或它是空的）：{args.csv}")
        return 2
    missing = [k for k in NEED if k not in c]
    if missing:
        print(f"❌ 这份 CSV 缺列：{', '.join(missing)}")
        print("   多半是拿**旧版** src/fuse.py 跑出来的 —— 那时日志里没有")
        print("   绝对 pitch，也没有空格标记，本判决的【1】【2】【3】都做不出来。")
        print("   （不能用 d_pitch 顶替：它是窗内 p95−p5 **极差**，回推不出绝对值。）")
        print("   请用当前 src/fuse.py 重跑一次会话。")
        return 2

    t_all = c["t"]
    g = np.isfinite(t_all)
    t = t_all[g]
    col = {k: c[k][g] for k in c}
    if len(t) < 30:
        print(f"日志只有 {len(t)} 拍，太短。")
        return 2
    dur = float(t[-1] - t[0])

    pitch, ear, mar = col["pitch"], col["ear"], col["mar"]
    mark = np.nan_to_num(col["mark"], nan=0.0) > 0
    gate = col["gate"] > 0.5
    p_fat, en_now = col["p_fat"], col["en_now"]
    perclos = col["perclos"]

    # ── 两个 EAR_norm 口径，必须分清（`live_face.py:562-564` 记过这个坑）──
    #   en_now  = 发布路径当场算出来的那个量，正是它喂进 PERCLOS→逻辑回归。
    #             只在闸门开且缓冲 ready 时非空（其余拍是 `-`）。
    #   en_rec  = 拿原始 ear 按当前参数**重算**的，覆盖面全（凡检到脸就有）。
    #             与 live_face 那批数字（闭眼 0.19 / 睁眼 0.38）同口径。
    # 判决主体用 en_now（这才是要演示的东西）；【3】的对照用 en_rec，因为标记期
    # 几乎必然横跨闸门开关，用 en_now 会让标记/未标记落在**不同的采样集合**上。
    en_rec = ear / np.maximum(norm_by_time(t, ear, ROLL_WIN), 1e-6)
    r_x, n_x = _r(en_now, en_rec)

    # ── 基线有效性掩码：护栏（2026-09-23 加，同日从「整场取最大」改成逐窗）──
    #   防的是**测量本身**失效，不是支路二失效。
    #   norm_by_time 的基线是 ROLL_WIN=10 秒窗的 **p75**，只在「窗内闭眼占比
    #   c < ~0.75」时才落得回睁眼区间（`face.py:154` 那条设计假设）。超了基线
    #   就塌到闭眼值上：闭着眼读成 en≈0.93（"睁着"），**睁开之后**更荒唐，
    #   en 冲到 1.8~2.1。实测：
    #     runs/session1.csv（闭 12~15 s）c=1.00 → 基线 0.372→0.184
    #         → 闭眼 en_now 0.931、睁眼 2.068 —— 整场报废；
    #     runs/session2.csv（闭 5 s，但第 4 次闭了 7.5 s）尾窗 c=0.78
    #         → 基线 0.37→0.20 → **只有** t=90.8~93.6 那几秒不可用。
    #   ⚠️ 所以护栏不能整场取最大：一次超时的闭眼会把没坏的几十秒一起判死。
    #      基线的有效性是**每个时刻各自的窗**的性质，逐窗才对应得上机制。
    #   c 按**真实秒数**在尾窗里算，与 norm_by_time 的选窗方式一致。
    #   ⚠️ 这条掩码只作用于 **EAR 派生的量**（en_rec/en_now/perclos/p_fat），
    #      pitch/MAR/gate 与基线无关，不掩 —— 掩了是张冠李戴。
    C_SAFE = 0.70
    c_t = np.full(len(t), np.nan)
    for _i in range(len(t)):
        _sel = (t >= t[_i] - ROLL_WIN) & (t <= t[_i])
        if _sel.any():
            c_t[_i] = float(mark[_sel].mean())
    # 第二把尺子：**原始 EAR** 直接数闭眼占比，不依赖任何标记。
    #   为什么非要两把：mark 尺准，但只在用户**按了空格**时才准 —— 他闭眼
    #   8 秒却忘了按结束，mark 尺就看不见那 3 秒。EAR 尺不依赖人，但要一个
    #   阈值。各自漏掉的正是对方强的地方，所以取**与**（更保守）。
    #   阈值 = 睁眼参考往下 35% 的跨度。睁眼参考取 p90、闭眼参考取 p5 ——
    #   闭眼在一场会话里总是少数，两端的极值点必然落在两个模态里；35% 比
    #   中点更靠闭眼侧，因为归一化基线本身就是 p75、天然偏睁眼侧。
    _eo = float(np.nanpercentile(ear, 90))
    _ec = float(np.nanpercentile(ear, 5))
    _thr = _eo - 0.35 * (_eo - _ec)
    eye_shut = np.where(np.isfinite(ear), (ear < _thr).astype(float), np.nan)
    c_e = np.full(len(t), np.nan)
    for _i in range(len(t)):
        _sel = (t >= t[_i] - ROLL_WIN) & (t <= t[_i])
        if _sel.any():
            c_e[_i] = float(np.nanmean(eye_shut[_sel]))
    valid = (np.isfinite(c_t) & (c_t <= C_SAFE)
             & np.isfinite(c_e) & (c_e <= C_SAFE))
    c_max = float(np.nanmax(c_t)) if np.isfinite(c_t).any() else float("nan")
    c_e_max = float(np.nanmax(c_e)) if np.isfinite(c_e).any() else float("nan")
    n_bad = int((~valid).sum())

    def _v(x):
        """把基线坏掉的拍打成 NaN —— 喂给 _r / np.mean 的最省事写法。"""
        return np.where(valid, x, np.nan)

    print("=" * 70)
    print(f"L4 支路二真人会话判决   {args.csv}")
    print(f"  时长 {dur:.1f} s   决策 {len(t)} 拍   "
          f"实测 {len(t) / max(dur, 1e-9):.1f} Hz")
    if np.isfinite(r_x):
        print(f"  两个 EAR_norm 口径一致性 r(en_now, en_rec) = {r_x:+.3f}"
              f"（{n_x} 拍可比）")
        if r_x < 0.9:
            print("     ⚠️ 两者差得有点多。en_now 是发布路径当场算的、en_rec 是事后")
            print("        按当前参数重算的 —— 差这么多说明录制时的参数与现在不一致，")
            print("        或归一化状态有漂移。判决仍以 en_now 为准，但值得查。")
    else:
        print("  两个 EAR_norm 口径：可比拍数不足，跳过一致性检查")

    # ══【0】结构性：支路二到底跑起来没有 ══════════════════════════════
    # 这一节不过，后面三节全部作废 —— 那正是 `runs/fuse_replay_full.txt`
    # 里「结构性通过，不算验证」的意思。
    print("\n" + "─" * 70)
    print("【0】结构性：支路二开口了吗")
    n_pfat = int(np.isfinite(p_fat).sum())
    n_open = int(gate.sum())
    gate_frac = float(gate.mean()) if len(gate) else 0.0
    # 关闭事件 = True→False 的次数 = True 段数(结尾为 True 时减一)
    n_gate_drop = n_true_runs(gate) - (1 if gate.size and gate[-1] else 0)
    run_s, run_a, run_b = longest_true_run(gate, t)
    print(f"  闸门开 {n_open}/{len(gate)} 拍（{100 * gate_frac:.1f}%）")
    span = f"（t={run_a:.1f} → {run_b:.1f}）" if np.isfinite(run_a) else ""
    print(f"  最长连续闸门开段 {run_s:.1f} s{span}")
    print(f"  闸门关闭事件 {n_gate_drop} 次 —— 每关一次，支路二 "
          f"{HIST_SEC:.0f} s 热身清零")
    print(f"  p_fat 出数 {n_pfat} 拍（占闸门开的 "
          f"{100 * n_pfat / max(1, n_open):.1f}%）")
    if n_pfat == 0:
        print("  ❌ 支路二**一次都没开口** —— 结构性缺口还在。")
        if run_s < HIST_SEC:
            print(f"     最长的连续闸门开段只有 {run_s:.1f} s，不到 "
                  f"{HIST_SEC:.0f} s。热身**根本没可能**完成。")
            print("     下回：坐正、视线盯住**镜头本身**（不是屏幕 —— 看屏幕时")
            print("     头会跟着扫视动），把 HUD 上 BRANCH 2 WARMING 的倒计时")
            print("     盯到归零再开始做动作。")
        else:
            print(f"     闸门连续开够 {run_s:.1f} s 了却还是没开口 —— "
                  "那要查 p_fat 是不是一直非有限（特征里有 NaN）。")
        return 1
    t_first = float(t[np.isfinite(p_fat)][0])
    print(f"  首次出数 t={t_first:.1f} s（开场后 {t_first - float(t[0]):.1f} s）")
    print("  ✅ 支路二出过数 —— 结构性缺口补上了。"
          "这正是离线回放做不到的那件事。")
    # 基线护栏在这一节先报总账（细则和逐段剔除在【3】）—— 它决定后面三节
    # 用哪些拍。放在【0】是因为它和「支路二跑没跑起来」一样属于**数据可用性**。
    print(f"  基线护栏：10 s 窗内闭眼占比最高 {c_max:.2f}（标记尺）/ "
          f"{c_e_max:.2f}（EAR 尺），安全线 {C_SAFE:.2f}"
          + ("  —— 全程有效，三节都用全部拍"
             if n_bad == 0 else
             f"  —— 超线 {n_bad}/{len(t)} 拍（{100 * n_bad / len(t):.0f}%），"
             "这几拍的 EAR_norm 基线塌了，【1】【2】【3】都不用它们"))

    # ══【1】自我否证：闸门开的帧里 EAR_norm 是不是头姿的影子 ═══════════
    # 离线那 95 段量到 −0.56；把「头不动且在中位姿态」的窗挑出来之后降到 +0.02。
    # 闸门本来就在按「支路一判正视前方」筛，所以这一节的 r 应当比整段低。
    print("\n" + "─" * 70)
    print("【1】自我否证：闸门开的帧里 r(EAR_norm, pitch)")
    r_ep, n_ep = _r(_v(en_now), pitch)   # pitch 与基线无关，只掩 EAR 侧
    if np.isfinite(r_ep):
        print(f"  r = {r_ep:+.3f}（{n_ep} 拍）")
        if abs(r_ep) >= 0.6:
            print("     ❌ 太高 —— 这段会话里 EAR 基本在跟着头姿走，闭眼和低头")
            print("        分不开。**本次数据不能作为证据**。")
        elif abs(r_ep) >= 0.35:
            print("     ⚠️ 中等相关，数据可疑 —— 这时**只有空格标记过的片段算数**，")
            print("        直接看【3】；【2】的滑窗结论在这种情况下不能单独用。")
        else:
            print("     ✅ 低 —— EAR 不是头姿的影子（离线跨片段是 −0.56）")
    else:
        print(f"  r =   -（可比拍数只有 {n_ep}，不够）")

    # ══【2】归因：p_fat 跟眼睛走还是跟头走 ════════════════════════════
    # 这一节是 fuse.csv **独有**的：live_face 那边没有 gate/p_fat，只能判
    # 「PERCLOS 上不上得去」；这里能直接判**模型自己的输出**。
    print("\n" + "─" * 70)
    print("【2】归因：p_fat 跟眼睛走还是跟头走")
    # 绝对 pitch 的中性基准。跳过开头 10 秒、排除标记帧 —— 两个坑都踩过，
    # 理由见 `_scratch/live_face.py:264-269`：整段中位会把「一直低头」当正常，
    # 开头几秒又正是人在启动脚本、最不中性的时候。
    h0 = np.isfinite(pitch) & (~mark) & (t > t[0] + 10.0)
    p_ref = (float(np.median(pitch[h0])) if h0.sum() > 30
             else float(np.nanmedian(pitch)))
    print(f"  中性姿态基准 = 跳过开头 10 s、排除标记帧后的 pitch 中位 "
          f"= {p_ref:.1f}°")
    # pitch 在闸门关着时也有值（它只依赖人脸检测，不依赖支路二缓冲），
    # 所以 p_ref 覆盖整段，不受闸门限制。
    dp = np.abs(pitch - p_ref)
    live = np.isfinite(p_fat) & valid
    if int(live.sum()) < 8:
        print(f"  p_fat 出数只有 {int(live.sum())} 拍，做不了归因。看【3】。")
    else:
        # ⚠️ perclos 是**逻辑回归自己的输入特征**（标准化系数 +0.859），所以
        #   r(p_fat, perclos) 必然很高 —— 那是**循环论证，不是证据**。
        #   实测过一场 10 分钟会话：r(p_fat, perclos)=+0.959，同时
        #   r(p_fat, en_now)=+0.096（几乎为零、符号还是反的）。
        #   要问的真问题是「perclos 本身可不可信」，不是它跟 p_fat 多像 ——
        #   那个看下面的 r(PERCLOS, 头动范围) 与分层。
        for label, x, expect in (
                ("en_now   (眼)", _v(en_now), "负：EAR 降 → P 升"),
                ("perclos  (眼)", _v(perclos), "正 —— 但循环论证，别当证据报"),
                ("|pitch−基|(头)", dp, "≈0：跟头 = 支路二在测头，坏消息")):
            r_, n_ = _r(_v(p_fat), x)
            shown = f"{r_:+.3f}" if np.isfinite(r_) else "  -  "
            print(f"  r(p_fat, {label}) = {shown}   [{n_:4d} 拍]  期望 {expect}")
        r_eye, _ = _r(_v(p_fat), _v(en_now))
        r_head, _ = _r(_v(p_fat), dp)
        if np.isfinite(r_eye) and np.isfinite(r_head):
            # ⚠️ **先看量级再看谁大**。原来先比大小，于是两个 r 都≈0 时
            #   （|r_head|=0.051 vs |r_eye|=0.023）会印出「p_fat 跟头更近 ——
            #   支路二的响应可能还是头姿的影子」—— 把两位小数的噪声读成了
            #   结论。session1 就是这样误报的。量级不够时没有「更近」可言。
            if max(abs(r_eye), abs(r_head)) < 0.3:
                print("  ⚠️ 两个相关都不大（|r| 都 < 0.3）—— 这一节**不表态**，")
                print("     归因看【3】的标记对照（那边的对照是设计出来的，不是回归出来的）。")
            elif abs(r_eye) > abs(r_head):
                print("  ✅ p_fat 与眼睛的关系强于与头的关系 —— 支路二在测眼睛。")
            else:
                print("  ❌ p_fat 跟头更近 —— 支路二的响应可能还是头姿的影子。")

        # 滑窗分层：照搬 live_face 的 STILL + NEUT 双条件。
        # ⚠️ 只看「窗内极差小」会中招：把头稳稳低着 22° 保持 5 秒，极差照样
        #    只有 4°，会被判成「头不动」，然后拿几何压扁的 EAR 当闭眼证据
        #    （`live_face.py:302-308` 原话）。
        W, S = 5.0, 1.0
        wr, wp, wf, wm = [], [], [], []
        for st in np.arange(t[0], t[-1] - W, S):
            s = (t >= st) & (t < st + W)
            if s.sum() < 5:
                continue
            if args.win_thr == "frames":
                keep = s.sum() >= int(W * 15.0 * 0.6)
            elif args.win_thr == "none":
                keep = True
            else:
                ts_ = t[s]
                keep = float(ts_[-1] - ts_[0]) >= 0.8 * W
            if not keep:
                continue
            p_ = pitch[s]
            p_ = p_[np.isfinite(p_)]
            if p_.size < 3:
                continue
            e_ = en_rec[s]
            e_ = e_[np.isfinite(e_) & valid[s]]   # 基线坏的拍不进 PERCLOS
            wr.append(float(np.percentile(p_, 95) - np.percentile(p_, 5)))
            wp.append(float(np.mean(e_ < BLINK_THR)) if e_.size else np.nan)
            wm.append(float(np.median(p_)))
            pf = p_fat[s]
            pf = pf[np.isfinite(pf) & valid[s]]
            wf.append(float(np.median(pf)) if pf.size else np.nan)
        wr, wp, wf, wm = map(np.asarray, (wr, wp, wf, wm))
        print(f"\n  滑窗（{W:.0f} s 窗 / {S:.0f} s 步长，滤网 {args.win_thr}）："
              f"保留 {len(wr)} 个")
        if len(wr) >= 4:
            r_all, n_all = _r(wp, wr)
            shown = f"{r_all:+.3f}" if np.isfinite(r_all) else "  -  "
            print(f"  r(PERCLOS, 头动范围) = {shown}   （离线 95 段是 +0.61）")
            st_w = (wr < args.still) & (np.abs(wm - p_ref) < args.neut)
            print(f"  头不动 **且** 在中位姿态的窗：{int(st_w.sum())}/{len(wr)} 个"
                  f"（极差 < {args.still:.0f}° 且 |窗中位−基准| < "
                  f"{args.neut:.0f}°）")
            if st_w.sum() == 0:
                print("     ❌ 一个都没有 —— 整段要么头在动，要么头一直没回中位。")
                print("        这次证不了任何事：坐正、头别动、只闭眼。")
            else:
                fin = st_w & np.isfinite(wf)
                print(f"     PERCLOS 中位 {np.nanmedian(wp[st_w]):.3f}   "
                      f"最高 {np.nanmax(wp[st_w]):.3f}")
                if fin.sum():
                    print(f"     p_fat  中位 {np.nanmedian(wf[fin]):.3f}   "
                          f"最高 {np.nanmax(wf[fin]):.3f}   "
                          f"（{int(fin.sum())} 个窗有 p_fat）")
                    print("     ⚠️ 这个中位是**被滑窗筛过一轮**的，别当门面数报：")
                    print("        本判决的分层变量是「头动不动」，而滤网也在按采样")
                    print("        跨度筛，小样本下两者相关（`_d7_probe.py` 在旧会话上")
                    print("        量到 r(帧数, 头动) = −0.45）。要不吃筛子的结论，看【3】。")
                else:
                    print("     这些窗里 p_fat 全空 —— 闸门连续开够 27 s 的窗太少。")

    # ══【3】标记期：最硬的一条 ═══════════════════════════════════════
    print("\n" + "─" * 70)
    print("【3】按空格标记的「我在闭眼」")
    if not mark.any():
        print("  这一次没有任何标记。**判决到此为止。**")
        print("  没有标记就只能靠【2】的滑窗，而滑窗的分层变量（头动不动）")
        print("  和被筛的维度是同一个 —— 那正是「这段疲劳到底靠眼睛还是靠头动」")
        print("  证不出来的原因。重跑一次，闭眼时按空格。")
        return 1
    # 用 en_rec 而不是 en_now：标记期几乎必然横跨闸门开关（闭眼久了支路一
    # 可能改判），用 en_now 会让标记期和未标记期落在**不同的采样集合**上，
    # 比值就没意义了。en_rec 凡检到脸就有值，两侧样本对齐。
    # ⚠️ 两侧都只用**基线没塌的拍**（valid）—— 掩码的来历见文件头上方那段。
    mk_m = mark & valid
    mk_u = (~mark) & valid
    pc_m = (float(np.mean(en_rec[mk_m] < BLINK_THR)) if mk_m.any()
            else float("nan"))
    pc_u = (float(np.mean(en_rec[mk_u] < BLINK_THR)) if mk_u.any()
            else float("nan"))
    seg = runs_sec(t, mark.astype(float), lambda v: v > 0)
    mk_sec = float(sum(seg))
    # 头动只跟 pitch 有关（pitch 不经基线），但**要和 pc_m 用同一批拍**才可比，
    # 否则又变成两个样本集合的对比 —— 那正是【3】一直在避免的错。
    p_m = pitch[mk_m]
    p_m = p_m[np.isfinite(p_m)]
    hr_m = (float(np.percentile(p_m, 95) - np.percentile(p_m, 5))
            if p_m.size > 15 else np.nan)
    ratio = (pc_m / pc_u if np.isfinite(pc_u) and pc_u > 1e-6
             else float("nan"))
    print(f"  共 {len(seg)} 段、{mk_sec:.1f} s（{int(mark.sum())} 拍）")

    # ── 护栏 A：基线有效性（细则；总账在【0】）─────────────────────
    print(f"  护栏A 基线：10 s 窗内闭眼占比最高 {c_max:.2f}（标记尺）/ "
          f"{c_e_max:.2f}（EAR 尺），安全线 {C_SAFE:.2f}")
    if not n_bad:
        print("     没有一拍超线 —— 基线全程有效。")
    else:
        print(f"     超线 {n_bad}/{len(t)} 拍（{100 * n_bad / max(1, len(t)):.0f}%），"
              "这些拍的 EAR_norm 基线塌到了闭眼值上，三节都已剔掉：")
        i = 0
        while i < len(t):
            if not valid[i]:
                j = i
                while j + 1 < len(t) and not valid[j + 1]:
                    j += 1
                who = []
                if np.nanmax(c_t[i:j + 1]) > C_SAFE:
                    who.append("标记尺")
                if np.nanmax(c_e[i:j + 1]) > C_SAFE:
                    who.append("EAR 尺")
                print(f"       t={t[i]:.1f}~{t[j]:.1f}s（{t[j] - t[i]:.1f}s，"
                      f"c 最高 标记 {np.nanmax(c_t[i:j + 1]):.2f} / "
                      f"EAR {np.nanmax(c_e[i:j + 1]):.2f}，{'＋'.join(who)}判的）"
                      f"  其中标记拍 {int(mark[i:j + 1].sum())} 个")
                i = j + 1
            else:
                i += 1
    n_mark, n_mark_ok = int(mark.sum()), int(mk_m.sum())
    print(f"     标记拍 {n_mark} 个，可用 {n_mark_ok} 个"
          f"（{100 * n_mark_ok / max(1, n_mark):.0f}%）")

    # ── 护栏 B：方向（独立于 A）────────────────────────────────────
    #   闭眼时 EAR_norm 必须**比睁眼低**。这是一句对「测量有没有反向」的
    #   直接检验，比 c 这个代理更贴目标，而且和 A 抓的是不同的失效：
    #   A 管基线塌没塌，B 管结果方向对不对（标记按反、人脸丢了、判据写反）。
    en_med_m = float(np.nanmedian(en_rec[mk_m])) if mk_m.any() else float("nan")
    en_med_u = float(np.nanmedian(en_rec[mk_u])) if mk_u.any() else float("nan")
    dir_ok = (np.isfinite(en_med_m) and np.isfinite(en_med_u)
              and en_med_m < en_med_u)
    print(f"  护栏B 方向：EAR_norm 中位 标记期 {en_med_m:.3f} vs 未标记期 "
          f"{en_med_u:.3f}"
          + ("  ✅ 闭眼更低" if dir_ok else "  ❌ 没有更低 —— 测量反了"))
    # ── 直接量一下**用上的那些拍的基线**落在哪儿 ────────────────────
    #   护栏 A 是**代理**（数闭眼占比，再推断基线该在哪儿）。这里直接测量
    #   基线本身：ear/en_rec 就是当时那个 p75。健康时它该落在睁眼区间
    #   （略低于全场睁眼参考 p90）；塌陷时会掉到闭眼值附近。
    #   有了这一行，读判决的人不必相信我的阈值 —— 数字自己说基线在哪。
    base_used = ear[mk_m] / np.maximum(en_rec[mk_m], 1e-6)
    base_used = base_used[np.isfinite(base_used)]
    ref_open = float(np.nanpercentile(ear, 90))
    if base_used.size:
        print(f"     直接量基线（= ear/en_rec，就是当时的 p75）："
              f"可用标记拍中位 {np.median(base_used):.3f}，"
              f"全场睁眼参考 p90 {ref_open:.3f}")
    # ── 判定 ────────────────────────────────────────────────────────
    #   ⚠️ 这里**故意不设「可用率必须 ≥ X%」的闸**。我一度写过 0.70，
    #      结果 session1 落在 0.698 —— 判决由 0.002 决定，那是阈值在做推理，
    #      不是在测量。护栏A 已经把坏拍剔掉了，剩下多少是**证据的多少**，
    #      该报出来让人看见，而不是拿去当通过/不通过的门槛。
    #      真正该硬的地方只有一个：剔完之后还剩不剩得下东西。
    guard_ok = dir_ok and n_mark_ok >= 20 and mk_u.sum() >= 20
    if not guard_ok:
        if not dir_ok:
            print("     ❌ 这一场的【3】数字**不可信**：EAR_norm 在闭眼时没有")
            print("        低下去。要么基线塌了，要么标记按反 / 人脸丢了。")
        else:
            print(f"     ❌ 这一场**不作数**：剔掉基线塌陷之后，可用的标记拍"
                  f"只剩 {n_mark_ok} 个（未标记拍 {int(mk_u.sum())} 个），"
                  "样本不够。")
        print("        重跑：闭眼 <= 5 s，每次之间睁眼歇 >= 12 s。")
        print("        要拉长的是**间隔**，不是闭眼时长。")
    elif n_mark_ok < 0.75 * n_mark:
        # 剔得多就**明说**，不让结论看起来比证据干净 —— 但不因此否决：
        # 剩下的那些拍的基线是**逐拍量过**的，不是推断出来的。
        print(f"     ⚠️ 口径：标记拍剔掉了 {n_mark - n_mark_ok}/{n_mark}"
              f"（{100 * (1 - n_mark_ok / n_mark):.0f}%），"
              f"下面的对照只用剩下的 {n_mark_ok} 个。")
    hr_s = f"{hr_m:.1f}" if np.isfinite(hr_m) else " - "
    # ⚠️ 名字别撞车：这里的 pc_m 是**逐帧**「EAR_norm 低于阈值的拍占多少」，
    #   和 CSV 里那个 `perclos` 列（WIN_SEC = 17 秒窗内的占比）**不是同一个量**。
    #   两者容易在材料里被当成一回事，所以这里一律叫「闭眼帧占比」。
    print(f"  标记期   闭眼帧占比 {pc_m:.3f}   头动范围 {hr_s}°")
    print(f"  未标记期 闭眼帧占比 {pc_u:.3f}")
    print("     （这是**逐帧**占比，不是 CSV 里 perclos 列那个 17 秒窗占比 ——")
    print("       两个量别在材料里混着用。）")
    # ⚠️ pc_u 可能是**精确的 0**（未标记期一次闭眼都没有 —— 短会话里不罕见）。
    #   直接打印 pc_m/pc_u 会印出一个由 1e-6 保护生出来的 "1000000.0 倍"，
    #   看着像结论其实是无意义的。这种情况要说人话。
    if np.isfinite(ratio):
        print(f"  → 标记期高出 {ratio:.1f} 倍")
    else:
        print("  → 未标记期一次闭眼都没有，比值无从谈起（这本身是好事，"
              "但也说明未标记期太短）")
    # 同时给一份发布路径口径（en_now）：en_rec 是事后重算的，两者同向才说明
    # 屏上那个数和判决用的数是一回事（`live_face.py:562-564` 的告诫）。
    en_m = en_now[mk_m]
    en_m = en_m[np.isfinite(en_m)]
    en_u = en_now[mk_u]
    en_u = en_u[np.isfinite(en_u)]
    if en_m.size and en_u.size:
        pm_now = float(np.mean(en_m < BLINK_THR))
        pu_now = float(np.mean(en_u < BLINK_THR))
        rt = (f"，高出 {pm_now / pu_now:.1f} 倍" if pu_now > 1e-6 else "")
        print(f"  （发布路径口径 en_now：标记期 {pm_now:.3f} vs 未标记期 "
              f"{pu_now:.3f}{rt} —— 与上面同向才说明屏上那个数和判决用的数"
              f"是一回事）")
    else:
        print("  （en_now 在标记期样本不足，发布路径口径这次给不出来）")
    # ⚠️ D1：中间地带**必须打印**，不许静默通过。
    #    `live_face.py:372-384` 记过：2026-09-22 那场会话 pc_m=0.694 但
    #    hr_m=8.2 差 0.2° 越线，两个分支都不满足，整场最硬的证据判成了空白。
    if not guard_ok:
        print("  ❌ 不判 —— 护栏没过（见上）。这一场的 EAR_norm 被搞坏了，")
        print("     拿它下结论，就是把测量事故当成支路二的毛病。先按 protocol 重跑。")
    elif pc_m > 0.5 and np.isfinite(hr_m) and hr_m < 8:
        print("  ✅ 闭眼时闭眼帧占比高、头没动 —— 这一条最硬。支路二成立。")
    elif pc_m <= pc_u * 1.3:
        print("  ❌ 闭眼时闭眼帧占比没比睁眼高多少 —— EAR 没抓到闭眼。")
    else:
        rt = f"，{ratio:.1f} 倍" if np.isfinite(ratio) else ""
        print("  ⚠️ 中间地带 —— **不静默通过**：闭眼帧占比确实抬起来了"
              f"（{pc_m:.3f} vs {pc_u:.3f}{rt}），")
        print(f"     但标记期头动 {hr_s}° 越过了 8° 那条线。"
              "那条 8° 是**拍的、不是标定的** ——")
        print("     结论立在不带阈值的那个倍数比较上；要收紧就把头动判据改成标定的。")

    # ── 图 ────────────────────────────────────────────────────────────
    if args.png:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(5, 1, figsize=(12, 11), sharex=True)
        ax[0].plot(t, en_rec, lw=0.8, label="EAR_norm (recomputed)")
        if np.isfinite(en_now).any():
            ax[0].plot(t, en_now, lw=0.8, alpha=0.6, label="EAR_norm (en_now)")
        ax[0].axhline(BLINK_THR, color="orange", ls="--", lw=1,
                      label=f"thr {BLINK_THR}")
        ax[0].set_ylabel("EAR_norm")
        ax[0].legend(loc="upper right", fontsize=8)
        ax[1].plot(t, pitch, lw=0.8, color="green")
        ax[1].axhline(p_ref, color="gray", ls=":", lw=1,
                      label=f"neutral {p_ref:.1f}")
        ax[1].set_ylabel("pitch (deg)")
        ax[1].set_title("HEAD POSE - the control variable", fontsize=9)
        ax[1].legend(loc="upper right", fontsize=8)
        ax[2].plot(t, mar, lw=0.8, color="purple")
        ax[2].set_ylabel("MAR")
        ax[3].plot(t, p_fat, lw=1.0, color="crimson")
        ax[3].set_ylabel("P(fatigue)")
        ax[3].set_title("branch 2 output - only exists while gate open",
                        fontsize=9)
        ax[4].plot(t, gate.astype(float), lw=1.0, color="steelblue")
        ax[4].set_ylabel("gate")
        ax[4].set_xlabel("time (s)")
        ax[4].set_title(f"gate open {100 * gate_frac:.0f}%  |  "
                        f"branch2 spoke {n_pfat} ticks", fontsize=9)
        for x in ax:
            x.fill_between(t, *x.get_ylim(), where=mark, alpha=0.12,
                           color="blue")
            if n_bad:   # 基线塌陷、已剔除的拍 —— 画出来，别让图比报告干净
                x.fill_between(t, *x.get_ylim(), where=~valid, alpha=0.30,
                               color="red")
        fig.suptitle("branch2 L4 live session  "
                     "(blue = space-marked, red = excluded)",
                     fontsize=10)
        fig.tight_layout()
        fig.savefig(args.png, dpi=110)
        print(f"\n判决图 -> {args.png}")

    print("\n" + "=" * 70)
    if not guard_ok:
        print("【结论】这一场**不判** —— 护栏没过，测量本身失效了。")
        print(f"  护栏A：10 s 窗内闭眼占比最高 {c_max:.2f}（标记尺）/ "
              f"{c_e_max:.2f}（EAR 尺），安全线 {C_SAFE:.2f}；"
              f"可用标记拍 {n_mark_ok}/{n_mark}。")
        print(f"  护栏B：EAR_norm 标记期 {en_med_m:.3f} vs 未标记期 "
              f"{en_med_u:.3f}。")
        if not dir_ok:
            print("  norm_by_time 的 p75 基线塌到了闭眼值上，EAR_norm 反向。")
        else:
            print("  方向是对的，但剔掉基线塌陷后剩下的拍太少 —— 不是测量反了，")
            print("  是这一场能用的证据不够。")
        print("  重跑：闭眼 <= 5 s，间隔 >= 12 s。")
    else:
        print("【结论】支路二在真人会话里跑起来了，判据见上。")
        print("  最硬的是【3】：标记期 PERCLOS 高而头没动。")
        print(f"  ⚠️ 口径（做材料时必须照写）：全场剔掉 {n_bad} 拍基线塌陷"
              f"（{100 * n_bad / max(1, len(t)):.0f}%），"
              f"标记拍用了 {n_mark_ok}/{n_mark}。")
        print("     别把「剔过之后成立」说成「全程成立」。")
        print("  【2】的滑窗数是**筛过一轮**的，做材料时要么注明口径，要么只用【3】。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
