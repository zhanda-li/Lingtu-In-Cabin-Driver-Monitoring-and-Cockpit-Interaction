# -*- coding: utf-8 -*-
"""量化 `cheer` 那一格：**白身体**和**白背景**到底能不能用颜色分开。

    python _scratch/_probe_cheer.py [格名]

只在 `(min通道, R-B)` 这个平面上打点，不做任何判定 —— 因为前四版都死在
"先想判据再量数据"。这一版的顺序反过来：**先量，看两堆点分不分得开**。

输出三样：
  1. 若干条竖线上的逐点 RGB / min / R-B（人工看趋势）
  2. 手工标出的"肯定是身体"和"肯定是背景"的框，各自的 (min, R-B) 分布
  3. 这两堆点在 (min, R-B) 上的**重叠率** —— 重叠高就说明这条判据在这格上
     根本不成立，别再加参数调了。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).parent))
from _mk_xiaorui16 import CELLS, CN, SRC   # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 手工框：坐标是**相对格子左上角**的像素（不是全图），看 QA 放大图定的。
#   (x0, y0, x1, y1, 是不是身体)
BOXES = {
    "cheer": [(48, 62, 70, 82, True),    # 肚子正中最亮那块
              (66, 78, 84, 100, True),   # 右胯到右腿
              (6, 6, 26, 26, False),     # 左上角背景（白）
              (96, 6, 114, 26, False),   # 右上角背景（白）
              (50, 120, 70, 138, False)],  # 正下方背景（圆盘下缘外）
    "go": [(40, 60, 60, 80, True), (5, 5, 25, 25, False), (95, 5, 115, 25, False)],
    "wave": [(40, 60, 62, 84, True), (4, 4, 24, 24, False), (95, 4, 115, 24, False)],
}

name = (sys.argv[1:] or ["cheer"])[0]
win = next(c for c in CELLS if c[4] == name)
x0, y0, x1, y1, _ = win
sub = np.asarray(Image.open(SRC).convert("RGB").crop((x0, y0, x1, y1))).astype(np.float32)
print("%s %s  格 %dx%d" % (name, CN[name], sub.shape[1], sub.shape[0]))

mn = sub.min(2)
rb = sub[..., 0] - sub[..., 2]

print("\n-- 竖直中线逐点（每 6 行一个采样，看 min / R-B 怎么变）--")
cx = sub.shape[1] // 2
print("   y   RGB             min    R-B")
for y in range(0, sub.shape[0], 6):
    r, g, b = sub[y, cx]
    print("  %3d  (%3d,%3d,%3d)   %3d   %+5.0f" % (y, r, g, b, mn[y, cx], rb[y, cx]))

body, back = [], []
for bx0, by0, bx1, by1, isbody in BOXES.get(name, []):
    blk_m = mn[by0:by1, bx0:bx1].ravel()
    blk_r = rb[by0:by1, bx0:bx1].ravel()
    tag = "身体" if isbody else "背景"
    print("\n[%s] 框 (%d,%d)-(%d,%d)  %d 点" % (tag, bx0, by0, bx1, by1, blk_m.size))
    print("   min:  中位 %.0f  5%%->95%%  %.0f -> %.0f" % (
        np.median(blk_m), np.percentile(blk_m, 5), np.percentile(blk_m, 95)))
    print("   R-B:  中位 %+.0f  5%%->95%%  %+.0f -> %+.0f" % (
        np.median(blk_r), np.percentile(blk_r, 5), np.percentile(blk_r, 95)))
    (body if isbody else back).append((blk_m, blk_r))

if body and back:
    bm = np.concatenate([b[0] for b in body]); br = np.concatenate([b[1] for b in body])
    km = np.concatenate([b[0] for b in back]); kr = np.concatenate([b[1] for b in back])
    print("\n== 两堆点在这条判据上分不分得开 ==")
    # 判据：「背景 = min>=LIGHT 且 R-B<=RBM」，看两堆各自被这条规则命中的比例
    for LIGHT, RBM in [(205, 3), (200, 0), (190, 8), (215, 0)]:
        hit_b = ((bm >= LIGHT) & (br <= RBM)).mean()
        hit_k = ((km >= LIGHT) & (kr <= RBM)).mean()
        print("   LIGHT=%3d R-B<=%+d :  身体被判成背景 %4.1f%%   背景被判成背景 %4.1f%%"
              % (LIGHT, RBM, hit_b * 100, hit_k * 100))
    # 单轴也看一眼：也许 R-B 单独就能分
    print("   R-B 单独: 身体中位 %+.0f  背景中位 %+.0f" % (np.median(br), np.median(kr)))
    print("   min 单独: 身体中位 %.0f  背景中位 %.0f" % (np.median(bm), np.median(km)))
