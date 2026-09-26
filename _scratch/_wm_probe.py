# -*- coding: utf-8 -*-
"""一次性探针：量 `背景.png` / `首页背景.png` 右下角那个「豆包AI生成」水印**在哪几行**。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_wm_probe.py

★ 第一版探针**失败了，记在这里免得重走**：拿"整行 vs 横向中位核 K=61"做残差，
  在**整幅宽度**上统计异常像素占比 —— 结果是搜索区里**每一行都报警**（5%~29%）。
  不是水印大，是**这张图本来就满是城市纹理**，K=61 相对 2656 宽太小，
  真实画面内容全被算成了"异常"。**判据的分辨力来自"窗口开得对不对"，不是来自阈值。**

现在这一版把窗口收到**水印实际所在的那一小块**（位置是先把右下角带标尺渲染出来
用眼睛读的，见 runs/_wm_corner.png），并且用 **2D 中位核**（51×51，比笔画宽、比
画面结构窄）去掉背景，只留笔画。**只读、只打印，不写任何文件。**
"""
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRCS = ["背景.png", "首页背景.png"]

# 窗口：比水印本身略宽一点。**这是量出来的框**（runs/_wm_corner.png 上读的）：
#   水印文字 x≈2378..2625、y≈1443..1506（两张源图都一样，都是 2656x1536）。
WIN_X = (2330, 2660)
WIN_Y = (1380, 1536)
GK = 51          # 2D 中位核：要**宽于笔画**（笔宽约 15px），**窄于**画面的大块结构
THR = 25         # 水印是浅色叠加，和背景差 30~60 灰阶；25 留一点余量
# ★ 0.02 是**错的**，会连斜向光带一起收进来（实测光带 2%~9.2%，见下面那张逐行表）——
#   于是 min(hot) 落在 1380，裁掉 10% 还裁不干净（残余 54.91%）。
#   0.15 落在"光带最高 9.2%"和"水印最低 19%"中间那道空档里，是**量出来的**。
FRAC = 0.15      # 一行里超过这个占比就算"这一行压着水印"


def imread_u(p, flag=cv2.IMREAD_UNCHANGED):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flag)


for name in SRCS:
    p = os.path.join(ROOT, "ui", "图片效果", name)
    im = imread_u(p, cv2.IMREAD_COLOR)
    H, W = im.shape[:2]
    print("\n=== %s  %dx%d ===" % (name, W, H))

    x0, x1 = WIN_X
    y0w, y1w = WIN_Y
    win = im[y0w:y1w, x0:x1]
    g = cv2.cvtColor(win, cv2.COLOR_BGR2GRAY)
    med = cv2.medianBlur(g, GK)
    res = (np.abs(g.astype(np.int16) - med.astype(np.int16)) > THR)
    prof = res.mean(axis=1)          # 窗口内逐行的异常占比

    print("  窗口 x %d..%d  y %d..%d   异常总占比 %.2f%%"
          % (x0, x1, y0w, y1w, res.mean() * 100))
    print("  逐行（源图 y）:")
    hot = []
    for i, v in enumerate(prof):
        y = y0w + i
        if v > FRAC:
            hot.append(y)
        if i % 4 == 0 or v > FRAC:
            bar = "#" * min(46, int(v * 90))
            print("    y=%4d  %5.2f%%  %s%s" % (y, v * 100, bar,
                                                "  <== 压着水印" if v > FRAC else ""))
    if not hot:
        print("  ★ 窗口内没有任何一行超阈值 —— 没找到水印")
        continue
    top, bot = min(hot), max(hot)
    print("  -> 水印行 y %d .. %d（高 %d）" % (top, bot, bot - top + 1))

    # 裁到水印上方留一点余量，再看残留 —— 余量必须是**验证过的**，不是拍的
    for margin in (0, 8, 16, 24):
        cut = top - margin
        tail = prof[max(0, cut - y0w):]
        print("     margin %2d -> 裁到 y<%4d（保留高 %4d = %.2f%%）  残余最大行 %.2f%%"
              % (margin, cut, cut, cut * 100.0 / H,
                 (tail.max() * 100) if len(tail) else 0.0))
