"""支路二到底学到了什么？—— 是眼睛，还是只是跟着头动走？

【3】的系数里"眨眼频率"权重最大（+0.996），fatigue 组 34 次/分 vs normal 7.9。
但 fatigue 段是**点头**录的。两种可能：

  A. 真眼动 —— 疲劳时眨眼确实变多变快，这是文献里的 drowsiness 早期征象
  B. 假信号 —— 头在动 → landmark 抖 → EAR 反复穿越阈值 → 数出一堆"眨眼"

分不清就不知道支路二有没有独立价值（B = 它只是支路一的影子）。

判法两条：
  D1  跨片段 r(眨眼频率, pitch范围)。强正 = 眨眼频率只是头动的代理量
  D2  **只留头不动的片段**，再比 fatigue vs normal。
      如果头不动时两组仍然分得开 → A（真的是眼睛）
      如果分不开 → B（全是头动）
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "_scratch" / "_ear_raw.npz"
FPS, ROLL_WIN, BLINK_THR = 15.0, 10.0, 0.84
YAWN_THR, YAWN_MIN = 0.60, 1.5
NOD_DROP, NOD_MIN = 12.0, 0.5

z = np.load(CACHE, allow_pickle=True)
files = set(z.files)
keys = sorted({k.rsplit("|", 1)[0] for k in files})
get = lambda k, f: z[f"{k}|{f}"] if f"{k}|{f}" in files else None
grp = lambda g: [k for k in keys if k.startswith(g + "|")]


def roll_med(e, w):
    n = len(e)
    half = max(2, int(w * FPS) // 2)
    i = np.arange(n)
    lo, hi = np.maximum(0, i - half), np.minimum(n, i + half + 1)
    return np.array([np.median(e[a:b]) for a, b in zip(lo, hi)])


def runs(x, f):
    out, cur = [], 0
    for v in x:
        if f(v):
            cur += 1
        elif cur:
            out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


rows = []
for g in ("normal", "glance", "phone", "fatigue"):
    for k in grp(g):
        e, eu = get(k, "ear"), get(k, "euler")
        if eu is None or len(eu) != len(e):
            continue
        m = np.isfinite(e) & np.isfinite(eu[:, 0])
        e, eu = e[m], eu[m]
        if len(e) < 60:
            continue
        en = e / np.maximum(roll_med(e, ROLL_WIN), 1e-6)
        dur = len(e) / FPS
        pr = eu[:, 0]
        rows.append(dict(
            grp=g, name=k.split("|")[1], dur=dur,
            perclos=float((en < BLINK_THR).mean()),
            blink=len(runs(en, lambda v: v < BLINK_THR)) / dur * 60,
            pitch_range=float(np.percentile(pr, 95) - np.percentile(pr, 5)),
            pitch_std=float(np.std(pr)),
            yaw_std=float(np.std(eu[:, 1])),
        ))

D = {r["name"]: r for r in rows}
G = lambda g: [r for r in rows if r["grp"] == g]
print(f"片段 {len(rows)} 段\n")

print("【D1】眨眼频率 是不是只是「头在动」的代理量？")
print(f"\n{'对照量':<14}{'r(眨眼频率, ·)':>17}{'r(PERCLOS, ·)':>16}")
print("-" * 48)
bl = np.array([r["blink"] for r in rows])
pc = np.array([r["perclos"] for r in rows])
for f in ("pitch_range", "pitch_std", "yaw_std"):
    v = np.array([r[f] for r in rows])
    print(f"{f:<14}{np.corrcoef(bl, v)[0,1]:>+17.2f}"
          f"{np.corrcoef(pc, v)[0,1]:>+16.2f}")
print("\n   ↑ 强正说明这两个'眼睛指标'其实在跟着头动走")

print("\n【D2】只留头不动的片段，fatigue 还分得开吗？")
for lim, tag in ((6.0, "头动 < 6°（基本没动）"),
                 (10.0, "头动 < 10°"),
                 (99.0, "全部")):
    sel = [r for r in rows if r["pitch_range"] < lim]
    sub = {}
    for g in ("normal", "glance", "phone", "fatigue"):
        v = [r for r in sel if r["grp"] == g]
        if len(v) >= 3:
            sub[g] = (len(v), np.median([r["perclos"] for r in v]),
                      np.median([r["blink"] for r in v]))
    if "fatigue" not in sub or "normal" not in sub:
        print(f"\n   {tag}：样本不足（疲劳 {len([r for r in sel if r['grp']=='fatigue'])}，"
              f"正常 {len([r for r in sel if r['grp']=='normal'])}）")
        continue
    print(f"\n   {tag}")
    print(f"     {'组':<9}{'段数':>5}{'PERCLOS':>10}{'眨眼/分':>10}")
    for g, (n, p, b) in sub.items():
        print(f"     {g:<9}{n:>5}{p:>10.3f}{b:>10.1f}")
    rp = sub["fatigue"][1] / max(1e-6, sub["normal"][1])
    rb = sub["fatigue"][2] / max(1e-6, sub["normal"][2])
    print(f"     疲劳/正常 倍数:  PERCLOS {rp:.1f}x   眨眼频率 {rb:.1f}x")

print("\n【D3】头动最小的那些片段，逐段看看")
print(f"\n{'片段':<16}{'头动范围':>10}{'PERCLOS':>10}{'眨眼/分':>10}{'时长':>8}")
print("-" * 56)
for r in sorted([r for r in rows if r["grp"] in ("fatigue", "normal")],
                key=lambda r: r["pitch_range"])[:16]:
    print(f"{r['name']:<16}{r['pitch_range']:>10.1f}{r['perclos']:>10.3f}"
          f"{r['blink']:>10.1f}{r['dur']:>8.1f}")

sys.stdout.flush()
