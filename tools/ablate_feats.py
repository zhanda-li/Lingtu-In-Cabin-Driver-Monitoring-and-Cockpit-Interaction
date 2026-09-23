"""哈欠特征消融：把 YAWN/min 从逻辑回归里去掉，会不会变差？

── 为什么必须跑这一遍 ────────────────────────────────────────────────
「哈欠特征没信息量」这句话在项目里被当作推断用了很久，但它**从来没被实测过**。
`probe_b2.py:181-182` 只报过两个变体（4 特征、以及去掉**点头**的 3 特征），
从没跑过去掉哈欠的那一版。而 `probe_b2.py:167 report()` 本来就支持按列子集评估，
只是没人调过。

真正的理由比"推断"更硬：训练集只有 normal/glance/phone/fatigue 四组，
yawn / talking / yawn_open **从不进 LR**，所以 `YAWN/min` 这一列在 96 段训练
片段上**恒等于 0**。逻辑回归对一个恒 0 列给出的系数就是 0 —— 这是
**「这一列是常数」，不是「这一列没用」**。两者必须分开报，否则以后有人
看到系数 0.000 会以为"哈欠没价值"，然后拿一个错误的理由把它永久删掉。

判决标准不是准确率差多少，而是**错判的是不是同一批片段**——
同一个数字可以掩盖不同的错判集合。

用法：
    python tools/ablate_feats.py
    python tools/ablate_feats.py --perm 300
"""
import argparse
import math
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config as C
from face import clip_features

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

CACHE = ROOT / "_scratch" / "_ear_raw.npz"
# 自检：2026-09-23 实测的基准。不等就说明本次跑的已经不是同一口径
BASE_BAL_4 = 65.7

SUBSETS = [
    ("4 特征（含哈欠，历史口径）", ("perclos", "brate", "yawn", "nod")),
    ("3 特征（去哈欠，本次采用）", ("perclos", "brate", "nod")),
    ("2 特征（只留眼睛）", ("perclos", "brate")),
    ("1 特征（只有 PERCLOS）", ("perclos",)),
]


def build(need):
    npz = np.load(CACHE, allow_pickle=True)
    keys = sorted({k.rsplit("|", 1)[0] for k in npz.files})
    X, y, names = [], [], []
    for g in ("fatigue", "normal", "glance", "phone"):
        for k in [k for k in keys if k.startswith(g + "|")]:
            f, _ = clip_features(npz, k, need=need)
            if f is None:
                continue
            X.append(f)
            y.append(1 if g == "fatigue" else 0)
            names.append(k)
    return np.array(X, float), np.array(y, int), names


def loo(X, y, C_=1.0):
    pred = np.zeros(len(y), dtype=int)
    for i in range(len(y)):
        tr = np.arange(len(y)) != i
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=C_, max_iter=2000))
        m.fit(X[tr], y[tr])
        pred[i] = m.predict(X[[i]])[0]
    return pred


def report(pred, y):
    rec = float((pred[y == 1] == 1).mean())
    spe = float((pred[y == 0] == 0).mean())
    acc = float((pred == y).mean())
    return acc, rec, spe, 0.5 * (rec + spe)


def bal_only(pred, y):
    """平衡准确率。自助重采样里正负样本可能被抽空，得挡住除零。"""
    p, n = y == 1, y == 0
    if not p.any() or not n.any():
        return float("nan")
    return 0.5 * (float((pred[p] == 1).mean()) + float((pred[n] == 0).mean()))


