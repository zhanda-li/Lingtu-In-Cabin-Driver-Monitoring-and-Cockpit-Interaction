# -*- coding: utf-8 -*-
"""标定「低头/点头」这条**规则**要多久 —— 用户原话「短点头 我肯定就点一次啊
只要我低头就应该报啊 我都快死了」。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_calib_head_down.py [--grid 0.5,0.8,1.0,1.5,2.0,3.0]

**为什么是这条而不是"再降 ENTER_TH"**：`ENTER_TH=0.60 / ENTER_SEC=0.25` 是
**模型**的迟滞（`src/live.py:112-117`），单次短低头在 45 帧（3 s）窗里只占一小段，
模型给的概率本来就上不到 0.60 —— 那不是阈值调不够低，是**窗里没有足够的证据**。
而「头偏出中性姿态持续多久」是**几何量**，跟前几帧直接比就有答案，不需要模型、
不需要 17 s 统计窗、也不需要 27 s 缓冲。哈欠规则当初就是这么绕开预热的
（`src/fuse.py:614-619`），这条是同一种东西。

⚠️ 判据完全照 `src/face.py:90` 的定义：`|pitch − 本段中位| > NOD_DROP(12°)`，
   只把「算一次点头」换成「连续多少秒」。**中位取整段**（离线 `_features` 的口径），
   在线是取窗内中位 —— 两个口径在本批片段上差异很小，但报告里要说清是哪一个。
⚠️ pitch 可能是 NaN（没有面部变换矩阵时），NaN 不算「低于中位」也不算「高于」，
   和 `src/face.py:383` 那条「没检到脸也要塞 NaN、记成没闭眼」的保守口径一致。
"""
import argparse
import json
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from face import (HEAD_DEG, HEAD_REF_ITERS, HEAD_REF_Q, HEAD_REF_WIN,  # noqa: E402
                  NOD_DROP, NOD_MIN, ROLL_WIN, norm_by_time, runs_sec)

CACHE = os.path.join(HERE, "_ear_raw.npz")
TABLE = os.path.join(HERE, "_calib_head_down_ref.json")   # 【6】的表 → 给 _check_head_dir【2】对账
GROUPS = ("normal", "glance", "phone", "fatigue")
EXTRA = ("talking", "yawn_open")


def ref_at(ts, p, now, ref_win=HEAD_REF_WIN, q=HEAD_REF_Q, tol=HEAD_DEG):
    """`now` 这一刻的**平视位**（度）—— 本工具**另写一遍**生产的 `face.head_ref`。

    ★ **2026-09-26 第四次**：生产换成**双侧修剪**（"离当前估计超过 `tol` 度的帧不算数，
      在内点集上重取分位"），这里也重写一遍、**写法故意不同**：生产用
      `np.percentile` + `np.abs` 掩码，这里用 `np.quantile` + 布尔掩码累乘；迭代次数
      两边都从 `HEAD_REF_ITERS` 取。⚠️ 老实说，**两边现在是同一条算法**（这轮换口径
      之后躲不开），所以这条互校能抓的是"常量/迭代次数不同步"和"边界处理不同"
      （有效帧 ≥5、`ts <= now`），**抓不到"公式抄错一次"** —— 别当成比它实际更强的保证。

    ⚠️ 这里原来还有"短窗那一项（p25(最近 ROLL_WIN 秒)）取 max"。**2026-09-26 第四次
       删掉了** —— 生产（`face.head_ref`）也删了，那一项能被持续低头拽高、而 `max`
       只升不降，于是"人还低着、判据自己先松手"。删了之后这里才和生产同口径；
       忘了删的话【2】的互校会当场红（它就是这么发现我漏改的）。
    """
    ts = np.asarray(ts, float)
    p = np.asarray(p, float)
    m = (ts <= now) & (ts >= now - ref_win) & np.isfinite(p)
    v = p[m]
    if v.size < 5:                                      # noqa: PLR2004
        return np.nan
    r = float(np.quantile(v, q / 100.0))
    for _ in range(HEAD_REF_ITERS):
        inner = v[np.abs(v - r) <= tol]
        if inner.size < 5:                              # noqa: PLR2004
            break
        r = float(np.quantile(inner, q / 100.0))
    return r


