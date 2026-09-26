# -*- coding: utf-8 -*-
"""一次性探针：给**新给的两张**源图量「豆包AI生成」水印的位置。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_wm_probe2.py

为什么不能复用 `_wm_probe.py`：那个脚本里的窗口是**为 2656x1536 量的绝对坐标**，
而这两张是 **2304x1728**（4:3，竖一些）和 **2048x1184**。`_mk_bg.py` 的 `wm_crop`
碰到未知尺寸会**当场停**（那是故意的，防的是"按比例缩放坐标"——水印字号不跟着
图缩放）。所以这里先把右下角那块**1:1 渲染出来带标尺**，用眼睛读出窗口，
再跑逐行剖面。

**只读 + 只写 runs/ 下的两张 PNG，不碰任何产品素材。**
"""
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRCS = [
    ("detail_xq", "驾驶监测页 小瑞智能陪伴部分背景图.png"),
    ("rail_bg", "整体左栏背景图.png"),
]
# 要看的那一块：右下角 800x460（够放下水印 + 四周留白，1:1）
CORNER_W, CORNER_H = 800, 460
# 窗口候选（绝对 x 范围）。**是在上面那张 1:1 渲染图上读出来的**：
#   detail_xq 的字大约 x 1690..2230（字高 ~105px）
#   rail_bg   的字大约 x 1655..1995（字高 ~55px）
# 挨个试，挑"贴着字"的那个 —— 窗口越贴，逐行异常占比越高，判据越有分辨力
# （老那条教训：分辨力来自窗口开得对不对，不是阈值）。
CAND = {
    "detail_xq": [(1604, None), (1660, 2260), (1650, 2304), (1690, 2240), (1750, 2200)],
    "rail_bg":   [(1348, None), (1630, 2030), (1640, 2048), (1660, 2000), (1700, 1990)],
}
GK = 51
THR = 25
FRAC = 0.15
# 逐行表默认不打了（太吵）；要看就 `python _scratch/_wm_probe2.py -v`
VERBOSE = "-v" in sys.argv


def imread_u(p, flag=cv2.IMREAD_UNCHANGED):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flag)


