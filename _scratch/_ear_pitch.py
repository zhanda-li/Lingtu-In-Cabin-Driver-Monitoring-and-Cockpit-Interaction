"""排查混淆：fatigue 段的 EAR 偏低，是真的眼睑下垂，还是低头压扁了 landmark？

Q1b 的直方图显示 fatigue 的 EAR 分布整体左移（峰值 0.22~0.26 vs normal 0.34~0.36）。
这可能是：
  A. 真信号 —— 疲劳的人眼睑下垂、眯眼，EAR 本来就低。那就直接能用。
  B. 假信号 —— fatigue 段是"点头"录的，低头时眼周点被压扁，EAR 假性降低。

分不清就建在沙子上。

判法（按 pitch 分层对比）：
  把两组的帧都按头部 pitch 分箱。同一个 pitch 箱里，如果 fatigue 的 EAR
  仍然低于 normal，那和头姿无关，是 A。
  如果分层后差距消失，那就是 B。

另外看段内 r(EAR, pitch) —— 同一段里头一低 EAR 就掉，说明是几何伪影。
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "_scratch" / "_ear_raw.npz"

z = np.load(CACHE, allow_pickle=True)
files = set(z.files)
keys = sorted({k.rsplit("|", 1)[0] for k in files})


def get(key, field):
    k = f"{key}|{field}"
    return z[k] if k in files else None


print("【1】段级：EAR 中位 vs pitch 中位")
print(f"{'组':<9}{'段数':>5}{'EAR中位':>9}{'pitch中位':>11}{'pitch范围':>18}")
print("-" * 54)
for g in ("normal", "fatigue", "yawn", "talking"):
    es, ps, prs = [], [], []
    for k in keys:
        if not k.startswith(g + "|"):
            continue
        e = get(k, "ear")
        eu = get(k, "euler")
        if eu is None or len(eu) != len(e):
            continue
        es.append(np.median(e))
        ps.append(np.median(eu[:, 0]))
        prs.append((np.percentile(eu[:, 0], 5), np.percentile(eu[:, 0], 95)))
    if es:
        lo = min(p[0] for p in prs)
        hi = max(p[1] for p in prs)
        print(f"{g:<9}{len(es):>5}{np.median(es):>9.3f}{np.median(ps):>11.1f}"
              f"{f'[{lo:.1f}, {hi:.1f}]':>18}")

# ── 段内相关：头一低 EAR 就掉吗 ──────────────────────────────────────
print("\n【2】段内 r(EAR, pitch)。负得多 = 低头时 EAR 假性下降（几何伪影）")
for g in ("normal", "fatigue"):
    rs = []
    for k in keys:
        if not k.startswith(g + "|"):
            continue
        e, eu = get(k, "ear"), get(k, "euler")
        if eu is None or len(eu) != len(e):
            continue
        if np.std(e) < 1e-6 or np.std(eu[:, 0]) < 1e-6:
            continue
        rs.append(float(np.corrcoef(e, eu[:, 0])[0, 1]))
    if rs:
        print(f"   {g:<9} 段内 r 中位 {np.median(rs):+.2f}   "
              f"（{sum(1 for r in rs if r < -0.5)}/{len(rs)} 段强负）")

# ── 决定性检验：按 pitch 分层 ────────────────────────────────────────
print("\n【3】按 pitch 分层 —— 同一个头姿下，fatigue 的 EAR 还低吗？")
print("     分层后差距还在 = 真信号(A)；消失 = 头姿伪影(B)\n")
bins = [(-40, -20), (-20, -10), (-10, -5), (-5, 0), (0, 5), (5, 10),
        (10, 20), (20, 40)]
print(f"{'pitch 区间':>14}{'normal EAR':>13}{'n':>7}{'fatigue EAR':>14}{'n':>7}"
      f"{'差':>9}")
print("-" * 66)
for lo, hi in bins:
    row = []
    for g in ("normal", "fatigue"):
        vs = []
        for k in keys:
            if not k.startswith(g + "|"):
                continue
            e, eu = get(k, "ear"), get(k, "euler")
            if eu is None or len(eu) != len(e):
                continue
            m = (eu[:, 0] >= lo) & (eu[:, 0] < hi)
            if m.any():
                vs.append(e[m])
        row.append(np.concatenate(vs) if vs else np.array([]))
    if len(row[0]) >= 30 and len(row[1]) >= 30:
        a, b = np.median(row[0]), np.median(row[1])
        print(f"{f'[{lo}, {hi})':>14}{a:>13.3f}{len(row[0]):>7}"
              f"{b:>14.3f}{len(row[1]):>7}{b - a:>+9.3f}")
    else:
        print(f"{f'[{lo}, {hi})':>14}{'':>13}{len(row[0]):>7}"
              f"{'':>14}{len(row[1]):>7}   样本不足")

sys.stdout.flush()
