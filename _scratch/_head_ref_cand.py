# -*- coding: utf-8 -*-
"""参考位口径的**候选评估**（2026-09-26 第四次）—— 把"判据自己松不松手"也量进去。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_head_ref_cand.py

为什么又开一个脚本：`_calib_head_down.py` 的【7】量的是"参考位会不会被**一次短偏移**
（仰头）拖走"，它**没有一列**量"**持续**低头期间判据会不会自己松手"。上一天那个 bug
就是从这列的缺口里漏过去的 —— 而这两个方向**要相反的合并规则**：

  · `max(各段 p25)`：干净段更高，`max` 取它 → **抗仰头** ✅；低头把最近那段拖**高**，
    `max` 取高的 → **低头期间自己松手** ❌（实测：低下去 13.0 s 就掉到 10° 以下，
    而且那之后 ~95 s 里再来一次低头也报不出来，B 行只有 5.2°）。
  · `p25(长窗)`：低的那一侧天生被仰头拽走 → **假触发** ❌（表里对照行 +20.9°）。
  · **只有一个估计量能同时抗两侧：双侧修剪**（= 密度的众数）。参考位是"这个人的
    平视位"，仰头和低头**都是偏离**，所以"离当前估计超过一个阈值的帧不算数"这条
    对两侧是对称的。

⚠️ 这里扫的是**锚点分位 q0**：修剪要有个初值，而初值越低越抗低头、越容易被仰头拽走。
   q0=25 抗仰头 25%、抗低头 75%；q0=35 → 35% / 65%（更平衡，对 ≤27 s 的片段友好）。
   迭代 3 次之后，最终那个值是在"内点集"里取的 q0 分位，所以整体略偏低（偏敏感）。

⚠️ 只用 `_ear_raw.npz`（片段）+ 合成轨迹 + 真人 `runs/_probe_lag_cam.csv`；
   本脚本**只读**，不碰摄像头，跑完 `os._exit(0)`（mediapipe 那 42 秒）。

⚠️ 判据 `dip = p95(最近 2 s) − ref` 与生产/`_calib_head_down.py` 同款（`scan`）。
"""
import csv
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))
sys.path.insert(0, HERE)
from face import (HEAD_DEG, HEAD_REF_CHUNK, HEAD_REF_Q,  # noqa: E402
                  norm_by_time)

CACHE = os.path.join(HERE, "_ear_raw.npz")
GROUPS = ("normal", "glance", "phone", "fatigue", "talking")
TRAIL, STEP = 2.0, 0.2      # 判据窗 2 s（= face.HEAD_WIN）；滑窗步长 0.2 s


# ─────────────────────────── 候选口径 ───────────────────────────
def ref_chunkmax(T=HEAD_REF_CHUNK, K=5, q=HEAD_REF_Q):
    """现状（2026-09-26 第三次）：历史切 K 段、各段 p25、**取最高**。抗仰头，不抗低头。"""
    def f(ts, p):
        out = np.full(len(ts), np.nan)
        for i in range(len(ts)):
            best = np.nan
            for k in range(K):
                hi = ts[i] - k * T
                m = (ts >= hi - T) & (ts <= hi) & np.isfinite(p)
                if m.sum() >= 5:                       # noqa: PLR2004
                    v = float(np.percentile(p[m], q))
                    best = v if not np.isfinite(best) else max(best, v)
            out[i] = best
        return out
    return f


def ref_trimq(win=300.0, q0=35.0, tol=HEAD_DEG, iters=3):
    """**双侧修剪**参考位：以 q0 分位为初值，反复丢掉离它 `tol` 度以外的帧。

    为什么必须双侧（这段是这次的核心，别简化成单侧）：参考位 = 这个人的**平视位**，
    而仰头和低头都是偏离。单侧分位天生只抗一个方向（`p25` 抗低头、被仰头拽走），
    `max(各段)` 反过来。"离当前估计太远就不算数"**对两侧对称** —— 一次持续偏移
    只要没占满窗口的大半（初值才不会被它拽走），就会被剔掉。

    记忆 = 偏移占到 (1 − q0) 的窗口时长为止（q0=35、win=300 s → 195 s），比任何
    真实偏移都长得多，而且是**有意的**：那种"一直低着"的姿态本来就该一直报。
    """
    def f(ts, p):
        out = np.full(len(ts), np.nan)
        for i in range(len(ts)):
            m = (ts >= ts[i] - win) & (ts <= ts[i]) & np.isfinite(p)
            v = p[m]
            if len(v) < 5:                             # noqa: PLR2004
                continue
            r = float(np.percentile(v, q0))
            for _ in range(iters):
                k = np.abs(v - r) <= tol
                if k.sum() < 5:                        # noqa: PLR2004
                    break
                r = float(np.percentile(v[k], q0))
            out[i] = r
        return out
    return f


