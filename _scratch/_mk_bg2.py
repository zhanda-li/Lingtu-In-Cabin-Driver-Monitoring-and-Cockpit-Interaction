# -*- coding: utf-8 -*-
"""把 `ui/图片效果/背景图1|2|3.png` 装成**每页一张**的座舱底图。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_mk_bg2.py

产出：

    ui/web/assets/bg1_wash.jpg   —— 首页 / 对话页
    ui/web/assets/bg2_wash.jpg   —— 驾驶监测 / 监测详情
    ui/web/assets/bg3_wash.jpg   —— 多媒体 / 设置 / 试音台

★ 2026-09-25 用户原话：「把首页整体大背景换成背景图1.png 多媒体页整体大背景换成
  背景图3.png 驾驶监测整体大背景换成背景图2.png 设置页面整体大背景换成背景图3.png」
  —— 三张图分给四页（多媒体和设置**共用背景图3**，那是用户点名的）。

★★ 同一轮里用户的第二句话是**这一轮真正的重点**：
  「但是整体显示 出来还是太白 就是你背景没啥用」
  所以这一轮不只是换图，还把 `.bg::after` 那层白蒙版从 **0.84/0.78/0.74** 压到
  **0.34/0.30/0.27**（见 style.css 那段）。两件事必须一起做：
  只换图不压蒙版 = 换了也看不见；只压蒙版不换图 = 原来的 `bg_wash.jpg`（1280 宽、
  7px 模糊）会露出一张模糊的城市照片，那也不是要的效果。
  ⇒ 本脚本这一轮把底图从「模糊纹理」改成「**能认出画面**」：
    1600 宽、模糊 4.0（原来是 1280 宽、模糊 7.0）。

⚠️ 和 `_mk_bg.py` 的关系：那一个管**封面**（`bg_scene.jpg`，原色不洗）和**默认底图**
  （`bg_wash.jpg`，现在只剩「没点名的那几页」在用）。两个脚本的压法故意不同，
  别为了"统一"把它们合成一个 —— 封面的观感是有意和座舱内分开的（见 style.css）。

⚠️ 水印：三张源图右下角都有「豆包AI生成」，**不裁就会被烤进产品素材**。裁法沿用
  `_mk_bg.py` 的 `wm_crop()`（同一套残差检测，只是窗口按 2730x1536 重量了一遍）。
"""

import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, "ui", "图片效果")
DST = os.path.join(ROOT, "ui", "web", "assets")

# (源文件, 产出，谁用)
JOBS = [
    ("背景图1.png", "bg1_wash.jpg", "首页 / 对话页"),
    ("背景图2.png", "bg2_wash.jpg", "驾驶监测 / 监测详情"),
    ("背景图3.png", "bg3_wash.jpg", "多媒体 / 设置 / 试音台"),
]

# ---------------------------------------------------------------- 水印检测参数
# ⚠️ 这三张是 **2730x1536**（和 `_mk_bg.py` 那两张 2656x1536 **不是一个尺寸**），
#    所以窗口**必须重量**，别把旧坐标缩放了事 —— `_mk_bg.py` 里那段注释说得很清楚。
#    量法：先把右下角带标尺渲染出来用眼睛读（本脚本会顺手存一张
#    `runs/_bg2_corner.png`），再在这块窗口里跑残差。
WM_SIZE = (2730, 1536)
WM_WIN_X = (2420, 2730)
WM_WIN_Y = (1360, 1536)
WM_GK = 51
WM_THR = 25
WM_FRAC = 0.15
WM_MARGIN = 12

WIDTH = 1600
QUALITY = 82
BLUR = 4.0


def imread_u(p):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), cv2.IMREAD_COLOR)


