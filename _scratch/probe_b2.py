"""支路二本体：4 个滑窗统计量 → 逻辑回归。

特征（全部是**率/占比**，不是计数 —— 片段长短不一，计数不可比）：
  1. PERCLOS        闭眼帧占比          （头姿归一化后的 EAR）
  2. 眨眼频率        次/分
  3. 哈欠频率        次/分              （MAR 持续张开）
  4. 点头频率        次/分              （pitch 相对本段"抬头位"的下探）

标签：疲劳 = 1，其余（normal/glance/phone）= 0
      —— 支路二只回答"眼睛和嘴累不累"，分心交给支路一。

为什么不用 4 类：glance/phone 在眼睛和嘴的统计量上和 normal 几乎一样，
硬训会学到"转头导致 landmark 扭曲"这个假信号。详见对话记录。

两件事必须做，否则结论读不出来：
  · 留一交叉验证（106 段，样本少）
  · 置换检验（4 维 / 106 段，逻辑回归靠噪声也能到 70%+）
"""
import os
import sys
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "_scratch" / "_ear_raw.npz"
FPS = 15.0

# 归一化：逐段滚动中位基线。见 probe_norm2.py 的对比 ——
# 全局 pitch 基线失败（同 pitch 下片间差异比 pitch 影响还大），
# 滚动中位把 phone 的假闭眼从 60.8% 打到 2.3%。
ROLL_WIN = 10.0
BLINK_THR = 0.84        # 校准到「正常段闭眼占比 5%」得到的阈值
YAWN_THR = 0.60         # MAR 高于它算张嘴
YAWN_MIN = 1.5          # 且持续这么久才算哈欠（说话最长 1.13s，留余量）
NOD_DROP = 12.0         # 相对本段"抬头位"下探多少度算一次点头
NOD_MIN = 0.5

z = np.load(CACHE, allow_pickle=True)
files = set(z.files)
keys = sorted({k.rsplit("|", 1)[0] for k in files})


def get(key, field):
    k = f"{key}|{field}"
    return z[k] if k in files else None


def grp(g):
    return [k for k in keys if k.startswith(g + "|")]


def aligned(key, fields=("ear", "euler")):
    a = get(key, fields[0])
    b = get(key, fields[1])
    if a is None or b is None or len(a) != len(b):
        return None
    m = np.isfinite(a) & np.isfinite(b if b.ndim == 1 else b[:, 0])
    return (a[m], b[m]) if m.any() else None


def roll_med(e, win_sec):
    """最近 win_sec 秒的 EAR 中位 = 这段时间"睁眼时 EAR 大概多少"。
    眨眼只占 ~4% 帧，动不了中位；低头/眼镜滑/距离变化都是慢漂移，中位跟得上。"""
    n = len(e)
    half = max(2, int(win_sec * FPS) // 2)
    idx = np.arange(n)
    lo = np.maximum(0, idx - half)
    hi = np.minimum(n, idx + half + 1)
    return np.array([np.median(e[a:b]) for a, b in zip(lo, hi)])


def ear_norm(e):
    return e / np.maximum(roll_med(e, ROLL_WIN), 1e-6)


def runs(x, mask_fn):
    """返回满足 mask_fn 的连续段长度（帧）"""
    out, cur = [], 0
    for v in x:
        if mask_fn(v):
            cur += 1
        elif cur:
            out.append(cur)
            cur = 0
    if cur:
        out.append(cur)
    return out


def feats(key):
    r = aligned(key)
    if r is None:
        return None
    e, eu = r
    m = get(key, "mar")
    if m is None or len(m) != len(e):
        return None
    pitch = eu[:, 0]
    dur = len(e) / FPS
    if dur < 5:
        return None

    en = ear_norm(e)
    closed = int(np.sum(en < BLINK_THR))
    blinks = len(runs(en, lambda v: v < BLINK_THR))
    yawns = len([d for d in runs(m, lambda v: v > YAWN_THR)
                 if d / FPS >= YAWN_MIN])
    # 点头用"相对本段中位的偏移"，不依赖欧拉角的正负号约定
    # （我不知道这个 pitch 正值是抬头还是低头，用绝对偏移就不用知道）
    mid = np.median(pitch)
    nods = len([d for d in runs(pitch, lambda v: abs(v - mid) > NOD_DROP)
                if d / FPS >= NOD_MIN])
    rng_p = float(np.percentile(pitch, 95) - np.percentile(pitch, 5))
    return [closed / len(e), blinks / dur * 60, yawns / dur * 60,
            nods / dur * 60], dur, rng_p


# ── 特征表 ────────────────────────────────────────────────────────────
print("【1】每组特征分布（中位）")
print(f"\n{'组':>9}{'段数':>6}{'PERCLOS':>10}{'眨眼/分':>10}"
      f"{'哈欠/分':>10}{'点头/分':>10}{'pitch范围':>11}")
print("-" * 68)
rows = {}
for g in ("normal", "fatigue", "glance", "phone", "yawn", "yawn_open",
          "talking"):
    F = [feats(k) for k in grp(g)]
    F = [f for f in F if f]
    if not F:
        continue
    rows[g] = np.array([f[0] for f in F])
    me = np.median(rows[g], 0)
    print(f"{g:>9}{len(F):>6}{me[0]:>10.3f}{me[1]:>10.1f}"
          f"{me[2]:>10.1f}{me[3]:>10.1f}"
          f"{np.median([f[2] for f in F]):>11.1f}")

# ── 训练集 ────────────────────────────────────────────────────────────
TR = ["normal", "glance", "phone", "fatigue"]
Xs, ys, names = [], [], []
for g in TR:
    for k in grp(g):
        f = feats(k)
        if f:
            Xs.append(f[0])
            ys.append(1 if g == "fatigue" else 0)
            names.append(k)
X, y = np.array(Xs), np.array(ys)
durs = [f[1] for g in TR for k in grp(g) for f in [feats(k)] if f]
print(f"\n【2】训练集 {len(y)} 段：疲劳 {y.sum()} / 其余 {(1-y).sum()}"
      f"   （片段时长中位 {np.median(durs):.1f}s，共 {sum(durs)/60:.1f} 分钟）")


def loo(Xa, ya, C=1.0):
    pred = np.zeros(len(ya), dtype=int)
    for i in range(len(ya)):
        tr = np.arange(len(ya)) != i
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=C, max_iter=2000))
        m.fit(Xa[tr], ya[tr])
        pred[i] = m.predict(Xa[[i]])[0]
    return pred