def ref_p25(win=300.0, q=HEAD_REF_Q):
    """单侧长窗分位（**已知在仰头上翻车**，留一行当对照，别选它）。"""
    return lambda ts, p: norm_by_time(ts, p, win, q=q)


# ─────────────────────────── 量法 ───────────────────────────
def scan(ts, p, ref):
    """滑 2 秒窗，返回逐窗 (t0, dip)。与 `_calib_head_down.py` 同款。"""
    rows = []
    t0 = float(ts[0])
    while t0 + TRAIL <= ts[-1]:
        m = (ts >= t0) & (ts <= t0 + TRAIL) & np.isfinite(p)
        if m.sum() > 5 and np.isfinite(ref[m][-1]):    # noqa: PLR2004
            rows.append((t0, float(np.percentile(p[m], 95)) - float(ref[m][-1])))
        t0 += STEP
    return rows


def syn(segs, hz=8.0, seed=20260926):
    """合成轨迹：segs = ((时长, pitch), …)。固定种子，跑几次都一样。"""
    rng = np.random.default_rng(seed)
    p = np.concatenate([mu + rng.normal(0.0, 2.0, int(d * hz)) for d, mu in segs])
    return np.arange(len(p)) / hz, p


def probe(ts, p, ref_fn, a, b, mode):
    """在合成轨迹的 [a,b] 段里量 dip（`a`/`b` 是**段**的起止；`t0` 是窗**起点**）。

    ⚠️ `t0` 是 2 秒窗的**起点**（`scan` 的窗是 [t0, t0+TRAIL]），所以上界要减 TRAIL ——
       我第一版写成 `a + TRAIL <= t0`，于是每个"段"的最后一行量到的是**跨界那一窗**
       （低头结束/回正开始），四条探针全部假绿/假红。
    mode: `hold` = 持续偏移期间**掉不掉**（想要：从不掉）；`hit` = 该报的报得出来吗
          （想要：≥ 阈值）；`quiet` = 不该报的安静吗（想要：< 阈值）。
    """
    rows = [(t0, v) for t0, v in scan(ts, p, ref_fn(ts, p))
            if a <= t0 <= b - TRAIL]
    if not rows:
        return "没量到"
    v = np.array([x for _, x in rows])
    if mode == "hold":
        under = [t0 for t0, x in rows if x < HEAD_DEG]
        if not under:
            return "**从不掉** ✅"
        return "低下去 %3.1f s 就掉 ❌" % (under[0] - a)
    if mode == "hit":
        return "%5.1f°%s" % (float(v.max()),
                             " ✅" if v.max() >= HEAD_DEG else " ❌")
    return "%5.1f°%s" % (float(v.max()), " ✅" if v.max() < HEAD_DEG else " ❌")


