# -*- coding: utf-8 -*-
"""标定「持续闭眼」这条**规则**要多久 —— 哈欠规则的姊妹条。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_calib_closeeye.py [--grid 0.5,0.8,1.0,1.2,1.5,2.0]

**为什么要做这条规则**（2026-09-26，用户原话「太不敏感了」「点头低头为啥有时候不报
还报我健康」）：支路二的 `l2` 在 `ui/cam.py:326-334` / `src/fuse.py` 里**只有
`fb.full()`（27 s）之后才算**，之前一律 `l2 = 0`。于是开机后那 27 秒里：
  · `l_face = min(l2, 2)` = 0 → 支路二**没有投票权**
  · 「检测到持续闭眼」这条告警（`ui/state.py:300` 判 `l2 >= 1`）**结构上不可能响**
  · 而 `perclos` 明明第 10 秒就有真值了
哈欠规则当初就**故意**没挂在那个预热上（`src/fuse.py:614-619` 的注释：挂在 `st` 上
等于让逻辑回归的热身去管规则，代价是短片段上永远不响）。闭眼是同一种东西 ——
它的判据是**时长**，不需要 17 秒的窗、也不需要 27 秒的缓冲。

**这条脚本回答的唯一问题**：`ear_norm` 连续低于 `BLINK_THR` 多少秒，
在「正常/瞟一眼/低头/疲劳」四组里分别是多少？于是能定出一个
「正例全触发、负例全不触发」的 N —— 和 `tools/calib_yawn.py` 完全同一个套路。

⚠️ 只读 `_scratch/_ear_raw.npz` 缓存（`probe_ear.py` 那份，15 fps、字段 t/ear/mar/…），
   **不重跑 FaceMesh**，所以不用开摄像头、也不碰 mediapipe 的 42 秒析构。
⚠️ 归一化必须调 `face.norm_by_time`（p75 基线）**本体**，不许在这里重写一遍 ——
   两份实现迟早不一致（`src/face.py` 模块开头那段警告说的就是这个）。
"""
import argparse
import os
import sys

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, os.path.join(ROOT, "src"))

from face import BLINK_THR, NORM_Q, ROLL_WIN, norm_by_time, runs_sec  # noqa: E402

CACHE = os.path.join(HERE, "_ear_raw.npz")
GROUPS = ("normal", "glance", "phone", "fatigue")     # 四组是"人正常开车的各种样子"
EXTRA = ("talking", "yawn_open", "yawn")             # 旁证


def longest(ts, en, thr):
    """这一段里最长的**连续闭眼**多少秒（= 哈欠那边 `yawn_seconds` 的同款）。"""
    return max(runs_sec(ts, en, lambda v: v < thr) or [0.0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--grid", default="0.5,0.8,1.0,1.2,1.5,2.0,3.0")
    args = ap.parse_args()
    grid = [float(x) for x in args.grid.split(",")]

    z = np.load(CACHE, allow_pickle=True)
    keys = sorted(z.files)
    per = {g: [] for g in GROUPS + EXTRA}
    for k in keys:
        g = k.split("|")[0]
        if g not in per:
            continue
        f = k.split("|")[2] if len(k.split("|")) > 2 else ""
        if f != "ear":
            continue
        clip = k.split("|")[1]
        tkey, ekey = "%s|%s|t" % (g, clip), k
        if tkey not in z.files:
            continue
        ts = np.asarray(z[tkey], float)
        ear = np.asarray(z[ekey], float)
        if len(ts) < 20 or not np.isfinite(ear).any():      # noqa: PLR2004
            continue
        en = ear / np.maximum(norm_by_time(ts, ear, ROLL_WIN), 1e-6)
        per[g].append((clip, longest(ts, en, BLINK_THR)))

    print("BLINK_THR=%.2f  NORM_Q=%.0f  ROLL_WIN=%.1f  （归一化走 face.norm_by_time）"
          % (BLINK_THR, NORM_Q, ROLL_WIN))
    print("\n【1】每段最长的连续闭眼（秒）")
    for g in GROUPS + EXTRA:
        if not per[g]:
            continue
        d = sorted(v for _, v in per[g])
        print("\n  %-9s %d 段   最短 %.2f  中位 %.2f  最长 %.2f"
              % (g, len(d), d[0], d[len(d) // 2], d[-1]))
        print("            " + "  ".join("%s=%.2f" % (c[-6:], v)
                                         for c, v in sorted(per[g], key=lambda x: x[1])))

    print("\n【2】N 扫描：正常侧要**全部不触发**，疲劳侧要**尽量多触发**")
    print("     判据 = min(疲劳侧最长) − max(正常侧最长)，正数才有余量")
    print("\n     %-6s %-14s %-14s %-14s %-10s %s"
          % ("N(s)", "正常侧触发", "低头侧触发", "疲劳侧触发", "说话侧触发", "余量"))
    for N in grid:
        a = sum(v >= N for _, v in per["normal"])
        b = sum(v >= N for _, v in per["phone"])
        c = sum(v >= N for _, v in per["fatigue"])
        t = per["talking"]
        s = sum(v >= N for _, v in t)
        mn = min([v for _, v in per["fatigue"]] or [np.nan])
        mx = max([v for _, v in per["normal"]] or [np.nan])
        print("     %-6.1f %-14s %-14s %-14s %-10s %+.2f"
              % (N, "%d/%d" % (a, len(per["normal"])), "%d/%d" % (b, len(per["phone"])),
                 "%d/%d" % (c, len(per["fatigue"])), "%d/%d" % (s, len(t)), mn - mx))

    print("\n【3】⚠️ 这条规则**只能当补充，不能替掉 perclos**：")
    print("     · 它看的是「一次闭眼有多久」，perclos 看的是「窗内闭眼占多少」——")
    print("       一个司机连续闭 1.0 s、每 3 秒来一次，perclos 会很高，而这条规则不响。")
    print("     · 反过来它有个 perclos 没有的好处：**第 ROLL_WIN(+N) 秒就能响**，")
    print("       而 `l2` 要等 27 s（`fb.full()`）。这正是用户说的「不应该等时间」。")
    print("     · 基线仍要 ROLL_WIN=10 s（p75）—— 这一段**不能省**：窗短于 10 秒时")
    print("       分位数会被闭眼自己拽塌，`ear/基线` 恒为 1，越疲劳越读不出来。")
    sys.stdout.flush()
    os._exit(0)          # mediapipe/python 的收尾别等（见 _scratch 那条记录）


if __name__ == "__main__":
    main()