def report(tag, cols):
    p = loo(X[:, cols], y)
    acc = (p == y).mean()
    rec = (p[y == 1] == 1).mean()
    spe = (p[y == 0] == 0).mean()
    bal = 0.5 * (rec + spe)
    print(f"\n   {tag}")
    print(f"      准确率 {100*acc:.1f}%   "
          f"召回(疲劳) {100*rec:.1f}%   特异度 {100*spe:.1f}%   "
          f"平衡 {100*bal:.1f}%")
    return p, bal


print("\n【3】留一交叉验证")
p4, bal4 = report("4 特征（含点头）", [0, 1, 2, 3])
p3, bal3 = report("3 特征（去掉点头，支路二只管眼和嘴）", [0, 1, 2])

# 误报落在哪
print("\n   4 特征版的错误：")
for i, nm in enumerate(names):
    if p4[i] != y[i]:
        tag = "漏报(疲劳没查出来)" if y[i] == 1 else "误报"
        print(f"      {nm:<20} {'疲劳' if y[i] else '正常'}→"
              f"{'疲劳' if p4[i] else '正常'}  {tag}")

# ── 置换检验 ──────────────────────────────────────────────────────────
rng = np.random.default_rng(0)
NPERM = 300
null = []
for _ in range(NPERM):
    yp = rng.permutation(y)
    pp = loo(X[:, [0, 1, 2, 3]], yp)
    r = (pp[yp == 1] == 1).mean()
    s = (pp[yp == 0] == 0).mean()
    null.append(0.5 * (r + s))
null = np.array(null)
pv = float((null >= bal4).mean())
print(f"\n【4】置换检验（{NPERM} 次打乱标签）")
print(f"      真实 平衡准确率 {100*bal4:.1f}%")
print(f"      乱猜 均值 {100*null.mean():.1f}%   95 分位 {100*np.percentile(null,95):.1f}%"
      f"   最高 {100*null.max():.1f}%")
print(f"      p = {pv:.3f}  →  "
      + ("✅ 真信号" if pv < 0.05 else "❌ 不显著，这个特征组没学到东西"))

# ── 系数（选逻辑回归就是为了这个） ──────────────────────────────────
m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
m.fit(X, y)
sc, lr = m[0], m[1]
fn = ["PERCLOS", "眨眼频率", "哈欠频率", "点头频率"]
print("\n【5】标准化后的系数（可直接比大小 = 答辩用）")
o = np.argsort(-np.abs(lr.coef_[0]))
for i in o:
    print(f"      {fn[i]:<10} {lr.coef_[0][i]:+.3f}   "
          f"（原始尺度每增加 1 单位 → 对数几率 "
          f"{lr.coef_[0][i]/sc.scale_[i]:+.3f}）")
print(f"      截距 {lr.intercept_[0]:+.3f}")

sys.stdout.flush()
os._exit(0)
