# -*- coding: utf-8 -*-
"""看 `runs/_bgs4_monxq.png` 的**左右两条边**：面板的描边到底落在卡片边上了没有。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_probe_monxq_edge.py

为什么单独量一次：用户的原话是「背景边框和我实际边框感觉有矛盾…不然有两个边框」。
`_shot_bgs4.py` 那张整格截图**缩在终端里看不清 5 个像素宽的描边**，
而这一条改动成不成功全在那 5 个像素上 —— 所以把左右各 60px 的窄条放大 4 倍存成
PNG 给人眼看，另外把这一行的**原始灰阶剖面逐像素打出来**（描边在剖面上是个凹口）。

判读方法（和 `_probe_frame2.py` 量源图时同一个眼光）：
  · 面板的边 = 一条**青色线**（源图灰阶 ~227..231），它两边是更亮的亮边(251)和内阴影；
  · 裁对了的话，这条凹口应该在**截图最外沿**（x 0..8 或 w-8..w）——
    也就是它和卡片自己的圆角/1px 白描边重合；
  · 如果凹口出现在 x≈20~40，那说明"裁面板"那步没生效或 CSS 又变回 `cover` 了，
    两条边框的老毛病就还在。

⚠️ 只读 `runs/_bgs4_monxq.png`、只写 `runs/_monxq_edge_*.png`。
"""
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PNG = os.path.join(ROOT, "runs", "_bgs4_monxq.png")
ROW = 60          # 取哪一行剖面（避开左上圆角）
BAND = 60         # 左右各看多少像素
MAG = 4


def imread_u(p, flag=cv2.IMREAD_COLOR):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flag)


im = imread_u(PNG)
if im is None:
    raise SystemExit("读不到 runs/_bgs4_monxq.png —— 先跑 _shot_bgs4.py")
h, w = im.shape[:2]
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY)
print("=== _bgs4_monxq.png %dx%d（截图是 scale=2 的，所以卡片是 %dx%d CSS px）==="
      % (w, h, w // 2, h // 2))


def profile(y, lo, hi, label):
    print("\n%s —— 第 %d 行的灰阶（逐像素）:" % (label, y))
    row = g[y, lo:hi].astype(int)
    for i, v in enumerate(row):
        x = lo + i
        d = v - 245          # 245 ≈ 面板内部的典型亮度，凹口 = 描边
        print("    x=%4d  %3d  (%+4d) %s" % (x, v, d,
                                             "<" * min(40, max(0, -d // 2))))


def strip(x0, x1, name):
    s = im[:, x0:x1]
    s = cv2.resize(s, ((x1 - x0) * MAG, h * MAG), interpolation=cv2.INTER_NEAREST)
    for i in range(0, s.shape[1], MAG * 5):        # 每 5 个源像素一根
        cv2.line(s, (i, 0), (i, 16), (0, 0, 255), 1)
        cv2.putText(s, str(x0 + i // MAG), (i + 2, 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.36, (0, 0, 255), 1, cv2.LINE_AA)
    p = os.path.join(ROOT, "runs", name)
    cv2.imencode(".png", s)[1].tofile(p)
    print("  -> runs/%s（源图 x %d..%d，放大 %d 倍）" % (name, x0, x1, MAG))


profile(ROW, 0, BAND, "左边缘")
profile(ROW, w - BAND, w, "右边缘")

# 顺带找一下"最暗的那一列"落在哪（描边是这一段里最暗的），给个数字，别只看图
for lo, hi, lab in ((0, BAND, "左"), (w - BAND, w, "右")):
    seg = g[ROW:ROW + 1, lo:hi].ravel()
    i = int(np.argmin(seg))
    print("\n%s边缘这一行最暗的一列：x=%d 灰阶 %d（整段 %d..%d）"
          % (lab, lo + i, seg[i], seg.min(), seg.max()))

print()
strip(0, BAND, "_monxq_edge_left.png")
strip(w - BAND, w, "_monxq_edge_right.png")


# ---- 顺带看**上下**：青色线在左右两侧一直画到哪一行 -------------------------
# 这一问的理由：`100% auto` 是"按宽度铺"，图会比卡片高、上下各切掉一截 ——
# 但"切掉"切的是**面板内部的画面**，面板的左右两条边是通高的，应该**从上沿一直到下沿**。
# 如果这条线只画到一半就没了，说明 `.mon-xq` 这个元素的盒子比卡片本身高
# （截图按 `getBoundingClientRect` 裁，会把盒子多出来的那段也裁进来），
# 那就得回头看是不是布局上还有个空档。
print("\n青色线的纵向范围（第 4 列 = 左描边）：")
col = g[:, 4].astype(int)
dark = col < 238          # 描边灰阶 ~222，卡片白边 ~254，面板内 ~244
runs = []
y = 0
while y < h:
    if dark[y]:
        y0 = y
        while y < h and dark[y]:
            y += 1
        runs.append((y0, y - 1))
    y += 1
for y0, y1 in runs:
    print("    y %4d..%4d  （%d 行）" % (y0, y1, y1 - y0 + 1))
print("    （y 是截图行，除以 2 就是卡片里的 CSS 像素；卡片高 %d CSS px）" % (h // 2))

print("\n竖向剖面（每 4 行一格）：`边` = 左边 8 列的均值（描边就在这儿），"
      "`心` = 中间那一段的均值（面板内部），`行` = 整行均值")
print("      y   CSS    边     心     行")
for y in range(0, h, 4):
    print("    %4d  %5.1f  %5.1f  %5.1f  %5.1f"
          % (y, y / 2.0, g[y, 0:8].mean(), g[y, 100:400].mean(), g[y].mean()))