def mcnemar_exact(b, c):
    """McNemar 精确检验：只有「A 错 B 对」和「B 错 A 对」两种不一致帧有用。

    用二项分布直接算，不引 scipy —— 这个仓库的依赖已经够多了。
    这是**配对**检验，置换检验不是：置换打乱的是标签，配对比较的是同一批片段。
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / (2.0 ** n)
    return min(1.0, 2.0 * tail)


def boot_delta(pred_a, pred_b, y, n=2000, seed=0):
    """按**片段**重采样，返回 Δ平衡准确率(A−B) 的 95% 区间。

    区间跨 0 = 这 96 段证不出两组有差别，选哪组只能靠理由是够硬，不能靠分数。
    """
    rng = np.random.default_rng(seed)
    idx = np.arange(len(y))
    d = []
    for _ in range(n):
        s = rng.choice(idx, len(idx), replace=True)
        a, b = bal_only(pred_a[s], y[s]), bal_only(pred_b[s], y[s])
        if a == a and b == b:          # 两者都不是 nan
            d.append(a - b)
    if not d:
        return float("nan"), float("nan")
    return float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--perm", type=int, default=0)
    args = ap.parse_args()

    print(f"缓存 {CACHE.name}   口径：norm_by_time p75 + runs_sec 真实秒数\n")
    res, PRED = {}, {}
    print(f"{'特征组':<28}{'准确率':>8}{'召回':>8}{'特异度':>9}{'平衡准确率':>11}")
    print("-" * 64)
    for tag, need in SUBSETS:
        X, y, names = build(need)
        pred = loo(X, y)
        acc, rec, spe, bal = report(pred, y)
        res[tag] = (bal, [names[i] for i in range(len(y)) if pred[i] != y[i]], X, need, names, y)
        PRED[tag] = pred
        print(f"{tag:<28}{100*acc:>7.1f}%{100*rec:>7.1f}%{100*spe:>8.1f}%{100*bal:>10.1f}%")

    # ── 主对照：4 特征 vs 3 特征 ─────────────────────────────────────
    w4 = res["4 特征（含哈欠，历史口径）"]
    w3 = res["3 特征（去哈欠，本次采用）"]
    print(f"\n【主对照】4 特征 {100*w4[0]:.1f}%  vs  3 特征 {100*w3[0]:.1f}%"
          f"   差 {100*(w3[0]-w4[0]):+.1f} 个百分点")
    print(f"  4 特征错判 {len(w4[1])} 段")
    print(f"  3 特征错判 {len(w3[1])} 段")
    same = set(w4[1]) == set(w3[1])
    print(f"  错判集合{'完全相同' if same else '不同'} —— "
          f"{'去掉哈欠是零代价' if same else '⚠️ 去掉哈欠改变了错判集合，需要逐个看'}")

    if abs(100 * w4[0] - BASE_BAL_4) > 0.15:
        print(f"\n⚠️ 4 特征版平衡准确率 {100*w4[0]:.1f}% 与基准 {BASE_BAL_4}% 不符 ——"
              f"本次跑的已经不是同一口径，上面的对照作废，先查 src/face.py")
    else:
        print(f"\n✅ 4 特征版复现基准 {BASE_BAL_4}%，口径一致")

    # ── 配对比较：置换检验比不了两组之间 ────────────────────────────
    print(f"\n【配对比较】上面四组的置换检验 p 全是 0.0000 —— 它只能证明「优于随机」，"
          f"\n  **不能**用来比较两组之间。要回答「68.3% 是不是真的比 65.7% 好」，"
          f"\n  只能看同一批片段上谁错谁对是否不对称（McNemar）+ 按片段自助重采样。")
    print(f"\n{'A（对照）':<26}{'B（基准）':<26}{'A独错':>7}{'B独错':>7}"
          f"{'McNemar p':>11}{'Δ平衡准确率 95%CI':>20}")
    print("-" * 97)
    PAIRS = [
        ("2 特征（只留眼睛）", "3 特征（去哈欠，本次采用）"),
        ("2 特征（只留眼睛）", "4 特征（含哈欠，历史口径）"),
        ("1 特征（只有 PERCLOS）", "3 特征（去哈欠，本次采用）"),
        ("4 特征（含哈欠，历史口径）", "3 特征（去哈欠，本次采用）"),
    ]
    for ta, tb in PAIRS:
        pa, pb = PRED[ta], PRED[tb]
        y = res[ta][5]
        b = int(((pa != y) & (pb == y)).sum())   # A 错 B 对
        c = int(((pa == y) & (pb != y)).sum())   # B 错 A 对
        lo, hi = boot_delta(pa, pb, y)
        p = mcnemar_exact(b, c)
        short = lambda s: s.split("（")[0]
        print(f"{short(ta):<26}{short(tb):<26}{b:>7}{c:>7}{p:>11.4f}"
              f"{f'{100*(res[ta][0]-res[tb][0]):+.1f}pp [{100*lo:+.1f},{100*hi:+.1f}]':>20}")
    print("  区间跨 0（含负号）= 这 96 段证不出两组有差别。此时**不能靠分数选特征**，"
          "\n  那是对测试集的挑选偏差；只能靠理由够不够硬。这就是本项目"
          "\n  「留一按片段留出」的道理：别让同一段同时参与选择和汇报。")

    # ── 列分布：把"常数"和"没用"分开 ────────────────────────────────
    print(f"\n【各列分布】恒为常数的列对 LR 没有意义 —— 那是【常数】，不是【没用】")
    print(f"{'列':<10}{'中位':>9}{'最小':>9}{'最大':>9}{'标准差':>9}{'非零段数':>10}")
    print("-" * 57)
    X4, need4, names4, y4 = w4[2], w4[3], w4[4], w4[5]
    for j, nm in enumerate(need4):
        c = X4[:, j]
        print(f"{nm:<10}{np.median(c):>9.3f}{c.min():>9.3f}{c.max():>9.3f}"
              f"{c.std():>9.3f}{int((c != 0).sum()):>10}")
    ycol = list(need4).index("yawn")
    if (X4[:, ycol] == 0).all():
        print(f"\n  → yawn 列在全部 {len(X4)} 段上恒等于 0：",
              "**它是常数，所以系数必然是 0.000**。")
        print("    这不等于\"哈欠没用\"——训练集里根本没有哈欠样本可学。")
        print("    哈欠改由 src/fuse.py 的独立规则处理，标定见 tools/calib_yawn.py。")

    # ── 系数 ────────────────────────────────────────────────────────
    print(f"\n【标准化系数】")
    for tag in ("4 特征（含哈欠，历史口径）", "3 特征（去哈欠，本次采用）"):
        X, need, *_ = res[tag][2], res[tag][3], res[tag][4], res[tag][5]
        m = make_pipeline(StandardScaler(), LogisticRegression(C=1.0, max_iter=2000))
        m.fit(X, res[tag][5])
        co = m[1].coef_[0]
        print(f"  {tag}")
        for j in np.argsort(-np.abs(co)):
            print(f"      {need[j]:<10}{co[j]:+.3f}")

    if args.perm:
        rng = np.random.default_rng(0)
        print(f"\n【置换检验】{args.perm} 次打乱标签。"
              f"四组用同一个零分布，才比得出「68.3% 是不是噪声」")
        for tag, need in SUBSETS:
            Xs, ys, _ = build(need)
            real = report(loo(Xs, ys), ys)[3]
            null = np.array([report(loo(Xs, rng.permutation(ys)), ys)[3]
                             for _ in range(args.perm)])
            print(f"  {tag:<28} 真实 {100*real:.1f}%  "
                  f"零分布中位 {100*np.median(null):.1f}%  "
                  f"p = {(null >= real).mean():.4f}")

    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
