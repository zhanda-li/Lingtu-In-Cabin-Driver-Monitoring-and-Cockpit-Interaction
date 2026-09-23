"""哈欠阈值标定：YAWN_THR / YAWN_MIN 到底该取多少。

── 为什么必须单独跑这一遍 ────────────────────────────────────────────
`YAWN_THR = 0.60` 在项目里存在了很久，但**从来没有任何标定记录**：
`probe_b2.py:37` 只有一句「MAR 高于它算张嘴」，`live_face.py:60` 原样照抄。
而唯一一次想验它的尝试得出了**反向**的结论 —— `_scratch/_ear.txt:178`：

    哈欠最低 0.00s vs 说话最高 0.87s  →  ❌ 重叠，MAR 和 jawOpen 不等价，要重新想

那条结论是错的，原因在**正例选错了**：它用的是 `yawn` 组（**捂着嘴**打哈欠），
而 `probe_ear.py:311-313` 自己写过：「yawn 那组是捂嘴的，几何量必然塌，
拿它当正例 = 自己制造'分不开'的结论」，合法正例应该是 `yawn_open`。
偏偏那个对照因为 `probe_ear.py:299/302` 的键不一致（`sep` 只初始化了
yawn/talking，过滤条件却放行 yawn_open）**KeyError 崩了，从未打印过**。

本脚本就是补上那一次。结论（2026-09-23 实测）：**分得开**。

── 判别量是「持续」，不是「峰值」────────────────────────────────────
单帧 MAR 上哈欠和说话**完全重叠**：talking max 0.777 vs yawn_open p90 最低 0.727。
但说话是**尖峰**，哈欠是**平台**：

    yawn_open  MAR p50 = 0.64~0.73（一半的帧都张着）
    talking    MAR p90 = 0.36~0.49（偶发尖峰）

所以判据是"张了多久"，不是"张得多大"。

用法：
    python tools/calib_yawn.py
    python tools/calib_yawn.py --min-grid 1.0,1.5,2.0,2.5
"""
import argparse
import os
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
import config as C
from face import YAWN_MIN, YAWN_THR, runs_sec

CACHE = ROOT / "_scratch" / "_ear_raw.npz"

# 正例用 yawn_open（不捂嘴），捂嘴的 yawn 只作为**局限**列出来
POS, NEG, LIMIT = "yawn_open", "talking", "yawn"
TRAIN_GROUPS = ("normal", "glance", "phone", "fatigue")


def load(npz):
    t = {}
    keys = sorted({k.rsplit("|", 1)[0] for k in npz.files})
    for g in (POS, NEG, LIMIT, *TRAIN_GROUPS):
        for k in [k for k in keys if k.startswith(g + "|")]:
            mk = f"{k}|mar"
            tk = f"{k}|t"
            if mk not in npz.files or tk not in npz.files:
                continue
            mar, ts = np.asarray(npz[mk], float), np.asarray(npz[tk], float)
            if np.isfinite(mar).sum() < 10:
                continue
            t.setdefault(g, []).append((k, ts, mar))
    return t


def longest(ts, mar, thr):
    """最长连续 MAR > thr 的**真实秒数**。按时间戳算，不按帧数。"""
    return max(runs_sec(ts, mar, lambda v: v > thr) or [0.0])


