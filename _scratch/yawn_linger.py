# -*- coding: utf-8 -*-
"""「打哈欠后为啥显示那么长时间」—— 把那个"长"量出来，顺便判计划里的改法能不能治。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\yawn_linger.py

用户的抱怨是**显示**：打完哈欠，`#sYawn` 那个秒数还挂在那儿很久（`app.js:428`
就是 `s.yawn_sec.toFixed(1)`，判据在 `ui/state.py:213,298` 的 `yawn_sec >= yawn_min`）。

为什么它会挂那么久：`yawn_sec = yawn_seconds(ts, mar)` 返回的是**窗内最长那次
张嘴**（`src/face.py:207`）。窗长 27 s，所以哈欠只要还在窗里，这个数就一直
是那个常数 —— 一条**平台**，不是脉冲。平台的长度 ≈ 窗长，和哈欠本身多长无关。

所以这次量两件事：
  1. 哈欠本身（`MAR > YAWN_THR` 的连续段）多长；
  2. 它**结束之后**，`yawn_sec` 还挂在 `>= yawn_min` 多少秒 —— 用户看到的"长"是这个。

判计划的改法能不能治（决定性）：计划里批准的是「`yawn_sec` 掉回 `< yawn_min`
之后再显示 `hold_sec` 秒，然后归 0」。如果 (2) 本来就是二十几秒（平台塌下来
很晚），那这个锁存**触发得太晚**，只会把显示再拖长 3 秒 —— 治不了。
要治必须给显示层一个"哈欠现在结束了"的**脉冲**信号，而 `yawn_sec` 里没有这个信息。

⚠️ 只读不改：不碰 `src/face.py`、`src/fuse.py`、任何参数。
"""
import csv
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
from face import YAWN_THR, YAWN_MIN   # noqa: E402

SESS = [
    ("runs/session1.csv", "融合会话 1"),
    ("runs/session2.csv", "融合会话 2"),
    ("_scratch/_face_live_20260922_235417.csv", "标定集"),
    ("_scratch/_face_live_20260923_103357.csv", "真人会话 A"),
    ("_scratch/_face_live_20260923_103843.csv", "真人会话 B"),
]


def num(s):
    s = (s or "").strip()
    try:
        return float(s)
    except ValueError:
        return np.nan


def load(p):
    with open(p, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    t = np.array([num(r.get("t")) for r in rows])
    mar = np.array([num(r.get("mar")) for r in rows])
    ysec = np.array([num(r.get("yawn_sec") or r.get("yawn")) for r in rows])
    return t, mar, ysec


def runs(t, x, pred):
    """[(起, 止, 时长)]，只取满足 pred 的连续段。"""
    out, i, n = [], 0, len(x)
    while i < n:
        if np.isfinite(x[i]) and pred(x[i]):
            j = i
            while j + 1 < n and np.isfinite(x[j + 1]) and pred(x[j + 1]):
                j += 1
            out.append((float(t[i]), float(t[j]), float(t[j] - t[i])))
            i = j + 1
        else:
            i += 1
    return out


def main():
    print("=" * 96)
    print("哈欠：它本身多长 vs 打完还挂多久（YAWN_THR=%.2f  YAWN_MIN=%.2f）"
          % (YAWN_THR, YAWN_MIN))
    print("=" * 96)
    for rel, tag in SESS:
        p = ROOT / rel
        if not p.exists():
            print("\n%-14s 找不到 %s" % (tag, rel))
            continue
        t, mar, ysec = load(p)
        if not np.isfinite(ysec).any():
            print("\n%-14s 没有 yawn_sec 列，跳过" % tag)
            continue
        mar_runs = runs(t, mar, lambda v: v > YAWN_THR)
        plateau = runs(t, ysec, lambda v: v >= YAWN_MIN)
        print("\n%-14s %s  %.0f s @ %.1f Hz"
              % (tag, p.name, t[-1] - t[0],
                 len(t) / max(t[-1] - t[0], 1e-9)))
        print("   MAR>%.2f 的张嘴段 %d 个：%s"
              % (YAWN_THR, len(mar_runs),
                 "  ".join("%.1fs" % d for _, _, d in mar_runs) or "无"))
        print("   yawn_sec>=%.1f 的平台段 %d 个：%s"
              % (YAWN_MIN, len(plateau),
                 "  ".join("%.1fs" % d for _, _, d in plateau) or "无"))
        # 关键：每个张嘴段结束后，平台还挂多久
        for a, b, d in mar_runs:
            after = [x for x in plateau if x[1] >= b]
            if not after:
                print("     张嘴 %.1fs（%.1f~%.1f s）→ 结束后平台立刻没有"
                      % (d, a, b))
                continue
            ling = max(x[1] for x in after) - b
            # 平台上显示的值 = 用户看到的那个"秒数"
            sl = (t >= a) & (t <= b)
            shown = float(np.nanmax(ysec[sl])) if sl.any() else np.nan
            print("     张嘴 %.1fs（%.1f~%.1f s）→ 屏幕上那个数显示 %.1f s，"
                  "哈欠结束后还挂 **%.1f s**"
                  % (d, a, b, shown, ling))

    print("\n" + "=" * 96)
    print("怎么读：")
    print("  · 若「还挂 X 秒」普遍是二十几秒 → 用户抱怨的那个「长时间」= 窗长，")
    print("    和哈欠本身多长无关；")
    print("  · 而计划批准的改法是「yawn_sec 掉回 < yawn_min 之后**再**显示 hold_sec 秒」，")
    print("    触发点在平台塌下来的那一刻 —— 也就是上面那个 X 秒之后，")
    print("    它只会把显示**再拖长** hold_sec 秒，**治不了这个抱怨**。")
    print("=" * 96)


if __name__ == "__main__":
    main()