def load():
    z = np.load(CACHE, allow_pickle=True)
    per = {g: [] for g in GROUPS + EXTRA}
    for k in z.files:
        parts = k.split("|")
        if len(parts) != 3 or parts[2] != "euler":
            continue
        g, clip, _ = parts
        if g not in per:
            continue
        tk = "%s|%s|t" % (g, clip)
        if tk not in z.files:
            continue
        ts = np.asarray(z[tk], float)
        eu = np.asarray(z[k], float)
        if eu.ndim != 2 or eu.shape[1] < 3 or len(ts) < 20:      # noqa: PLR2004
            continue
        pitch = eu[:, 0]
        yaw = eu[:, 1]
        if not np.isfinite(pitch).any():
            continue
        mid = float(np.median(pitch[np.isfinite(pitch)]))
        run = max(runs_sec(ts, pitch, lambda v, m=mid: abs(v - m) > NOD_DROP) or [0.0])
        fin = pitch[np.isfinite(pitch)]
        per[g].append((clip, run,
                       float(np.percentile(fin, 95) - np.percentile(fin, 5)),
                       float(np.percentile(yaw[np.isfinite(yaw)], 95)
                             - np.percentile(yaw[np.isfinite(yaw)], 5))))
    return per


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="0.5,0.8,1.0,1.5,2.0,3.0")
    args = ap.parse_args()
    grid = [float(x) for x in args.grid.split(",")]
    per = load()

    print("NOD_DROP=%.0f°（判据取 |pitch − 整段中位| > 它）" % NOD_DROP)
    print("\n【1】每段最长的连续低头（秒）—— 「低头一次」到底有多长")
    for g in GROUPS + EXTRA:
        if not per[g]:
            continue
        d = sorted(v for _, v, _, _ in per[g])
        print("\n  %-9s %d 段   最短 %.2f  中位 %.2f  最长 %.2f"
              % (g, len(d), d[0], d[len(d) // 2], d[-1]))
        print("            " + "  ".join("%s=%.2f" % (c[-6:], v)
                                         for c, v, _, _ in sorted(per[g],
                                                                  key=lambda x: x[1])))
    print("\n【2】头动幅度（pitch p95−p5，度）—— 顺带看谁在真低头")
    for g in GROUPS + EXTRA:
        if not per[g]:
            continue
        d = sorted(v for _, _, v, _ in per[g])
        y = sorted(v for _, _, _, v in per[g])
        print("  %-9s pitch 极差 中位 %5.1f°  最大 %5.1f°   |  yaw 极差 中位 %5.1f°"
              % (g, d[len(d) // 2], d[-1], y[len(y) // 2]))

    print("\n【3】N 扫描：正常侧要**全部不触发**，低头/疲劳侧要尽量多触发")
    print("\n     %-6s %-12s %-12s %-12s %-12s %s"
          % ("N(s)", "正常", "低头", "疲劳", "说话", "正常侧最长 vs N"))
    for N in grid:
        a = sum(v >= N for _, v, _, _ in per["normal"])
        b = sum(v >= N for _, v, _, _ in per["phone"])
        c = sum(v >= N for _, v, _, _ in per["fatigue"])
        t = sum(v >= N for _, v, _, _ in per["talking"])
        mx = max(v for _, v, _, _ in per["normal"])
        print("     %-6.1f %-12s %-12s %-12s %-12s %s%.2f"
              % (N, "%d/%d" % (a, len(per["normal"])), "%d/%d" % (b, len(per["phone"])),
                 "%d/%d" % (c, len(per["fatigue"])), "%d/%d" % (t, len(per["talking"])),
                 "✅ " if mx < N else "⚠️ 越界 ", mx))

    # ── 4. 免基线的那个量：最近 2 秒里头的**摆动幅度** ────────────────────
    #    【1】那个量是 |pitch − 整段中位|，对**持续低头**天然瞎（中位自己挪过去了）。
    #    这个量换了个问法：「最近 2 秒里，头从最低摆到最高差多少度」——
    #      · **不需要任何基线**，所以开机第 2 秒就能判（用户要的「直接接入」）
    #      · 「低头一次」和「反复点头」都落在里面（一次低头也是摆幅）
    #      · 但它**分不出"低头困了"和"低头看仪表"** —— 那是时长/节律的事
    print("\n【4】免基线的「最近 2 秒摆动幅度」—— 开机即可用，单次低头也算")
    TRAIL, STEP = 2.0, 0.2
    z = np.load(CACHE, allow_pickle=True)
    rows = {g: [] for g in GROUPS + EXTRA}
    for k in z.files:
        parts = k.split("|")
        if len(parts) != 3 or parts[2] != "euler":
            continue
        g, clip, _ = parts
        if g not in rows:
            continue
        tk = "%s|%s|t" % (g, clip)
        if tk not in z.files:
            continue
        ts = np.asarray(z[tk], float)
        eu = np.asarray(z[k], float)
        if eu.ndim != 2 or eu.shape[1] < 1 or len(ts) < 20:      # noqa: PLR2004
            continue
        p = eu[:, 0]
        if not np.isfinite(p).any():
            continue
        best = 0.0
        t0 = ts[0]
        while t0 + TRAIL <= ts[-1]:
            m = (ts >= t0) & (ts <= t0 + TRAIL) & np.isfinite(p)
            if m.sum() > 5:                                       # noqa: PLR2004
                q = p[m]
                best = max(best, float(np.percentile(q, 95)
                                       - np.percentile(q, 5)))
            t0 += STEP
        rows[g].append((clip, best))
    for g in GROUPS + EXTRA:
        if not rows[g]:
            continue
        d = sorted(v for _, v in rows[g])
        print("  %-9s 中位 %5.1f°  最大 %5.1f°   |  逐段: %s"
              % (g, d[len(d) // 2], d[-1],
                 " ".join("%.0f" % v for _, v in rows[g])))
    print("\n     阈值扫描（这个量**越大越像低头**，与【3】的 N 相反）：")
    print("     %-8s %-12s %-12s %-12s %-12s" % ("阈值", "正常", "低头", "疲劳", "说话"))
    for TH in (8.0, 10.0, 12.0, 15.0, 18.0, 20.0):
        f = lambda g: sum(v >= TH for _, v in rows[g])            # noqa: E731
        print("     %-8.1f %-12s %-12s %-12s %-12s"
              % (TH, "%d/%d" % (f("normal"), len(rows["normal"])),
                 "%d/%d" % (f("phone"), len(rows["phone"])),
                 "%d/%d" % (f("fatigue"), len(rows["fatigue"])),
                 "%d/%d" % (f("talking"), len(rows["talking"]))))

    # ── 6. 带方向的低头量：修「仰头为啥也算低头」（2026-09-26 用户第二问）────
    #    【4】那个量是**极差**（p95 − p5），没有方向：仰头 12° 和低头 12° 在它
    #    眼里一模一样。用户的原话：「我仰头为啥也算持续低头」。
    #    改法照 EAR 那条的镜像 —— EAR 把"闭眼"当**低**的一侧，所以基线取 p75
    #    （高的一侧）；pitch 这边"低头"是**高**的一侧，基线就要取**低**的一侧，
    #    也就是 p25 = 「抬头位」。于是：
    #        dip = p95(最近 TRAIL 秒) − p25(最近 ROLL_WIN 秒)
    #    仰头时 pitch 低于抬头位 → dip 为负 → 永远不会触发。
    #    ⚠️ 两种取参考位的口径都量（窗**末** / 窗**首**）：持续低头超过 7.5 s 时
    #      p25 自己也会被拽上去（这正是 EAR 那条注释里说的"自我抑制"），
    #      两个口径被拽的时机不同，选出来才不是拍脑袋。
    print("\n【6】带方向的低头量（★ 2026-09-26 第四次起生产用的是 **dE** 这一版）")
    print("      dips = p95(最近 %.1fs) − 参考位。参考位三个口径一起量："
          "dW = 窗末的 p25(最近 %.0fs)（治①**之前**生产用的）、"
          "d0 = 窗首的 p25、**dE = 双侧修剪（第四次起生产用的）**"
          % (TRAIL, ROLL_WIN))
    dirs = {g: [] for g in GROUPS + EXTRA}
    for k in z.files:
        parts = k.split("|")
        if len(parts) != 3 or parts[2] != "euler":
            continue
        g, clip, _ = parts
        if g not in dirs:
            continue
        tk = "%s|%s|t" % (g, clip)
        if tk not in z.files:
            continue
        ts = np.asarray(z[tk], float)
        eu = np.asarray(z[k], float)
        if eu.ndim != 2 or len(ts) < 20:                           # noqa: PLR2004
            continue
        p = eu[:, 0]
        if not np.isfinite(p).any():
            continue
        old = norm_by_time(ts, p, ROLL_WIN, q=25.0)      # 旧口径（窗末 p25）
        dE = dW = d0 = upE = 0.0
        t0 = ts[0]
        while t0 + TRAIL <= ts[-1]:
            m = (ts >= t0) & (ts <= t0 + TRAIL) & np.isfinite(p)
            if m.sum() > 5:                                        # noqa: PLR2004
                hi = float(np.percentile(p[m], 95))
                lo = float(np.percentile(p[m], 5))
                rE = ref_at(ts, p, float(ts[m][-1]))               # ← 工具自己写的生产口径
                if np.isfinite(rE):
                    dE = max(dE, hi - rE)
                if np.isfinite(old[m][-1]):
                    dW = max(dW, hi - float(old[m][-1]))
                    # 同样的窗，**上抬**那半（旧判据分不出来的那一半）：
                    upE = max(upE, float(old[m][-1]) - lo)
                if np.isfinite(old[m][0]):
                    d0 = max(d0, hi - float(old[m][0]))
            t0 += STEP
        dirs[g].append((clip, dE, dW, d0, upE))
    for g in GROUPS + EXTRA:
        if not dirs[g]:
            continue
        e = sorted(v for _, v, _, _, _ in dirs[g])
        w = sorted(v for _, _, v, _, _ in dirs[g])
        s = sorted(v for _, _, _, v, _ in dirs[g])
        u = sorted(v for _, _, _, _, v in dirs[g])
        print("  %-9s **dE** 中位 %5.1f° 最大 %5.1f°  |  dW 中位 %5.1f° 最大 %5.1f°"
              "  |  d0 中位 %5.1f° 最大 %5.1f°  |  上抬侧(旧口径) 中位 %5.1f° 最大 %5.1f°"
              % (g, e[len(e) // 2], e[-1], w[len(w) // 2], w[-1],
                 s[len(s) // 2], s[-1], u[len(u) // 2], u[-1]))
    # 这张表要跟 `_check_head_dir.py` 的【2】对账 —— 那边**跑生产函数**算同样的两列。
    # 常量一起落盘：face.py 里的常量改了而这份表没重跑，就是"拿着旧表当证据"，
    # 【2】会当场报红。⚠️ 这条断言以前是假的（只印了两遍同一个数）。
    with open(TABLE, "w", encoding="utf-8") as fh:
        json.dump({"ref_win": HEAD_REF_WIN, "q": HEAD_REF_Q,
                   "tol": HEAD_DEG, "iters": HEAD_REF_ITERS,
                   "trail": TRAIL, "step": STEP,
                   "groups": {g: {"n": len(dirs[g]),
                                  "med": sorted(v for _, v, _, _, _ in dirs[g])[len(dirs[g]) // 2],
                                  "max": max(v for _, v, _, _, _ in dirs[g])}
                              for g in GROUPS + EXTRA if dirs[g]}}, fh, indent=1)
    print("  表已落盘 → %s（【2】拿它跟生产函数对账）" % os.path.basename(TABLE))
    print("\n     阈值扫描（「旧判据的误报」= 这一段是**上抬**顶过阈值、"
          "带方向的量自己没过）")
    print("     %-7s %-10s %-9s %-9s %-9s %-9s %s"
          % ("阈值", "正常", "扭头", "低头", "疲劳", "说话", "旧判据的误报"))
    for TH in (8.0, 10.0, 12.0, 15.0, 18.0):
        for name, idx in (("dE", 1), ("dW", 2), ("d0", 3)):
            f = lambda g: sum(v[idx] >= TH for v in dirs[g])       # noqa: E731
            bad = sum(1 for v in dirs["normal"] + dirs["glance"]
                      if v[4] >= TH and v[idx] < TH)
            tot = len(dirs["normal"]) + len(dirs["glance"])
            print("     %-3s %-4.1f %-10s %-9s %-9s %-9s %-9s %d/%d"
                  % (name, TH, "%d/%d" % (f("normal"), len(dirs["normal"])),
                     "%d/%d" % (f("glance"), len(dirs["glance"])),
                     "%d/%d" % (f("phone"), len(dirs["phone"])),
                     "%d/%d" % (f("fatigue"), len(dirs["fatigue"])),
                     "%d/%d" % (f("talking"), len(dirs["talking"])), bad, tot))
    print("     ⚠️ 「旧判据的误报」那一列就是用户报的「我仰头为啥也算低头」："
          "旧判据（p95−p5）在这几段上会响，而带方向的 dE/dW 不响。")

    # ── 7. 参考位抗拖动（2026-09-26 用户第三问）──────────────────────────
    #    用户原话：「我低头回正后还有很长一段时间报重度疲劳 然后我从回正到仰头
    #    过了一段时间才报疲劳」。量出来的**假的那一次**在仰头回正之后：
    #      w=25.1 仰头 → w=36.05 回正 → 直立着报重度 14.8 s（`hsw` 14.6~25.3）
    #    机制：ref = p25(最近 ROLL_WIN 秒) 被仰头拽到**抬头那一侧**，回正瞬间
    #      hi = p95(最近 2 秒) 已经追上直立、ref 还留在抬头 → 差 20° 上下。
    #    这里扫的就是 ref 的口径。两关必须同时过：
    #      · 正常 0/N、疲劳尽量多（掉了就是"把参考位整体抬高了"，把真低头也修没了）
    #      · 真人会话上"回正之后"的峰值要掉到 HEAD_DEG 以下
    #    ⚠️ 为什么长窗不是万能：p25 容忍窗里 75% 是偏移；用户这场只有 57 秒、
    #      仰头占了 11 秒（19%），**历史越短、长窗越救不了** —— 所以"现场那几十秒"
    #      这一列才是真正的验收列。
    print("\n【7】参考位口径扫描（★ 决定 `src/face.py` 的 ref 怎么算）")

    def q_ref(win, q):
        """最近 win 秒的 q 分位（现状就是这个，win=10、q=25）。"""
        return lambda ts, p: norm_by_time(ts, p, win, q=q)

    def chunked(T, K, q=25.0):
        """把历史切成 K 段各 T 秒，取**各段 p25 里最高的那个**。

        ⚠️ 与"一个长窗取 p25"的区别是**它不赌"偏移占历史多少"**：长窗取分位时，
           偏移占比一旦超过那个分位，参考位就整个塌到偏移那一侧（用户那场 57 秒里
           仰头占 28%，所以 p25 必塌、p40 才够 —— 而他要是动作再快一点，p40 也会塌）。
           分段之后，**只要还有一段历史是干净的**，参考位就还站在抬头位那一侧。
        """
        def f(ts, p):
            out = np.full(len(ts), np.nan)
            for i in range(len(ts)):
                best = np.nan
                for k in range(K):
                    hi = ts[i] - k * T
                    m = (ts >= hi - T) & (ts <= hi) & np.isfinite(p)
                    # ⚠️ 门槛必须是 5：生产（`head_swing`/`head_ref`）和【6】的 `ref_at`
                    #    都是"有效帧 < 5 就不算数"。这里原来写的是 3 —— 于是这张表量的
                    #    是另一个东西（互校一跑就差 0.275°，冷启动那几秒尤其明显）。
                    if m.sum() >= 5:                               # noqa: PLR2004
                        v = float(np.percentile(p[m], q))
                        best = v if not np.isfinite(best) else max(best, v)
                out[i] = best
            return out
        return f

    def two(f1, f2):
        return lambda ts, p: np.fmax(f1(ts, p), f2(ts, p))     # fmax: NaN 侧不算数

    # ★ **2026-09-26 第四次：这一节的口径换了**（`_scratch/_head_ref_cand.py` 是那次
    #   的主实验）。第三次那条"分段取 p25、再取 max"**抗仰头、不抗低头** —— 低头把
    #   最近那一段拖高，而 `max` 只采纳高的那一侧，于是"人还低着、参考位自己涨上去"
    #   （合成实测：低下去 13.0 s 就掉到阈值以下）。换成**双侧修剪**（= 密度的众数）。
    #   这张表因此从"给短窗项挑搭档"→"挑 X"→**"挑 X 和它的锚点分位 q0"**。
    #   旧口径的行留着当对照（标 `旧`），**它们不许跟着生产改**（`_OLD_*` 那套理由）。
    def trim(win=HEAD_REF_WIN, q0=HEAD_REF_Q, tol=HEAD_DEG, iters=HEAD_REF_ITERS):
        """★ **生产口径（2026-09-26 第四次）**：双侧修剪参考位。

        以 q0 分位为初值，反复丢掉离它超过 `tol` 度的帧，再在内点集上重取 q0 分位
        —— 固定迭代 `iters` 次。**默认参数就是生产常量**（`face.HEAD_REF_*`），所以
        "★生产 修剪"那一行永远等于生产口径，连"记忆" `(1 − q0)·win` 也跟着常量走。
        """
        def f(ts, p):
            out = np.full(len(ts), np.nan)
            for i in range(len(ts)):
                m = (ts >= ts[i] - win) & (ts <= ts[i]) & np.isfinite(p)
                v = p[m]
                if len(v) < 5:                              # noqa: PLR2004
                    continue
                r = float(np.percentile(v, q0))
                for _ in range(iters):
                    k = np.abs(v - r) <= tol
                    if k.sum() < 5:                         # noqa: PLR2004
                        break
                    r = float(np.percentile(v[k], q0))
                out[i] = r
            return out
        return f

    CANDS = (
        ("旧 p25(10s)", q_ref(ROLL_WIN, 25.0)),
        ("旧 +p25(300s)", two(q_ref(ROLL_WIN, 25.0), q_ref(300.0, 25.0))),
        ("旧 +p40(300s)", two(q_ref(ROLL_WIN, 25.0), q_ref(300.0, 40.0))),
        ("旧 +段 20s×5", two(q_ref(ROLL_WIN, 25.0), chunked(20.0, 5))),
        ("旧 段 20s×5", chunked(20.0, 5)),
        ("p25(300s)", q_ref(300.0, 25.0)),
        ("p40(300s)", q_ref(300.0, 40.0)),
        ("段 10s×3", chunked(10.0, 3)),
        ("段 30s×10", chunked(30.0, 10)),
        ("★生产 修剪", trim()),
        ("修剪 100s q35", trim(100.0, 35.0)),
        ("修剪 300s q25", trim(300.0, 25.0)),
        ("修剪 300s q30", trim(300.0, 30.0)),
        ("修剪 300s q40", trim(300.0, 40.0)),
        ("修剪 300s q50", trim(300.0, 50.0)),
    )
    # 每段的长度 / 段数 → **记忆长度**：一次偏移持续到多久，参考位就认它是常态了。
    # 旧口径的推导：一段里被偏移占了 75% 以上，该段的 p25 就塌到偏移那一侧，所以
    #   "还有干净段"能扛 ≈ (K − 0.75)·T 秒。
    # **第四次之后生产用的是修剪**，它的记忆是 `(1 − q0)·win`：偏移占满窗的
    #   (1 − q0) 之后，修剪的**初值**本身就落在偏移里、内点集也只剩偏移 ——
    #   实测见 `_head_ref_cand.py`（b 探针、D 探针）。
    MEMO = {"旧 +段 20s×5": 85.0, "旧 段 20s×5": 85.0,
            "段 10s×3": 22.5, "段 30s×10": 277.5,
            "★生产 修剪": (1.0 - HEAD_REF_Q / 100.0) * HEAD_REF_WIN,
            "修剪 100s q35": 65.0,
            "修剪 300s q25": 225.0, "修剪 300s q30": 210.0,
            "修剪 300s q40": 180.0, "修剪 300s q50": 150.0}
    # ⚠️ 记忆长度只跟**那个抗拖动的项**有关：旧口径里短窗项的记忆是 ROLL_WIN−2.5
    #    ≈ 7.5 秒，它在 `max` 里，于是整条参考位的记忆 = 7.5 秒（分段项那 85 秒被它
    #    盖掉）—— 这就是【8】要量的那件事。**删掉短窗项之后，记忆才真的是 85/195 秒**。

    def real_pitch():
        """用户那场真人会话的 pitch（`runs/_probe_lag_cam.csv`，只取 cam 段）。"""
        path = os.path.join(ROOT, "runs", "_probe_lag_cam.csv")
        if not os.path.exists(path):
            return None, None
        import csv
        with open(path, encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("source") == "cam"]
        ts, ps = [], []
        for r in rows:
            try:
                ts.append(float(r["wall"]))
                ps.append(float(r["pitch"]))
            except (TypeError, ValueError):
                continue
        ts, ps = np.asarray(ts), np.asarray(ps)
        if len(ts) < 20:                                           # noqa: PLR2004
            return None, None
        return ts - ts[0], ps

    def scan(ts, p, ref):
        """滑 2 秒窗，返回逐窗 (t0, hi − ref(窗末))。"""
        rows = []
        t0 = ts[0]
        while t0 + TRAIL <= ts[-1]:
            m = (ts >= t0) & (ts <= t0 + TRAIL) & np.isfinite(p)
            if m.sum() > 5 and np.isfinite(ref[m][-1]):            # noqa: PLR2004
                rows.append((t0, float(np.percentile(p[m], 95)) - float(ref[m][-1])))
            t0 += STEP
        return rows

    lts, lps = real_pitch()
    if lts is not None:
        live_ref = {}
        for name, f in CANDS:
            live_ref[name] = max((v for t0, v in scan(lts, lps, f(lts, lps))
                                  if t0 >= 36.05), default=float("nan"))  # noqa: PLR2004
    else:
        live_ref = {}
    print("\n     %-14s %-9s %-9s %-9s %-9s %-9s %-8s %s"
          % ("参考位口径", "正常", "扭头", "低头", "疲劳", "说话",
             "记忆(秒)", "真人回正之后峰值"))
    for name, f in CANDS:
        hit = {g: [0, 0] for g in GROUPS + EXTRA}
        for k in z.files:
            parts = k.split("|")
            if len(parts) != 3 or parts[2] != "euler":
                continue
            g, clip, _ = parts
            if g not in hit:
                continue
            tk = "%s|%s|t" % (g, clip)
            if tk not in z.files:
                continue
            ts = np.asarray(z[tk], float)
            eu = np.asarray(z[k], float)
            if eu.ndim != 2 or len(ts) < 20:                       # noqa: PLR2004
                continue
            p = eu[:, 0]
            if not np.isfinite(p).any():
                continue
            dE = max((v for _, v in scan(ts, p, f(ts, p))), default=0.0)
            hit[g][1] += 1
            hit[g][0] += dE >= HEAD_DEG
        pk = live_ref.get(name, float("nan"))
        memo = MEMO.get(name)
        ok = "✅" if (hit["normal"][0] == 0 and hit["fatigue"][0] >= 22   # noqa: PLR2004
                      and not (pk >= HEAD_DEG)) else "❌"
        print("     %-14s %-9s %-9s %-9s %-9s %-9s %-8s %+6.2f°  %s"
              % (name, "%d/%d" % tuple(hit["normal"]), "%d/%d" % tuple(hit["glance"]),
                 "%d/%d" % tuple(hit["phone"]), "%d/%d" % tuple(hit["fatigue"]),
                 "%d/%d" % tuple(hit["talking"]),
                 "%.0f" % memo if memo else "—", pk, ok))
    print("     （「记忆」= 一次持续偏移到多久参考位就认它是常态（(K−0.75)·T）；"
          "真人那一列 = 那场 57 秒会话里 t≥36.05 s 的最大 dip，"
          "要 < %.0f° 才不假触发。两关同时过才算 ✅）" % HEAD_DEG)
    # ── 8. 判据会不会**自己松手**（2026-09-26 第四次）────────────────────────
    #    用户原话：「不要多报 我已经说了」「不要锁存」。红线里的锁存去掉之后，
    #    **判据自己撑不撑得住就成了唯一的防线** —— 而第三次那条口径撑不住，两个毛病：
    #      A 人还低着、判据自己松手（低下去 13.0 s 掉到阈值以下）
    #      B 长低头之后再低头报不出来（"低了一分钟的人从此不报低头"）
    #    上一天没发现，是因为【7】那张表的列里**根本没有"持续低头"这一列**。
    #    所以这里用**合成轨迹**（确定、不依赖任何素材、跑一次一秒）。
    print("\n【8】判据会不会自己松手（合成轨迹 8 Hz，噪声 σ=2°，固定种子 20260926）")

    def _synth(segs=None, hz=8.0):
        """`segs` = ((时长秒, pitch 偏移), …)。固定种子：跑几次都一样。"""
        segs = segs or ((60.0, 0.0), (30.0, 25.0), (20.0, 0.0))
        rng = np.random.default_rng(20260926)               # 固定种子：跑几次都一样
        p = np.concatenate([mu + rng.normal(0.0, 2.0, int(d * hz)) for d, mu in segs])
        return np.arange(len(p)) / hz, p

    _A = ((60.0, 0.0), (30.0, 25.0), (20.0, 0.0))                     # 持续低头 30 s
    _B = ((240.0, 0.0), (60.0, 25.0), (60.0, 0.0), (6.0, 25.0), (20.0, 0.0))
    _ROWS = (("旧 max(短窗10s, 段20s×5)",
              two(q_ref(ROLL_WIN, 25.0), chunked(20.0, 5))),
             ("旧 段20s×5（第三次生产）", chunked(20.0, 5)),
             ("★生产 修剪（第四次）", trim()))
    _st, _sp = _synth(_A)
    for _name, _f in _ROWS:
        _rows = [(t0, v) for t0, v in scan(_st, _sp, _f(_st, _sp))
                 if 62.0 <= t0 <= 88.0]        # 掐掉低头头尾各 2 秒（窗起点 ≥ onset+2）
        _v = np.array([v for _, v in _rows])
        _under = [t0 for t0, v in _rows if v < HEAD_DEG]
        print("     A 持续低头 30 s · %-24s dip 最小 %5.1f° 中位 %5.1f°  "
              "掉到 %.0f° 以下：%s"
              % (_name, float(np.min(_v)), float(np.median(_v)), HEAD_DEG,
                 ("t=%.1f s（低下去 **%.1f 秒**之后）" % (_under[0], _under[0] - 60.0))
                 if _under else "**从不** ✅"))
    _bt, _bp = _synth(_B)
    for _name, _f in _ROWS:
        _pk = max((v for t0, v in scan(_bt, _bp, _f(_bt, _bp))
                   if 360.0 <= t0 <= 364.0), default=float("nan"))
        print("     B 长低头60s+回正60s 后再低头 6 s · %-24s 峰值 %5.1f°  %s"
              % (_name, _pk, "✅ 报得出来" if _pk >= HEAD_DEG else "❌ 报不出来"))
    print("     ★ 判据一旦「自己松手」，人还低着屏幕上就已经降级了 —— 这条是"
          "`--head-hold` 锁存**替不了**的（锁存只会让它在降级后多挂几秒，"
          "而这里量的是它**根本抬不起来**）。")

    # 采纳的那一行**必须就是生产口径**。两处实现是各写各的（本表扫参数用的 `trim`、
    # 【6】的 `ref_at`），生产那份在 `src/face.py` —— 真人那场会话上必须给同一串数。
    if lts is not None:
        got = trim()(lts, lps)
        want = np.array([ref_at(lts, lps, float(t)) for t in lts])
        d = np.abs(got - want)
        d = d[np.isfinite(d)]
        print("     采纳口径（★生产 修剪）两处实现互校：本表 vs `ref_at`（=【6】=生产）"
              "最大差 %.2e°（%d 点）"
              % (float(d.max()) if len(d) else float("nan"), len(d)))

    print("\n【5】⚠️ 这条**分不出「低头看仪表」和「低头困了」**：")
    print("     · 判据是「头偏出自己的中性姿态」，所以调一次空调、看一眼中控都算。")
    print("     · 想分开只能靠**时长**（所以上面那张扫描表才是重点）或**节律**")
    print("       （`nod` = 反复偏出中位 → 点头；`d_pitch` 大而 `nod` 低 → 持续低垂）。")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