def rollmax(ts, mar, win=1.5):
    """滚动 win 秒均值的段内最大值。第二个候选判别量。"""
    mar = np.asarray(mar, float)
    best = 0.0
    for i in range(len(mar)):
        s = (ts >= ts[i] - win) & (ts <= ts[i])
        w = mar[s]
        w = w[np.isfinite(w)]
        if len(w) >= 3:
            best = max(best, float(np.mean(w)))
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-grid", default="1.0,1.5,2.0,2.5")
    args = ap.parse_args()
    mins = [float(x) for x in args.min_grid.split(",")]

    if not CACHE.exists():
        raise SystemExit(f"找不到 {CACHE}，先跑 _scratch/probe_ear.py")
    npz = np.load(CACHE, allow_pickle=True)
    D = load(npz)
    for g in (POS, NEG, LIMIT):
        if g not in D:
            raise SystemExit(f"缓存里没有 {g} 组，先补录素材")

    print(f"缓存 {CACHE.name}")
    print(f"正例 {POS}（不捂嘴）{len(D[POS])} 段   "
          f"负例 {NEG}（说话）{len(D[NEG])} 段   "
          f"对照 {LIMIT}（捂嘴）{len(D[LIMIT])} 段\n")

    # ── 逐段明细 ────────────────────────────────────────────────────
    print(f"【1】逐段明细（thr={YAWN_THR}）")
    print(f"{'片段':<20}{'时长s':>8}{'MAR p50':>9}{'p90':>7}{'max':>7}"
          f"{'最长张嘴s':>11}{'滚均1.5s峰值':>13}")
    print("-" * 76)
    for g in (POS, LIMIT, NEG):
        for k, ts, mar in D[g]:
            ok = mar[np.isfinite(mar)]
            print(f"{k:<20}{ts[-1]-ts[0]:>8.1f}"
                  f"{np.percentile(ok, 50):>9.3f}{np.percentile(ok, 90):>7.3f}"
                  f"{ok.max():>7.3f}"
                  f"{longest(ts, mar, YAWN_THR):>11.2f}"
                  f"{rollmax(ts, mar):>13.3f}")
        print()

    # ── 阈值扫描 ────────────────────────────────────────────────────
    print(f"【2】阈值扫描：判据 = min({POS} 最长张嘴) − max({NEG} 最长张嘴)")
    print(f"{'thr':>6}{POS + ' 最短':>16}{NEG + ' 最长':>16}{'间隔':>10}   判据")
    print("-" * 66)
    for thr in (0.45, 0.50, 0.55, 0.60, 0.65, 0.70):
        p = [longest(ts, mar, thr) for _, ts, mar in D[POS]]
        n = [longest(ts, mar, thr) for _, ts, mar in D[NEG]]
        gap = min(p) - max(n)
        print(f"{thr:>6.2f}{min(p):>16.2f}{max(n):>16.2f}{gap:>+10.2f}   "
              + ("✅ 分离" if gap > 1.0 else ("勉强" if gap > 0 else "❌ 重叠")))

    # ── YAWN_MIN 扫描（thr 固定为当前值）────────────────────────────
    print(f"\n【3】YAWN_MIN 扫描（thr={YAWN_THR}）：正例要全部触发，负例要全部不触发")
    print(f"{'MIN(s)':>8}{POS + ' 触发':>14}{NEG + ' 触发':>14}{'两侧余量':>22}")
    print("-" * 60)
    p = [longest(ts, mar, YAWN_THR) for _, ts, mar in D[POS]]
    n = [longest(ts, mar, YAWN_THR) for _, ts, mar in D[NEG]]
    for mn in mins:
        pt, nt = sum(d >= mn for d in p), sum(d >= mn for d in n)
        print(f"{mn:>8.1f}{f'{pt}/{len(p)}':>14}{f'{nt}/{len(n)}':>14}"
              f"{f'{min(p)-mn:+.2f} / {mn-max(n):+.2f}':>22}"
              + ("   ← 当前" if abs(mn - YAWN_MIN) < 1e-9 else ""))
    print("  余量 = (正例最短 − MIN) / (MIN − 负例最长)，两个都为正才分得开")

    # ── 结论 ────────────────────────────────────────────────────────
    gap = min(p) - max(n)
    ok_pos = sum(d >= YAWN_MIN for d in p)
    ok_neg = sum(d >= YAWN_MIN for d in n)
    print(f"\n【4】结论（thr={YAWN_THR} / MIN={YAWN_MIN}）")
    print(f"  正例触发 {ok_pos}/{len(p)}   负例触发 {ok_neg}/{len(n)}   "
          f"间隔 {gap:+.2f} s")
    if ok_pos == len(p) and ok_neg == 0 and gap > 1.0:
        print("  ✅ 分得开 → 哈欠规则按「抬到 L1」实现（src/fuse.py 的 YAWN_ACTION=\"level\"）")
    else:
        print("  ❌ 分不开 → 哈欠降级为「只显示 + 只写日志」，不动级别"
              "（src/fuse.py 的 YAWN_ACTION=\"display\"）")

    lp = [longest(ts, mar, YAWN_THR) for _, ts, mar in D[LIMIT]]
    print(f"\n【5】⚠️ 局限：捂嘴哈欠 {LIMIT} 组 "
          f"{sum(d >= YAWN_MIN for d in lp)}/{len(lp)} 触发，最长只有 {max(lp):.2f} s")
    print("  捂嘴时嘴部几何量被手挡住，MAR 读不出来。这不是阈值问题，是模态问题。")
    print("  驾驶场景手在方向盘上，捂嘴不是目标场景，但必须如实写进报告的局限。")
    print("  （`_ear.txt:178` 那条\"MAR 分不开\"的结论就是把这一组当了正例。）")

    # ── 训练集里哈欠事件恒为 0：消融那条结论的现场证据 ───────────────
    tot = trig = 0
    for g in TRAIN_GROUPS:
        for k, ts, mar in D.get(g, []):
            tot += 1
            if longest(ts, mar, YAWN_THR) >= YAWN_MIN:
                trig += 1
    print(f"\n【6】训练集（{'+'.join(TRAIN_GROUPS)}）{tot} 段里触发哈欠事件的：{trig} 段")
    print("  这就是 tools/ablate_feats.py 里\"yawn 列恒等于 0、系数 0.000\"的来源 ——")
    print("  不是\"哈欠没用\"，是训练集里根本没有哈欠样本。")

    sys.stdout.flush()
    os._exit(0)


if __name__ == "__main__":
    main()
