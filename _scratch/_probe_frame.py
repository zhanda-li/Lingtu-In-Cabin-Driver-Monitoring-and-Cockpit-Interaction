# -*- coding: utf-8 -*-
"""量 `驾驶监测页 小瑞智能陪伴部分背景图.png` 里**那圈玻璃面板的边框**落在哪。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_probe_frame.py

为什么要有这一步：用户原话 ——

  「驾驶监测 小瑞智能陪伴那部分背景边框和我实际边框感觉有矛盾 把背景边框和我的
    实际边框宽度弄成相等的吧 不然有两个边框」

也就是说：源图是一张**画好的面板**（自己带一圈青色描边、四周还留着一圈淡蓝底），
`cover` 铺上来之后，那圈描边落在卡片**里面**一点，和卡片自己的边（`--r-lg` 圆角 +
1px 白描边）并排 —— 看起来就是**两个边框**。要"弄成相等"，就得让背景里那圈描边
**正好落在卡片边上**：把源图四周那圈"面板外的淡蓝底"裁掉，只留面板本身。
这个脚本负责把那个框量出来。**不许按比例猜** —— 理由和 `wm_crop` 那个尺寸断言一样。

## 第一版为什么没量出来（教训，别重走）

第一版用的是"逐列算'有多少比例的像素和横向中位核差 > 25'"（照搬水印检测那套），
然后按"占比 > 50% 的列"去找边 —— **一条都没找到**（最高的列才 48.36%）。
原因：**这圈描边是柔的**，不是水印那种硬笔画。它是一条 10~15px 宽的渐变带，
残差能过 25 的地方只有它最陡的那一两个像素，所以"贯穿整列"的比例上不去；
而占比最高的那几列（x=2148 / 161）恰好是**描边最陡的那一侧**，不是描边本身。

## 这一版的做法

改成看**列均值/行均值**这条剖面：描边在剖面上是一个**局部极值**。
但整幅图自己有一条很大的慢渐变（左边偏白、右下偏蓝），直接找极值会被它带跑 ——
所以先减掉自己的**重度模糊**（`sigma=40`），只留"局部起伏"，再找极值。
这就是"detrend 之后找线"，读数的位置和眼睛在图上看到的描边是同一个地方。

⚠️ 只读 + 只写 `runs/` 下的图，不碰任何产品素材。
"""
import os
import sys

import cv2
import numpy as np

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
NAME = "驾驶监测页 小瑞智能陪伴部分背景图.png"
WM_CUT = 1582            # `_mk_bg.py` 裁水印之后的高度
SIGMA = 40.0             # detrend 用的模糊尺度（要**远大于**描边宽度）


def imread_u(p, flag=cv2.IMREAD_UNCHANGED):
    return cv2.imdecode(np.fromfile(p, dtype=np.uint8), flag)


im = imread_u(os.path.join(ROOT, "ui", "图片效果", NAME), cv2.IMREAD_COLOR)
if im is None:
    raise SystemExit("读不到源图")
H, W = im.shape[:2]
im = im[:WM_CUT]
g = cv2.cvtColor(im, cv2.COLOR_BGR2GRAY).astype(np.float32)
h, w = g.shape
print("=== %s  %dx%d（裁水印后 y<%d）===" % (NAME, W, H, WM_CUT))

colmean = g.mean(axis=0)
rowmean = g.mean(axis=1)


def detrend(prof):
    """减掉自己的重度模糊，只留局部起伏。"""
    p = prof.reshape(1, -1).astype(np.float32)
    bg = cv2.GaussianBlur(p, (0, 0), SIGMA).ravel()
    return prof - bg, bg


def show(prof, lo, hi, label, step=4):
    d, _ = detrend(prof)
    print("\n%s（x/y %d..%d，每 %d 一格；`d`= 减掉慢渐变之后的值，"
          "描边就是那个尖）:" % (label, lo, hi, step))
    seg = [(i, float(d[i])) for i in range(lo, hi, step)]
    mx = max(abs(v) for _, v in seg) or 1.0
    for i, v in seg:
        print("    %4d  d=%+7.2f  %s%s" % (i, v, "#" * int(abs(v) / mx * 40),
                                           "*" if abs(v) > 0.6 * mx else ""))


def extremes(prof, lo, hi, sign):
    """在 [lo,hi) 里找 detrend 之后的极值位置（sign=-1 找谷、+1 找峰）。"""
    d, _ = detrend(prof)
    sub = d[lo:hi] * sign
    i = int(np.argmax(sub))
    return lo + i, float(d[lo + i])


show(colmean, 120, 240, "左描边一带（列均值）")
show(colmean, 2090, 2180, "右描边一带（列均值）")
show(rowmean, 90, 200, "上描边一带（行均值）")
show(rowmean, 1480, WM_CUT, "下描边一带（行均值）")

xl = extremes(colmean, 100, 260, -1)
xr = extremes(colmean, 2050, 2200, -1)
yt = extremes(rowmean, 80, 210, -1)
yb = extremes(rowmean, 1470, WM_CUT, -1)
print("\n★ 四条边的极值位置（列/行均值上的局部极小）：")
print("   左 x=%d (d=%+.2f)   右 x=%d (d=%+.2f)" % (xl[0], xl[1], xr[0], xr[1]))
print("   上 y=%d (d=%+.2f)   下 y=%d (d=%+.2f)" % (yt[0], yt[1], yb[0], yb[1]))

# ---- 复核图：把量到的四条线画在缩略图上，眼睛过一遍 --------------------------
sc = 900.0 / w
th = cv2.resize(im, (900, int(round(h * sc))), interpolation=cv2.INTER_AREA)
for xx, c in ((xl[0], (0, 0, 255)), (xr[0], (0, 0, 255))):
    cv2.line(th, (int(xx * sc), 0), (int(xx * sc), th.shape[0]), c, 1)
for yy, c in ((yt[0], (0, 255, 0)), (yb[0], (0, 255, 0))):
    cv2.line(th, (0, int(yy * sc)), (th.shape[1], int(yy * sc)), c, 1)
cv2.putText(th, "x %d / %d   y %d / %d" % (xl[0], xr[0], yt[0], yb[0]), (8, 24),
            cv2.FONT_HERSHEY_SIMPLEX, 0.62, (0, 0, 255), 2, cv2.LINE_AA)
cv2.imencode(".png", th)[1].tofile(os.path.join(ROOT, "runs", "_frame_probe.png"))
print("复核图 -> runs/_frame_probe.png（红线=左右，绿线=上下）")

# ---- 裁出来看一眼（= 裁掉面板外那圈淡蓝底之后的样子）------------------------
crop = im[yt[0]:yb[0] + 1, xl[0]:xr[0] + 1]
print("\n裁到面板本身: x %d..%d  y %d..%d -> %dx%d（比例 %.4f）"
      % (xl[0], xr[0], yt[0], yb[0], crop.shape[1], crop.shape[0],
         crop.shape[1] / float(crop.shape[0])))
th2 = cv2.resize(crop, (760, int(round(crop.shape[0] * 760.0 / crop.shape[1]))),
                 interpolation=cv2.INTER_AREA)
cv2.imencode(".png", th2)[1].tofile(os.path.join(ROOT, "runs", "_frame_cropped.png"))
print("裁完的缩略图 -> runs/_frame_cropped.png")
