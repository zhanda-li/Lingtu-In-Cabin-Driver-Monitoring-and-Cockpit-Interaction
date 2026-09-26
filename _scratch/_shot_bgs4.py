# -*- coding: utf-8 -*-
"""两张新底图的"看一眼"：驾驶监测那格「小瑞 · 智能陪伴」+ 全站左栏那张卡。

    D:\\Anaconda3\\envs\\dms\\python.exe -u _scratch/_shot_bgs4.py

为什么单独写一个（不并进 `_shot_bgs3.py`）：那个是**第十二次改版**那三张的
"看一眼"脚本，它的 `SHOTS` 表里写死了 `.mp-hero`/`.mp-lib`/`.livecard` 三个靶子；
这一轮的两个靶子（`.mon-xq`、`.rail-card`）一个都不重合。按仓库的习惯，
每一轮的"看一眼"脚本跟着那一轮走，名字带轮次，别把上一轮的靶子搅进来 ——
过几轮回头查"那次换了什么、当时看的是什么"时，这份文件自己说得清。

## 它证什么、不证什么

  · 证：**算出来的** background-image 真的是新图（CSS 里写了不等于浏览器认了，
    `html[data-theme="light"] .card` 那条特指度压掉 `.mon-xq` 的坑就是这么现形的）；
  · 证：截图里那两格的**实际观感**（落盘给人眼看）；
  · 证：左栏上那四个入口的**文字对比度**（从截图里量，p8=笔画 / p60=底），
    这是 `_mk_bg.py` 那个"按源图 p05 算"的**屏幕侧对照** ——
    两边都过才算数（源图那侧偏保守，屏幕侧受 `cover` 裁切和卡上其它元素影响）。
  · **不证**：好不好看（人眼的事，截图在那儿）。
⚠️ 只读不写：不点任何按钮，只 goto + 截图 + 量像素。
"""
import asyncio
import base64
import os
import sys

import cv2
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_pages import Session          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "runs")

# 端口和其它脚本错开：9411 _check_pages / 9429 _check_theme2 / 9471 _check_bg /
# 9481 _check_railxr / 9491 _probe_newbgs（+ _shot_bgs3）。
CDP = 9495

# (路径, [(选择器, 落盘名)])
SHOTS = [
    # 左栏在每一页上都有，挑首页拍一张、再挑多媒体拍一张（那一页卡片最多，
    # 左栏和压了纱的卡并排看，最能看出"这张卡是不是洗过头了"）。
    ("/index.html",  [(".rail-card", "_bgs4_rail_home.png")]),
    ("/detail.html", [(".mon-xq", "_bgs4_monxq.png"),
                      (".rail-card", "_bgs4_rail_detail.png")]),
    ("/media.html",  [(".rail-card", "_bgs4_rail_media.png")]),
]

# 单独报一次"生效的底图"：这几个选择器各页都要念一遍
WATCH = [".mon-xq", ".rail-card", ".mp-hero"]
WATCH_PAGES = ["/index.html", "/detail.html", "/media.html"]

# 四行入口上那两档字色（浅色主题），从 style.css 的变量表里抄的
INK_NAV = "#33689E"       # --ink-4，普通导航项
INK_ACTIVE = "#1E7FD8"    # --accent，选中那一项
NAV_BAND = 0.30           # 左栏"四个入口"占卡片上部的比例（见 _mk_bg.py 的 BAND_TOP_FRAC）


def _q(s):
    return "'" + s.replace("'", "\\'") + "'"


def _rect_js(sel):
    """某个选择器的盒子（页面坐标）。**拆成三段纯字符串拼**，别用 f-string 拼
    带花括号的 JS 字面量 —— `_shot_bgs3.py` 的注释里记着那次括号配平崩的教训。"""
    return ("(function(){const e=document.querySelector(" + _q(sel) + ");"
            "if(!e)return null;const b=e.getBoundingClientRect();"
            "return JSON.stringify({x:b.left+window.scrollX,"
            "y:b.top+window.scrollY,width:b.width,height:b.height});"
            "})()")


