"""冻结支路二模型：`_ear_raw.npz` → `models/branch2_lr.npz`。

── 为什么要落盘，而 `_scratch/live_face.py` 里是"当场拟合、不落盘" ──────
那是支路二**还没通过验证**时的规矩（`live_face.py:13-14`：它还没通过验证，
不配叫 model）。2026-09-23 它验通了，理由就反过来了：

1. `src/fuse.py` **不能** import `_scratch/` 下的东西 —— `live_face.py` 的最后
   一行是裸的 `main()`，import 就会直接开摄像头。
2. `StandardScaler` 的 `mean_`/`scale_` 以前只活在内存里。不落盘就没法在运行时
   复现标准化，等于模型有两个必须同时在场的部分而只存了一个。
3. 与项目自己的原则一致：`load_infer_model` 把窗口长度**从权重里读**，
   不从 config 读 —— 权重是唯一事实来源。

── 这个脚本同时是"src/face.py 搬对了没有"的验证 ──────────────────────
它的数字必须复现 2026-09-23 的基准：

    可算片段 96 段（106 段里有 10 段长度不齐，会被列出来）
    留一平衡准确率 65.7%   疲劳召回 38.5%   特异度 92.9%
    PERCLOS 系数 +0.859、NOD +0.408、BLINK +0.229

**对不上就是 `src/face.py` 的特征口径搬错了**，不是模型的问题。
（注意别拿旧的 71.4% 当目标——那是 probe_b2 的口径：居中帧数中位 + BLINK_THR 0.84
 + 106 段。两套口径不可比，`live_face.py:197-199` 写过这句话。）

用法：
    python tools/fit_branch2.py                 # 拟合 + 存盘
    python tools/fit_branch2.py --no-save       # 只看数字
    python tools/fit_branch2.py --perm 300      # 加置换检验
    python tools/fit_branch2.py --features perclos,brate,nod,yawn
"""
import argparse
import hashlib
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config as C
from face import (BLINK_THR, FEATURE_NAMES, NOD_DROP, NOD_MIN, NORM_Q, ROLL_WIN,
                  WIN_SEC, YAWN_MIN, YAWN_THR, clip_features)

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

GROUPS_POS = "fatigue"                      # 正类
GROUPS_NEG = ("normal", "glance", "phone")  # 负类
DEFAULT_CACHE = ROOT / "_scratch" / "_ear_raw.npz"
DEFAULT_OUT = ROOT / "models" / "branch2_lr.npz"


def build_xy(npz, need):
    """→ (X, y, keys, dropped)。dropped 是 [(key, 原因)]，**必须打出来**。"""
    files = set(npz.files)
    keys = sorted({k.rsplit("|", 1)[0] for k in files})
    X, y, used, dropped = [], [], [], []
    for g in (GROUPS_POS, *GROUPS_NEG):
        for k in [k for k in keys if k.startswith(g + "|")]:
            f, why = clip_features(npz, k, need=need)
            if f is None:
                dropped.append((k, why))
                continue
            X.append(f)
            y.append(1 if g == GROUPS_POS else 0)
            used.append(k)
    return np.array(X, float), np.array(y, int), used, dropped


def make_model():
    return make_pipeline(StandardScaler(),
                         LogisticRegression(C=1.0, max_iter=2000))


def loo(X, y, C_=1.0):
    """留一片段预测（**按片段留出**，不是按窗口随机分 —— 见 config.SPLIT_RATIO 的说明）。"""
    pred = np.zeros(len(y), dtype=int)
    for i in range(len(y)):
        tr = np.arange(len(y)) != i
        m = make_pipeline(StandardScaler(),
                          LogisticRegression(C=C_, max_iter=2000))
        m.fit(X[tr], y[tr])
        pred[i] = m.predict(X[[i]])[0]
    return pred


