# -*- coding: utf-8 -*-
"""量封面两个「看不清」到底差多少对比度 —— 标题的「智行」那两个字、和小瑞的腿。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_cov_contrast.py

判据只有一条：**笔画亮度 vs 紧邻背景亮度**（WCAG 对比度 (L1+.05)/(L2+.05)）。
测出来是几，就报几 —— 不猜「是不是新底图害的」。

分三段量标题：『灵途』『智行』『与你同行』。三段的**遮罩是同一张、渐变是同一条**,
所以三段如果差得多，差的就是**渐变在横向上的位置**（`100deg` 那条亮带）。
"""
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SHOT = os.path.join(ROOT, "runs", "_cov_cover.png")


def lum(bgr):
    """相对亮度（sRGB 线性化后 0.2126R+0.7152G+0.0722B）。"""
    x = bgr[..., ::-1].astype(np.float64) / 255.0            # BGR -> RGB
    x = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    return 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]


def ratio(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def band(bgr, x0, x1, y0, y1, label):
    """一条横带里：笔画 = 最暗的 8 分位；背景 = 最亮的 60 分位（避开飘带的亮部）。"""
    L = lum(bgr[y0:y1, x0:x1])
    stroke = float(np.percentile(L, 8))
    bg = float(np.percentile(L, 60))
    r = ratio(bg, stroke)
    print("  %-10s x %4d..%-4d y %3d..%-3d  笔画 L=%.3f  背景 L=%.3f  对比度 %.2f:1  %s"
          % (label, x0, x1, y0, y1, stroke, bg, r,
             "★偏低" if r < 3.0 else ("勉强" if r < 4.5 else "OK")))
    return stroke, bg, r


def main():
    im = cv2.imdecode(np.fromfile(SHOT, dtype=np.uint8), cv2.IMREAD_COLOR)
    print("截图 %s  %dx%d" % (os.path.basename(SHOT), im.shape[1], im.shape[0]))
    print("\n[1] 封面大标题 —— 三段（同一张遮罩 + 同一条渐变，差的是亮带落在哪一段）")
    # 标题墨迹带：由 _cmp_geo.py 量过，屏上 y≈258..369；横向 13.png 里是 795px 宽，
    # 从 x≈95 起。这里按四等分切三段量（灵途 / 智行 / 与你同行）。
    for lab, a, b in (("灵途", 95, 340), ("智行", 340, 590), ("与你同行", 590, 900)):
        band(im, a, b, 265, 360, lab)

    print("\n[2] 小瑞的腿 —— 腿身 vs 紧邻的背景（左右各取一条竖直参考带）")
    for lab, a, b in (("左腿", 1010, 1060), ("右腿", 1170, 1220)):
        band(im, a, b, 700, 795, lab)
    for lab, a, b in (("背景(左)", 856, 884), ("背景(右)", 1346, 1380)):
        band(im, a, b, 700, 795, lab)

    print("\n[3] 腿内部**竖向**的亮度爬升（看下半身是不是被一层白往下冲淡）")
    print("    y     左腿 L   右腿 L   左背景 L  右背景 L   腿-背景")
    for y in range(620, 810, 20):
        l1 = float(lum(im[y:y + 12, 1010:1060]).mean())
        l2 = float(lum(im[y:y + 12, 1170:1220]).mean())
        b1 = float(lum(im[y:y + 12, 856:884]).mean())
        b2 = float(lum(im[y:y + 12, 1346:1380]).mean())
        print("  %4d   %6.3f  %6.3f   %6.3f  %6.3f    %+.3f"
              % (y, l1, l2, b1, b2, (l1 + l2) / 2 - (b1 + b2) / 2))

    print("\n[4] 脚下那条发光地台（.cover-r .mascot::after）在屏上的位置")
    print("   槽 44x46rem = 657x687px，画面 x884..1344 y119..806，脚底 = 槽底 = 806")
    print("   `bottom:-6%` = -41px -> 元件 y 737..847（高 16% = 110px），**白心在 y≈792**")
    print("   脚在 806 —— 白心比脚还高 14px，正压在小腿/脚踝上。这是嫌疑点，下面用开关法验。")


main()