def wm_crop(im, name):
    """裁掉右下角那行「豆包AI生成」，返回裁好的图，并把量到的东西全打出来。"""
    H, W = im.shape[:2]
    if (W, H) != WM_SIZE:
        raise SystemExit("源图 %s 是 %dx%d，水印窗口是按 %dx%d 量的 —— 重量一遍。"
                         % (name, W, H, *WM_SIZE))
    x0, x1 = WM_WIN_X
    y0, y1 = WM_WIN_Y
    g = cv2.cvtColor(im[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
    res = (np.abs(g.astype(np.int16) - cv2.medianBlur(g, WM_GK).astype(np.int16)) > WM_THR)
    prof = res.mean(axis=1)
    hot = [y0 + i for i, v in enumerate(prof) if v > WM_FRAC]
    print("  %s 窗口 x %s y %s · 异常总占比 %.2f%% · 行最高 %.2f%%"
          % (name, WM_WIN_X, WM_WIN_Y, res.mean() * 100, prof.max() * 100))
    if not hot:
        raise SystemExit(
            "%s：窗口里没找到水印（最高一行才 %.2f%%，阈值 %.2f）—— **别当成"
            "'这次没有水印'**，去看 runs/_bg2_corner.png 再决定。"
            % (name, prof.max() * 100, WM_FRAC))
    top, bot = min(hot), max(hot)
    cut = top - WM_MARGIN
    print("     水印行 y %d..%d（高 %d）-> 裁到 y<%d（保留 %d = %.2f%%）"
          % (top, bot, bot - top + 1, cut, cut, cut * 100.0 / H))
    kept = prof[:cut - y0].max() * 100
    drop = prof[cut - y0:].max() * 100
    print("     留下的行最高 %.2f%%（要 ≤ %.2f）· 扔掉的行最高 %.2f%%（要 > %.2f）"
          % (kept, WM_FRAC * 100, drop, WM_FRAC * 100))
    assert kept <= WM_FRAC * 100, "裁完还有行超阈值：水印顶边没盖住"
    assert drop > WM_FRAC * 100, "扔掉的行里没有水印：裁多了"
    return im[:cut]


def emit(im, name, width=WIDTH, quality=QUALITY, blur=BLUR):
    sc = float(width) / im.shape[1]
    out = cv2.resize(im, (width, int(round(im.shape[0] * sc))),
                     interpolation=cv2.INTER_AREA)
    if blur:
        out = cv2.GaussianBlur(out, (0, 0), blur)
    p = os.path.join(DST, name)
    cv2.imencode(".jpg", out, [cv2.IMWRITE_JPEG_QUALITY, quality])[1].tofile(p)
    print("  %-16s %4dx%-4d %7.1f KB" % (name, out.shape[1], out.shape[0],
                                         os.path.getsize(p) / 1024))
    return out


def main():
    os.makedirs(DST, exist_ok=True)
    washed = []
    for src, dst, who in JOBS:
        p = os.path.join(SRC_DIR, src)
        im = imread_u(p)
        if im is None:
            raise SystemExit("读不到 %s" % p)
        print("=== %s  %dx%d  -> %s（%s）" % (src, im.shape[1], im.shape[0], dst, who))
        # 第一张顺手把右下角存下来，给人眼看水印位置对不对
        if not washed:
            corner = im[WM_WIN_Y[0]:, WM_WIN_X[0]:].copy()
            sc = 640.0 / corner.shape[1]
            corner = cv2.resize(corner, (640, int(corner.shape[0] * sc)),
                                interpolation=cv2.INTER_NEAREST)
            cv2.imencode(".png", corner)[1].tofile(
                os.path.join(ROOT, "runs", "_bg2_corner.png"))
            print("     对照图 -> runs/_bg2_corner.png（右下角窗口，眼睛看一遍水印在哪）")
        im = wm_crop(im, src)
        washed.append(emit(im, dst))

    # 白蒙版档位对照图：**这一次要一起给**，因为"太白"就是它造成的。
    # 左到右：0.22 / 0.30 / 0.38（现在的 0.78 自己站一格，好对比）。
    strip = None
    for w in (0.22, 0.30, 0.38, 0.78):
        wash = (washed[0].astype(np.float32) * (1 - w) + 255 * w).astype(np.uint8)
        wash = cv2.resize(wash, (560, int(wash.shape[0] * 560.0 / wash.shape[1])))
        cv2.putText(wash, ("white %.2f" % w).encode(), (14, 34),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.0, (20, 20, 20), 2, cv2.LINE_AA)
        strip = wash if strip is None else np.hstack([strip, wash])
    op = os.path.join(ROOT, "runs", "_bg_wash_levels2.png")
    cv2.imencode(".png", strip)[1].tofile(op)
    print("\n白蒙版对照图 -> runs/_bg_wash_levels2.png（左到右 0.22 / 0.30 / 0.38 / 现在的 0.78）")


main()
