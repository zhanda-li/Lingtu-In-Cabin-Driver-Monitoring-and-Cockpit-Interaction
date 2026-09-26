# -*- coding: utf-8 -*-
"""一次性探针：同一个 media.html，在不同视口尺寸下，纵向空间是怎么分配的。

    python _scratch/_probe_heights.py

起因：用户在**自己的浏览器窗口**里看到「小瑞 正在播放《…》那一栏上方有一块空白」，
而 `_check_media_lib.py` 在 1672×940 这个固定窗口里量到的是"底下空 0px、不用滚"。
两者不矛盾 —— 版式的纵向是这么来的：

    `.sub-body` 的高度 = 视口高 − 顶栏 − 底栏 − 内外边距   （**跟着视口走**）
    卡片的高度          = 一堆 rem                              （**跟着 1rem 走**）

而 `1rem = clamp(11px, min(100vh/58, 100vw/112), 22px)` —— **取的是宽高里小的那个**。
所以窗口一旦比设计比例**更高**（1440p / 16:10 屏 / 只是把窗口拉高），
`100vh/58` 先到顶、`1rem` 反而被宽度卡住不再变大，卡片就此定死，
而 `.sub-body` 还在跟着视口长 —— **多出来的高度全变成底下的空白**，
把那一栏顶到屏幕最下面。用户看到的就是这个。

⚠️ 这个脚本**只量、不判**。它存在的意义是：以后再有"某一块上面空了一截"，
   先跑它、看是哪一档出的问题，别对着一个尺寸猜。

⚠️ 自带宽高（端口 8799、`--source demo`，跑完自己收）。别跟回归脚本同时跑。
"""
import asyncio, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_pages import Session

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT, CDP = 8799, 9419
BASE = "http://127.0.0.1:%d" % PORT

# 设计基线放最前面，其余按"更宽/更高"的常见窗口排。
SIZES = [(1672, 940), (1672, 1040), (1672, 1180), (1920, 980), (1440, 900), (1280, 800)]

Q = ("(() => { try {"
     " const g=(s)=>{const e=document.querySelector(s); if(!e) return null;"
     " const b=e.getBoundingClientRect();"
     " return {t:Math.round(b.top),b:Math.round(b.bottom),h:Math.round(b.height),"
     " l:Math.round(b.left),w:Math.round(b.width)};};"
     " const sb=g('.sub-body'); const lib=g('.mp-lib'); const talk=g('.talk');"
     " const mg=g('.mp-grid'); const xq=g('.mp-xq');"
     " return JSON.stringify({"
     " innerH:window.innerHeight, innerW:window.innerWidth,"
     " rem:parseFloat(getComputedStyle(document.documentElement).fontSize),"
     " sub:sb, talk:talk, grid:mg, lib:lib, xq:xq,"
     " subScroll:(() => {const e=document.querySelector('.sub-body');"
     "   return e ? e.scrollHeight : null;})()});"
     " } catch (e) { return JSON.stringify({err:String((e && e.message) || e)}); } })()")


async def main():
    log = open(os.path.join(ROOT, "runs", "_probe_heights.log"), "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", str(PORT), "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/music.json", timeout=2).read(10); break
        except Exception: time.sleep(0.5)
    try:
        async with Session(CDP) as S:
            await S.cmd("Page.navigate", {"url": BASE + "/media.html"})
            await asyncio.sleep(3.0)
            print("视口(宽×高)     1rem   sub-body  内容  卡片底→sub底  sub底→那一栏  那一栏高  结论")
            for (w, h) in SIZES:
                # ⚠️ 用 CDP 改视口，不是重开浏览器 —— `100vh/100vw` 那套 clamp
                #    跟着它变，所以量出来的就是"窗口这么大时的真实版式"。
                await S.cmd("Emulation.setDeviceMetricsOverride",
                            {"width": w, "height": h, "deviceScaleFactor": 1,
                             "mobile": False})
                await asyncio.sleep(1.1)
                g = await S.js(Q)
                if g is None or g.get("err"):
                    print("%-14s !! %s" % ("%dx%d" % (w, h),
                                           (g or {}).get("err", "表达式抛了")))
                    continue
                sub, lib, talk, mg = g["sub"], g["lib"], g["talk"], g["grid"]
                below = sub["b"] - lib["b"]          # 卡片底 -> sub-body 可视底
                seam = talk["t"] - sub["b"]          # sub-body 可视底 -> 那一栏顶
                blank = below + seam                 # 用户眼里的"那一栏上方那块空白"
                verdict = ("贴住了" if blank <= 14 else
                           "空 %d px ← 就是这块" % blank if blank > 40 else "差 %d px" % blank)
                print("%-14s %5.2f  %6d  %5d  %11d  %10d  %8d  %s"
                      % ("%d×%d" % (w, h), g["rem"], sub["h"], g["subScroll"],
                     below, seam, talk["h"], verdict))
                print("               网格高 %d（卡片 %d~%d）  列表高 %d"
                      % (mg["h"], lib["t"], lib["b"],
                         (await S.js("(() => {const e=document.querySelector('.tracks');"
                                     " return e ? Math.round(e.getBoundingClientRect().height)"
                                     " : -1;})()")) or -1))
            await S.cmd("Emulation.clearDeviceMetricsOverride")
    finally:
        srv.terminate(); time.sleep(0.8)
        if srv.poll() is None: srv.kill()
        log.close()

asyncio.run(main())