for tag, name in SRCS:
    p = os.path.join(ROOT, "ui", "图片效果", name)
    im = imread_u(p, cv2.IMREAD_COLOR)
    if im is None:
        raise SystemExit("读不到 %s" % p)
    H, W = im.shape[:2]
    print("\n=== %s  %dx%d ===" % (name, W, H))

    # ---- 1. 右下角 1:1 带标尺渲染（给眼睛读窗口用）--------------------------
    cw, ch = min(CORNER_W, W), min(CORNER_H, H)
    x0c, y0c = W - cw, H - ch
    crop = im[y0c:H, x0c:W].copy()
    for x in range(0, cw, 50):
        cv2.line(crop, (x, 0), (x, ch), (0, 0, 255), 1)
        cv2.putText(crop, str(x0c + x), (x + 2, 14), cv2.FONT_HERSHEY_SIMPLEX,
                    0.36, (0, 0, 255), 1, cv2.LINE_AA)
    for y in range(0, ch, 50):
        cv2.line(crop, (0, y), (cw, y), (0, 255, 0), 1)
        cv2.putText(crop, str(y0c + y), (2, y + 12), cv2.FONT_HERSHEY_SIMPLEX,
                    0.36, (0, 160, 0), 1, cv2.LINE_AA)
    outp = os.path.join(ROOT, "runs", "_wm_new_corner_%s.png" % tag)
    cv2.imencode(".png", crop)[1].tofile(outp)
    print("  右下角 1:1（红=绝对 x，绿=绝对 y）-> runs/_wm_new_corner_%s.png"
          % tag)

    # ---- 2. 逐行剖面：窗口先按"右下角整块"扫，看哪些行压着水印 ------------
    # 先整块右下角（x 从 W-700 到 W），行从 H-300 到 H：这一步只用来定位行号，
    # 窗口最终由上面那张渲染图读出来。
    x0, x1 = max(0, W - 700), W
    y0w, y1w = max(0, H - 300), H
    win = im[y0w:y1w, x0:x1]
    g = cv2.cvtColor(win, cv2.COLOR_BGR2GRAY)
    res = (np.abs(g.astype(np.int16) - cv2.medianBlur(g, GK).astype(np.int16)) > THR)
    prof = res.mean(axis=1)
    print("  扫描窗 x %d..%d y %d..%d  异常总占比 %.2f%%"
          % (x0, x1, y0w, y1w, res.mean() * 100))
    hot = [y0w + i for i, v in enumerate(prof) if v > FRAC]
    for i, v in enumerate(prof):
        y = y0w + i
        if v > 0.02 and VERBOSE:
            print("    y=%4d  %5.2f%%  %s%s" % (y, v * 100,
                                                "#" * min(46, int(v * 90)),
                                                "  <== 压着水印" if v > FRAC else ""))
    if hot:
        print("  -> 这一窗里超阈值的行 y %d .. %d" % (min(hot), max(hot)))
        for margin in (0, 8, 12, 16, 24):
            cut = min(hot) - margin
            kept = prof[:max(0, cut - y0w)]           # 留下的那些行
            drop = prof[max(0, cut - y0w):]           # 扔掉的那些行
            print("     margin %2d -> 裁到 y<%4d（保留高 %4d = %.2f%%）"
                  "  留下最高 %.2f%%（要 ≤ %.0f）· 扔掉最高 %.2f%%（要 > %.0f）"
                  % (margin, cut, cut, cut * 100.0 / H,
                     (kept.max() * 100) if len(kept) else 0.0, FRAC * 100,
                     (drop.max() * 100) if len(drop) else 0.0, FRAC * 100))
    else:
        print("  ★ 这一窗没有超阈值的行 —— 水印可能不在右下 700x300 里，看图定窗口")

    # ---- 3. 窗口扫描：`wm_crop` 用的窗口（比上面那个 700 宽的关键块**窄得多**），
    # 判据的分辨力来自窗口开得对不对 —— 窗口越贴着字，逐行占比越高。
    # 这里把"字实际占的 x 范围"（上面那张渲染图上读出来的）套几个宽度试一遍，
    # 挑一个：水印行**明显**超阈值、而字上方的行**明显**不超的。
    print("  --- 窗口扫描（挑 wm_crop 要用的那个）---")
    for wx0, wx1 in CAND[tag]:
        wx0 = max(0, W - (W - wx0)) if wx0 < 0 else wx0
        wx1 = W if wx1 is None else wx1
        win2 = im[y0w:y1w, wx0:wx1]
        g2 = cv2.cvtColor(win2, cv2.COLOR_BGR2GRAY)
        r2 = (np.abs(g2.astype(np.int16)
                     - cv2.medianBlur(g2, GK).astype(np.int16)) > THR)
        p2 = r2.mean(axis=1)
        h2 = [y0w + i for i, v in enumerate(p2) if v > FRAC]
        print("    x %4d..%4d (%4d 宽)  超阈行 %s  最高一行 %.2f%%"
              % (wx0, wx1, wx1 - wx0,
                 ("y %d..%d 共 %d 行" % (min(h2), max(h2), len(h2))) if h2 else "无",
                 p2.max() * 100))
        if not h2:
            continue
        # ★ 决定性的两个数：按这个窗口 + margin，`wm_crop` 里那两条断言过不过。
        #   留下最高要 ≤ 15%，扔掉最高要 > 15% —— **两条都要留余量**，
        #   只差零点几个百分点的那种（老 rail 那张 700 宽窗口就是）不算数。
        for margin in (8, 12, 16):
            cut = min(h2) - margin
            kept = p2[:max(0, cut - y0w)]
            drop = p2[max(0, cut - y0w):]
            print("        margin %2d 裁<%4d · 留下最高 %.2f%% · 扔掉最高 %.2f%%"
                  "   %s"
                  % (margin, cut,
                     (kept.max() * 100) if len(kept) else 0.0,
                     (drop.max() * 100) if len(drop) else 0.0,
                     "OK" if ((len(kept) == 0 or kept.max() <= FRAC)
                              and drop.max() > FRAC) else "✗"))

