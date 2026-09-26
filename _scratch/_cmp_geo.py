# -*- coding: utf-8 -*-
"""把 13.png 和当前封面截图的**版式几何**量成同一套数，别靠眼睛比。

    D:\Anaconda3\envs\dms\python.exe _scratch\_cmp_geo.py [截图路径]

判据只用一条：**深墨像素**（亮度低）。13.png 的左栏大标题/副标题/胶囊文字
都是深蓝墨，而背景是浅蓝（亮度 > 200）。所以按行统计深墨像素的密度，
密度陡增的那几段就是「大标题带 / 副标题带 / 胶囊带」。

⚠️ 只量左栏（x < 52% 宽）：右边是小瑞，他头发和耳机也是深蓝，会污染行统计。
⚠️ 顶栏（y < 12% 高）和页脚（y > 88% 高）裁掉：顶栏有深色 logo 和标题，
   页脚有 CHERY 和按钮。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "ui" / "图片效果" / "13.png"


def bands(path, tag):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    H, W = a.shape[:2]
    lum = (a[:, :, 0] * 299 + a[:, :, 1] * 587 + a[:, :, 2] * 114) // 1000
    dark = lum < 130
    x0, x1 = int(W * 0.04), int(W * 0.52)
    y0, y1 = int(H * 0.12), int(H * 0.88)
    col = dark[y0:y1, x0:x1].sum(axis=1)
    thr = max(3, int((x1 - x0) * 0.004))
    print("\n%s  %s  %dx%d" % (tag, Path(path).name, W, H))
    print("  左栏深墨行带（阈值 %d 像素/行）:" % thr)
    out, i, n = [], 0, len(col)
    while i < n:
        if col[i] >= thr:
            j = i
            while j + 1 < n and col[j + 1] >= thr:
                j += 1
            if j - i >= 4:
                out.append((y0 + i, y0 + j))
            i = j + 1
        else:
            i += 1
    for a_, b_ in out:
        # 这一带里墨的水平范围
        sub = dark[a_:b_ + 1, x0:x1]
        xs = np.where(sub.any(axis=0))[0]
        print("    y %4d..%4d (高 %3d)   x %4d..%4d (宽 %4d)   %s"
              % (a_, b_, b_ - a_ + 1, x0 + xs[0], x0 + xs[-1], xs[-1] - xs[0] + 1,
                 "%.1f%%高" % (100.0 * (b_ - a_ + 1) / H)))
    return out


def main():
    shots = sys.argv[1:] or ["runs/_cover_v6.png"]
    bands(REF, "参考")
    for s in shots:
        p = Path(s)
        if not p.is_absolute():
            p = ROOT / s
        bands(p, "当前")
    print("\n怎么读：把两边的 y 带逐条对上（大标题 / 副标题 / 胶囊），"
          "高度百分比差 > 1.5 个点就值得动。")


if __name__ == "__main__":
    main()