def scores(pred, y):
    rec = float((pred[y == 1] == 1).mean()) if (y == 1).any() else float("nan")
    spe = float((pred[y == 0] == 0).mean()) if (y == 0).any() else float("nan")
    acc = float((pred == y).mean())
    return acc, rec, spe, 0.5 * (rec + spe)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache", default=str(DEFAULT_CACHE))
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--features", default=",".join(FEATURE_NAMES),
                    help=f"逗号分隔，默认 {','.join(FEATURE_NAMES)}")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--perm", type=int, default=0,
                    help="置换检验次数（打乱标签，看显著不为偶然）")
    args = ap.parse_args()

    need = tuple(s.strip() for s in args.features.split(",") if s.strip())
    cache = Path(args.cache)
    if not cache.exists():
        raise SystemExit(f"找不到缓存 {cache}\n先跑 _scratch/probe_ear.py 生成它。")
    npz = np.load(cache, allow_pickle=True)

    X, y, used, dropped = build_xy(npz, need)
    print(f"缓存 {cache.name}")
    print(f"特征 {list(need)}")
    print(f"\n可用片段 {len(y)}（疲劳 {int(y.sum())}）")
    if dropped:
        print(f"丢弃 {len(dropped)} 段：")
        for k, why in dropped:
            print(f"    {k:<22}{why}")
        print("  ⚠️ 丢掉的是【数据长度不齐】的片段，别把它和"
              "【有效时长 < 5 s】混成一句。")
    if len(y) < 20:
        raise SystemExit("可用片段太少，先补数据")

    # ── 主报告 ───────────────────────────────────────────────────────
    pred = loo(X, y)
    acc, rec, spe, bal = scores(pred, y)
    print(f"\n留一（按片段留出）")
    print(f"    准确率   {100*acc:6.1f}%")
    print(f"    疲劳召回 {100*rec:6.1f}%")
    print(f"    特异度   {100*spe:6.1f}%")
    print(f"    平衡准确率 {100*bal:6.1f}%   ← 主指标（单看准确率会被不平衡骗）")
    wrong = [used[i] for i in range(len(y)) if pred[i] != y[i]]
    print(f"    错判 {len(wrong)} 段：{', '.join(wrong) if wrong else '无'}")

    # 每一列的分布 —— 这一栏是"这列没信息"和"这列恒为常数"的分界
    print(f"\n各列分布（恒为常数的列对逻辑回归没有意义 —— 那是【常数】，不是【没用】）")
    print(f"{'列':<10}{'中位':>9}{'最小':>9}{'最大':>9}{'非零段数':>10}")
    print("-" * 47)
    for j, nm in enumerate(need):
        col = X[:, j]
        print(f"{nm:<10}{np.median(col):>9.3f}{col.min():>9.3f}{col.max():>9.3f}"
              f"{int((col != 0).sum()):>10}")

    m = make_model()
    m.fit(X, y)
    coef = m[1].coef_[0]
    print(f"\n标准化系数（绝对值降序）")
    for j in np.argsort(-np.abs(coef)):
        print(f"    {need[j]:<10}{coef[j]:+.3f}")

    if args.perm:
        rng = np.random.default_rng(0)
        null = np.array([scores(loo(X, rng.permutation(y)), y)[3]
                         for _ in range(args.perm)])
        p = float((null >= bal).mean())
        print(f"\n置换检验 {args.perm} 次：真实 {100*bal:.1f}% vs "
              f"零分布中位 {100*np.median(null):.1f}%   p = {p:.4f}"
              f"   ({'显著' if p < 0.05 else '不显著'})")

    if args.no_save:
        print("\n--no-save，不落盘。")
        sys.stdout.flush()
        os._exit(0)

    # ── 存盘 ─────────────────────────────────────────────────────────
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    const = dict(ROLL_WIN=ROLL_WIN, NORM_Q=NORM_Q, BLINK_THR=BLINK_THR,
                 YAWN_THR=YAWN_THR, YAWN_MIN=YAWN_MIN,
                 NOD_DROP=NOD_DROP, NOD_MIN=NOD_MIN, WIN_SEC=WIN_SEC)
    np.savez(out,
             coef=m[1].coef_.astype(np.float32),
             intercept=m[1].intercept_.astype(np.float32),
             mean=m[0].mean_.astype(np.float32),
             scale=m[0].scale_.astype(np.float32),
             features=np.array(need),
             classes=np.array(C.CLASSES),
             n_clips=len(y), n_pos=int(y.sum()),
             loo_bal=bal, loo_acc=acc, loo_rec=rec, loo_spe=spe,
             const=np.array(list(const.items()), dtype=object),
             cache=str(cache),
             cache_sha256=hashlib.sha256(cache.read_bytes()).hexdigest(),
             created=time.strftime("%Y-%m-%d %H:%M:%S"))
    print(f"\n存到 {out}")
    print(f"  缓存 sha256 前 16 位 {hashlib.sha256(cache.read_bytes()).hexdigest()[:16]}")
    print("  ⚠️ src/fuse.py 加载时会核对 const 与 src/face.py 的当前常量，"
          "不一致会告警——改了特征口径就必须重跑本脚本。")
    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