def _bg_js(sels):
    """念出几个选择器**算出来的**底图（前 80 字符够认了），返回一个对象。

    ⚠️ 每个选择器都要**先判在不在**：`.mon-xq` 只在 detail.html、`.mp-hero` 只在
       media.html，直接 `getComputedStyle(document.querySelector('...'))` 会在别的页
       对 `null` 取值、整段 JS 抛错，`S.js` 于是回 `None` —— 而这里的报错是
       `TypeError: 'NoneType' object is not iterable`，**看不出真正的原因**。
       （第一版就是这么写的，已经在 index.html 上崩过一次。）
    """
    parts = ",".join(
        "%s:(function(){const e=document.querySelector(%s);"
        "if(!e)return '(这一页没有这个选择器)';"
        "return getComputedStyle(e).backgroundImage.slice(0,80);})()"
        % (_q(s), _q(s)) for s in sels)
    return "(function(){return {" + parts + "}})()"


def lum(bgr):
    """相对亮度（sRGB 线性化后 0.2126R+0.7152G+0.0722B）。
    和 `_cov_contrast.py` / `_mk_bg.py` 用的是同一个公式，三处必须一致。"""
    x = bgr[..., ::-1].astype(np.float64) / 255.0
    x = np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)
    return 0.2126 * x[..., 0] + 0.7152 * x[..., 1] + 0.0722 * x[..., 2]


def ratio(l1, l2):
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


def ink_lum(rgb):
    v = np.array([int(rgb[i:i + 2], 16) for i in (1, 3, 5)], dtype=np.float64) / 255.0
    v = np.where(v <= 0.04045, v / 12.92, ((v + 0.055) / 1.055) ** 2.4)
    return float(0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2])


def nav_contrast(png, tag):
    """左栏截图上半段（四个入口）里的文字对比度。

    ⚠️ 估法：这一段里**笔画 = 最暗的 8 分位、底 = 最亮的 …不，是 60 分位**。
       分位法是 `_cov_contrast.py` 定的：这一带绝大部分面积是底、少部分是字，
       所以 p60 落在底上、p8 落在笔画上。**别改成"取最暗/最亮"** ——
       最暗那一个像素可能是抗锯齿的边，最亮那个可能是卡片上的一道高光。
    ⚠️ 量的是**截图**，所以它包含了白纱、`cover` 的裁切、以及卡上其它元素;
       `_mk_bg.py` 那个"按源图 p05 算"的数偏保守（把看不见的部分也算进去了），
       两个数**不是一回事、也不该相等**，都过 4.5 就够。
    """
    im = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
    h, w = im.shape[:2]
    band = im[:int(h * NAV_BAND), :]
    L = lum(band)
    bg = float(np.percentile(L, 60))
    stroke = float(np.percentile(L, 8))
    print("     %-22s %dx%d  底 %.3f 笔画 %.3f -> 导航项 %.2f:1  选中项 %.2f:1"
          % (tag, w, h, bg, stroke,
             ratio(bg, ink_lum(INK_NAV)), ratio(bg, ink_lum(INK_ACTIVE))))
    return im


async def shot(S, name):
    r = await S.cmd("Page.captureScreenshot", {"format": "png"})
    p = os.path.join(OUT, name)
    with open(p, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    print("  %-26s %7.1f KB" % (name, os.path.getsize(p) / 1024))
    return p


async def main():
    async with Session(CDP) as S:
        for path, crops in SHOTS:
            await S.goto(path, 2.6)
            await shot(S, "_bgs4_full" + path.replace("/", "_").replace(".html", ".png"))
            for sel, name in crops:
                box = await S.js(_rect_js(sel))
                if not box:
                    print("  !! %s 没找到 %s" % (path, sel))
                    continue
                r = await S.cmd("Page.captureScreenshot", {
                    "format": "png", "captureBeyondViewport": True,
                    "clip": dict(box, scale=2)})
                if not r.get("data"):
                    print("  !! %s 截不到 %s" % (path, sel))
                    continue
                png = base64.b64decode(r["data"])
                with open(os.path.join(OUT, name), "wb") as f:
                    f.write(png)
                print("  %-26s %7.1f KB   <- %s" % (name, len(png) / 1024, sel))
                if sel == ".rail-card":
                    nav_contrast(png, name)

        # 生效的底图（CSS 里写了不等于浏览器认了 —— 这一条是那个特指度坑的探针）
        print("\n=== 生效的底图 ===")
        for path in WATCH_PAGES:
            await S.goto(path, 1.8)
            print("  %s" % path)
            for sel, val in (await S.js(_bg_js(WATCH)) or {}).items():
                print("    %-12s %s" % (sel, val))
        errs = [e for e in S.errs if "camera" not in str(e)]
        print("\n控制台错误 %d 条%s" % (len(errs), ("：" + str(errs[:4])) if errs else ""))


asyncio.run(main())
