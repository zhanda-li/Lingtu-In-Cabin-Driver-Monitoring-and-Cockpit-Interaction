"""头姿归一化 EAR —— 修掉"低头 = 假闭眼"这个病。

上一轮量到：17° 的头姿变化 = 一次眨眼的 EAR 幅度，而点头有 20~30°。
固定阈值必然把点头读成闭眼。这也是昨晚 glance_15 的 eyeBlink 冲到 0.959 的原因。

做法：
  EAR_norm = EAR / baseline(pitch)
  baseline(pitch) = 这个头姿下"眼睛完全睁开"时 EAR 是多少

  拟合 baseline 的三个讲究：
    1. 用 **p90** 不用均值 —— 眨眼只占 ~4% 帧，均值会被拉低
    2. 只用 normal/glance/phone 拟合，**排除 fatigue** —— 疲劳的人眼睛可能真垂，
       算进去就把要检测的东西当成了基线
    3. 按 pitch 分箱再拟合，不是全局一个常数

  EAR_norm ≈ 1.0 = 眼睛全睁；往下掉 = 在闭。

验证（都要和"归一化前"对比才有意义）：
  V1  眨眼频率是否落进生理范围 15~20 次/分
  V2  分心段（glance/phone）的**假闭眼**有没有消失
  V3  疲劳段的闭眼有没有被误杀
"""
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "_scratch" / "_ear_raw.npz"
TARGET_FPS = 15.0

z = np.load(CACHE, allow_pickle=True)
files = set(z.files)
keys = sorted({k.rsplit("|", 1)[0] for k in files})


def get(key, field):
    k = f"{key}|{field}"
    return z[k] if k in files else None


def grp(g):
    return [k for k in keys if k.startswith(g + "|")]


def aligned(key):
    """ear 和 euler 必须逐帧对齐，对不上就丢（说明有些帧没输出变换矩阵）"""
    e, eu = get(key, "ear"), get(key, "euler")
    if eu is None or len(eu) != len(e):
        return None, None
    m = np.isfinite(e) & np.isfinite(eu[:, 0])
    return e[m], eu[m, 0]


# ── 拟合睁眼基线 ──────────────────────────────────────────────────────
FIT_GROUPS = ("normal", "glance", "phone")
X, Y = [], []
for g in FIT_GROUPS:
    for k in grp(g):
        e, p = aligned(k)
        if e is not None:
            X.append(p)
            Y.append(e)
X, Y = np.concatenate(X), np.concatenate(Y)

edges = np.arange(-25, 45, 5)
px, py, pn = [], [], []
for lo, hi in zip(edges[:-1], edges[1:]):
    s = (X >= lo) & (X < hi)
    if s.sum() >= 150:
        px.append(0.5 * (lo + hi))
        py.append(np.percentile(Y[s], 90))
        pn.append(int(s.sum()))
px, py = np.array(px), np.array(py)

print("【0】睁眼基线（pitch 分箱的 p90）")
print(f"     拟合用的组: {', '.join(FIT_GROUPS)}   "
      f"pitch 覆盖 [{X.min():.1f}, {X.max():.1f}]°")
print(f"\n{'pitch':>8}{'睁眼EAR(p90)':>14}{'帧数':>9}")
print("-" * 32)
for a, b, n in zip(px, py, pn):
    print(f"{a:>8.1f}{b:>14.3f}{n:>9}")

deg = 2 if len(px) >= 6 else 1
coef = np.polyfit(px, py, deg)
fit = np.polyval(coef, px)
r2 = 1 - np.sum((py - fit) ** 2) / max(1e-9, np.sum((py - py.mean()) ** 2))
print(f"\n     拟合 {deg} 次多项式，R² = {r2:.3f}")
print(f"     EAR_睁眼(pitch) = " + " + ".join(
    f"{c:+.5f}·p^{i}" for i, c in enumerate(coef[::-1])))

LOP, HIP = float(px.min()), float(px.max())


def base(p):
    """基线。超出拟合范围就截住，不外推。"""
    return np.polyval(coef, np.clip(p, LOP, HIP))


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


# ── V1 眨眼频率 ───────────────────────────────────────────────────────
print("\n\n【V1】眨眼频率 —— 归一化前 vs 后（生理值 15~20 次/分）")
nev = grp("normal")
dur = sum(float(get(k, "t")[-1] - get(k, "t")[0]) for k in nev)
lo_ok, hi_ok = 15 * dur / 60, 20 * dur / 60
print(f"     27 段 normal，总时长 {dur/60:.1f} 分钟，"
      f"应出现 {lo_ok:.0f}~{hi_ok:.0f} 次\n")
print(f"{'EAR_norm 阈值':>14}{'次数':>8}{'次/分':>9}{'闭眼占比':>11}"
      f"{'   ← 归一化后':<12}")
print("-" * 46)
for thr in np.round(np.arange(0.45, 0.96, 0.05), 2):
    tot, fr, nf = 0, 0, 0
    for k in nev:
        e, p = aligned(k)
        if e is None:
            continue
        en = e / base(p)
        tot += len(runs_below(en, thr))
        fr += int(np.sum(en < thr))
        nf += len(en)
    pm = tot / (dur / 60)
    ok = "✅" if lo_ok * 0.75 <= tot <= hi_ok * 1.35 else (
        "← 少" if tot < lo_ok else "← 多")
    print(f"{thr:>14.2f}{tot:>8}{pm:>9.1f}{100*fr/max(1,nf):>10.1f}%   {ok}")


# ── V2/V3 假闭眼 ──────────────────────────────────────────────────────
def closure_stats(thr_raw, thr_norm):
    """每组的"最长闭眼"，归一化前用 thr_raw，归一化后用 thr_norm"""
    out = {}
    for g in ("normal", "fatigue", "glance", "phone", "yawn", "talking"):
        raw, nrm = [], []
        for k in grp(g):
            e, p = aligned(k)
            if e is None:
                continue
            raw.append(max(runs_below(e, thr_raw) or [0]) / TARGET_FPS)
            nrm.append(max(runs_below(e / base(p), thr_norm) or [0]) / TARGET_FPS)
        if raw:
            out[g] = (np.median(raw), max(raw), np.median(nrm), max(nrm))
    return out


print("\n\n【V2/V3】各组最长闭眼 —— 归一化前 vs 后")
print("      归一化前 0.32 是上一轮实测的眨眼阈值；归一化后用同口径选的最新值")
print(f"\n{'组':>9}{'段数':>6}{'前·中位':>10}{'前·最长':>10}"
      f"{'后·中位':>10}{'后·最长':>10}{'变化':>10}")
print("-" * 66)
st = closure_stats(0.32, 0.80)
for g, (m0, x0, m1, x1) in st.items():
    print(f"{g:>9}{len(grp(g)):>6}{m0:>10.2f}{x0:>10.2f}"
          f"{m1:>10.2f}{x1:>10.2f}{x1 - x0:>+10.2f}")
print("\n   分心段（glance/phone）的'假闭眼'如果被压下去，说明头姿这一关过了。")

sys.stdout.flush()
os._exit(0)
