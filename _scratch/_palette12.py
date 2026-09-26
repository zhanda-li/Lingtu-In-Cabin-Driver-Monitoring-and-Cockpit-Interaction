# -*- coding: utf-8 -*-
"""从 12.png 取样出调色板 —— **照着色卡做，不靠肉眼估**。

    D:/Anaconda3/envs/dms/python.exe _scratch/_palette12.py

两路取样：
  1. K-means 出 12 个主色（按占比）—— 看整体落在哪几个色上；
  2. 指定区块的中位数 —— 具体是"卡片底多亮""强调色多饱和"这种要落到 CSS 里的值。

⚠️ 区块坐标是**目测**在 2000x1124 的展示图上框的，再乘 1.424 换算回原图。
   框错了会取到别的东西 —— 所以每一项都要跟主色表对得上才算数，
   对不上就挪框重取，别硬用。
"""
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SRC = Path(r"D:\sdk_env_v1.12.1\dms_project\ui\图片效果\12.png")


def hexs(c):
    r, g, b = (int(round(float(v))) for v in c[:3])
    return "#%02X%02X%02X  rgb(%3d,%3d,%3d)" % (r, g, b, r, g, b)


im = Image.open(SRC).convert("RGB")
W, H = im.size
print("12.png %dx%d" % (W, H))

sm = np.asarray(im.resize((W // 6, H // 6))).astype(np.float32).reshape(-1, 3)
crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.5)
_, lab, cen = cv2.kmeans(sm, 12, None, crit, 6, cv2.KMEANS_PP_CENTERS)
cnt = np.bincount(lab.ravel(), minlength=12)
print("\n== 全图 12 个主色（按占比）==")
for i in np.argsort(-cnt):
    print("   %5.1f%%  %s" % (cnt[i] / cnt.sum() * 100, hexs(cen[i])))

# 关键区块。坐标 = 展示图目测值 x 1.424（原图 2848x1600 / 展示 2000x1124）
BOX = {
    "天空底(顶部中间)": (900, 40, 1500, 150),
    "左栏玻璃卡": (55, 300, 270, 700),
    "中央玻璃卡内": (700, 420, 1150, 560),
    "选中态药丸(对话)": (60, 520, 280, 620),
    "强调按钮(开始导航)": (1000, 990, 1330, 1060),
    "小瑞围巾(蓝)": (1620, 700, 1760, 780),
    "底部气候栏": (700, 1330, 1200, 1420),
    "顶栏底": (600, 20, 1100, 90),
}
print("\n== 指定区块中位数 ==")
for k, (x0, y0, x1, y1) in BOX.items():
    x0, y0, x1, y1 = (int(v) for v in (x0, y0, x1, y1))
    blk = np.asarray(im.crop((x0, y0, x1, y1))).reshape(-1, 3).astype(np.float32)
    m = np.median(blk, 0)
    mn, mx = blk.min(0), blk.max(0)
    print("   %-20s %s   跨度 %s ~ %s" % (k, hexs(m), hexs(mn), hexs(mx)))