def main():
    # A：持续低头 30 s（想要：整段不掉）
    # B：长低头 60 s → 回正 60 s → 再低头 6 s（想要：报得出来）
    # C：一次 11 s 仰头 → 回正 40 s（想要：不假报）—— ①已经修好的那个
    # D：长仰头 60 s → 回正 60 s → 再低头 6 s（想要：报得出来）
    # ⚠️ B/D 的**前置直立段放到 240 s**，好让 `win` 真的分得出 100/200/300 ——
    #    第一版前置只有 60 s，比所有窗都短，于是三档窗量出来一模一样（假平）。
    P_DOWN = ((60, 0.0), (30, 25.0), (20, 0.0))
    P_LONG_D = ((240, 0.0), (60, 25.0), (60, 0.0), (6, 25.0), (20, 0.0))
    P_UP = ((60, 0.0), (11, -20.0), (40, 0.0))
    P_LONG_U = ((240, 0.0), (60, -20.0), (60, 0.0), (6, 25.0), (20, 0.0))
    SYN = ((P_DOWN, 60.0, 90.0, "hold"),
           (P_LONG_D, 360.0, 366.0, "hit"),
           (P_UP, 71.0, 111.0, "quiet"),
           (P_LONG_U, 360.0, 366.0, "hit"))

    live = os.path.join(ROOT, "runs", "_probe_lag_cam.csv")
    lts = lps = None
    if os.path.exists(live):
        with open(live, encoding="utf-8") as fh:
            rows = [r for r in csv.DictReader(fh) if r.get("source") == "cam"]
        a, b = [], []
        for r in rows:
            try:
                a.append(float(r["wall"]))
                b.append(float(r["pitch"]))
            except (TypeError, ValueError):
                continue
        if len(a) >= 20:                                          # noqa: PLR2004
            lts, lps = np.asarray(a) - a[0], np.asarray(b)

    CANDS = [("现状 段20s×5 取max", ref_chunkmax()), ("p25(300s) 对照", ref_p25(300.0))]
    for q0 in (25.0, 30.0, 35.0, 40.0, 50.0):
        for win in (100.0, 200.0, 300.0):
            CANDS.append(("修剪 %3.0fs q%02.0f" % (win, q0), ref_trimq(win, q0)))

    z = np.load(CACHE, allow_pickle=True)
    # 先把片段摊平成数组，别在候选循环里反复解 npz
    clips = []
    for k in z.files:
        parts = k.split("|")
        if len(parts) != 3 or parts[2] != "euler" or parts[0] not in GROUPS:
            continue
        tk = "%s|%s|t" % (parts[0], parts[1])
        if tk not in z.files:
            continue
        ts = np.asarray(z[tk], float)
        eu = np.asarray(z[k], float)
        if eu.ndim != 2 or len(ts) < 20 or not np.isfinite(eu[:, 0]).any():
            continue
        clips.append((parts[0], ts, eu[:, 0]))
    print("参考位候选评估（dip = p95(最近 2 s) − ref；阈值 %.0f°；%d 个片段）"
          % (HEAD_DEG, len(clips)))
    print("  片段列：疲劳要 ≥22/26（别把真低头修没）、正常必须 0/27；"
          "A/B/D 不能有 ❌，C 是①修好的那个，别修回去。\n")
    print("  %-18s %-6s %-6s %-6s %-6s %-6s %-8s %-16s %-10s %-10s %s"
          % ("口径", "正常", "扭头", "低头", "疲劳", "说话", "真人回正",
             "A 持续低头30s", "B 再低头", "C 回正假报", "D 长仰头后再低头"))
    print("  %-18s %-6s %-6s %-6s %-6s %-6s %-8s %-16s %-10s %-10s %s"
          % ("", "", "", "", "", "", "要 <10°", "要从不掉", "要 ≥10°",
             "要 <10°", "要 ≥10°"))

    for name, f in CANDS:
        hit = {g: [0, 0] for g in GROUPS}
        for g, ts, p in clips:
            d = max((v for _, v in scan(ts, p, f(ts, p))), default=0.0)
            hit[g][1] += 1
            hit[g][0] += d >= HEAD_DEG
        pk = float("nan")
        if lts is not None:
            pk = max((v for t0, v in scan(lts, lps, f(lts, lps))
                      if t0 >= 36.05), default=float("nan"))      # noqa: PLR2004
        cells = [probe(*syn(segs), f, a, b, m) for segs, a, b, m in SYN]
        ok = (hit["normal"][0] == 0 and hit["fatigue"][0] >= 22    # noqa: PLR2004
              and (not np.isfinite(pk) or pk < HEAD_DEG)
              and "❌" not in "".join(cells))
        print("  %-18s %-6s %-6s %-6s %-6s %-6s %+6.1f°%s %-18s %-9s %-8s %s  %s"
              % (name, "%d/%d" % tuple(hit["normal"]),
                 "%d/%d" % tuple(hit["glance"]), "%d/%d" % tuple(hit["phone"]),
                 "%d/%d" % tuple(hit["fatigue"]), "%d/%d" % tuple(hit["talking"]),
                 pk, "✅" if pk < HEAD_DEG else "❌", *cells,
                 "✅" if ok else "❌"))

    sys.stdout.flush()
    os._exit(0)          # ⚠️ 不刷缓冲就退出 = 整份输出凭空消失（退码还是 0）


if __name__ == "__main__":
    main()
