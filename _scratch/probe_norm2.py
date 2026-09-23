"""换一种归一化：逐段滚动中位基线。

上一版（全局 pitch 多项式）失败，原因写在 probe_norm.py：
同一个 pitch 下不同片段的差异比 pitch 本身的影响更大，
一个全局函数拟合不了。

滚动中位基线的道理：
  眨眼只占 ~4% 的帧，所以「最近 N 秒的 EAR 中位数」≈ 这段时间眼睛睁开时的 EAR。
  低头、眼镜滑、距离变化 —— 这些都是**缓慢漂移**，中位数跟着走，比值不变。
  真闭眼是**快事件**，中位数还没反应过来，比值就掉下去了。

  EAR_norm(t) = EAR(t) / median(EAR[t-N/2 : t+N/2])

校准方式（三个方法用同一把尺子，才好比）：
  每个方法都把阈值调到「正常段闭眼占比 = 5%」（生理值约 4~5%），
  然后看谁在 phone / glance 上的假闭眼最少。
  如果某个方法要靠一个很低的阈值才能压到 5%，那它本身就是坏的。
"""
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "_scratch" / "_ear_raw.npz"
FPS = 15.0

z = np.load(CACHE, allow_pickle=True)
files = set(z.files)
keys = sorted({k.rsplit("|", 1)[0] for k in files})


def get(key, field):
    k = f"{key}|{field}"
    return z[k] if k in files else None


def grp(g):
    return [k for k in keys if k.startswith(g + "|")]


def aligned(key):
    e, eu = get(key, "ear"), get(key, "euler")
    if eu is None or len(eu) != len(e):
        return None, None
    m = np.isfinite(e) & np.isfinite(eu[:, 0])
    return e[m], eu[m, 0]


def roll_med(e, win_sec):
    n = len(e)
    half = max(2, int(win_sec * FPS) // 2)
    idx = np.arange(n)
    lo = np.maximum(0, idx - half)
    hi = np.minimum(n, idx + half + 1)
    # 前缀和技巧做不了中位，n 不大，直接循环
    return np.array([np.median(e[a:b]) for a, b in zip(lo, hi)])


METHODS = {
    "原始 EAR": lambda e, p: e,
    "滚动中位 5s": lambda e, p: e / np.maximum(roll_med(e, 5), 1e-6),
    "滚动中位 10s": lambda e, p: e / np.maximum(roll_med(e, 10), 1e-6),
    "滚动中位 20s": lambda e, p: e / np.maximum(roll_med(e, 20), 1e-6),
    "10s + pitch 残差": None,      # 占位，下面填
}


def runs_below(x, thr):
    out, cur = [], 0
    for v in x:
        if np.isfinite(v) and v < thr:
            cur += 1
        elif cur:
            out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


GROUPS = ("normal", "fatigue", "glance", "phone", "yawn", "talking")
# 预算好每组每段的信号，避免反复算
SIG = {}
for g in GROUPS:
    for k in grp(g):
        e, p = aligned(k)
        if e is None or len(e) < 30:
            continue
        SIG[k] = (g, e, p, len(e) / FPS)

print(f"可用片段 {len(SIG)} 段\n")

# ── 校准：正常段闭眼占比打到 5% ──────────────────────────────────────
CAL = 0.05
print("【1】把每个方法的阈值校准到「正常段闭眼占比 = 5%」")
print(f"\n{'方法':<18}{'阈值':>9}{'正常段闭眼%':>14}{'正常段眨眼/分':>16}")
print("-" * 58)
thr_of = {}
for name, fn in METHODS.items():
    if fn is None:
        continue
    sigs = {k: fn(v[1], v[2]) for k, v in SIG.items()}
    grid = np.round(np.arange(0.30, 0.98, 0.01), 2)
    best, bt = None, None
    for t in grid:
        tot = sum(np.sum(s < t) for k, s in sigs.items()
                  if SIG[k][0] == "normal")
        nf = sum(len(s) for k, s in sigs.items() if SIG[k][0] == "normal")
        frac = tot / max(1, nf)
        if best is None or abs(frac - CAL) < abs(best - CAL):
            best, bt = frac, t
    thr_of[name] = bt
    n_bl = sum(len(runs_below(s, bt)) for k, s in sigs.items()
               if SIG[k][0] == "normal")
    dur = sum(SIG[k][3] for k in SIG if SIG[k][0] == "normal")
    print(f"{name:<18}{bt:>9.2f}{100*best:>13.1f}%{n_bl/(dur/60):>16.1f}")

# ── 各组表现 ──────────────────────────────────────────────────────────
print("\n\n【2】同一把尺子下，各组表现")
print("     正常段被校准到 5%，所以看的是**别组**有没有被误伤\n")
hdr = (f"{'方法':<18}{'组':>9}{'段数':>6}{'闭眼%':>9}"
       f"{'最长(s)':>9}{'中位最长(s)':>13}")
print(hdr)
print("-" * len(hdr))
for name, fn in METHODS.items():
    if fn is None:
        continue
    t = thr_of[name]
    for g in GROUPS:
        ss = [(fn(v[1], v[2]), v[3]) for v in SIG.values() if v[0] == g]
        if not ss:
            continue
        fr = np.mean([np.sum(s < t) / len(s) for s, _ in ss])
        mx = max([max(runs_below(s, t) or [0]) / FPS for s, _ in ss])
        md = np.median([max(runs_below(s, t) or [0]) / FPS for s, _ in ss])
        flag = ""
        if g == "normal":
            flag = "  ← 校准目标"
        elif md > 1.0:
            flag = "  ⚠️ 中位就超过 1 秒 = 假闭眼"
        print(f"{name:<18}{g:>9}{len(ss):>6}{100*fr:>8.1f}%"
              f"{mx:>9.2f}{md:>13.2f}{flag}")
    print()

sys.stdout.flush()
os._exit(0)
