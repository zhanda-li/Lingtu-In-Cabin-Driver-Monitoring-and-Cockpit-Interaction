# -*- coding: utf-8 -*-
"""三张新区块底图的"看一眼"：多媒体两张卡 + 驾驶监测没摄像头那一格。

    PYTHONIOENCODING=utf-8 D:\\Anaconda3\\envs\\dms\\python.exe -u \
        _scratch/_shot_bgs3.py 8790

为什么单独写一个：这一轮（2026-09-25 第十二次改版）动了三处**只有截图能判**的东西 ——
  · `.mp-hero` / `.mp-lib` 的底图铺上去之后，卡片上的字**还读不读得出**；
  · 「我的音乐」那一列行是 `rgba(255,255,255,.42)` 的半透明白，量不出"音符还看不看得见"；
  · 驾驶监测那一格要验的是**整张 `.stage-svg` 真的淡出**（不然照片一个像素都不露）。
这三件事读 CSS 都能读出自以为的答案，只有图上不是。

⚠️ 只读不写：不点任何按钮，只 goto + 截图。
⚠️ 收尾靠 `Session.__aexit__`（按 `--remote-debugging-port` 收，不按进程名 ——
   按进程名会关掉用户的浏览器，见记忆 [[windows-dev-env]]）。
"""
import asyncio
import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_pages import Session, BASE  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "runs")

# 每张图截什么：路径、等到什么时候、要不要把某个元素**单独**再截一张
SHOTS = [
    ("/media.html", 2.6, [
        (".mp-hero", "_bgs3_hero.png"),
        (".mp-lib", "_bgs3_lib.png"),
    ]),
    # 8790 是 `--source demo` 起的：`d.source !== 'cam'` -> `headMode('none')`
    # -> 整张 svg 淡出、`#noFace` 露面。正是要拍的那一档。
    ("/detail.html", 2.6, [
        (".livecard", "_bgs3_camoff.png"),
    ]),
]


async def shot(S, name):
    r = await S.cmd("Page.captureScreenshot", {"format": "png"})
    p = os.path.join(OUT, name)
    with open(p, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    print("  %-24s %7.1f KB" % (name, os.path.getsize(p) / 1024))
    return p


async def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8790"
    async with Session(9491) as S:
        for path, wait, crops in SHOTS:
            await S.goto(path, wait)
            await shot(S, "_bgs3_full" + path.replace("/", "_").replace(".html", ".png"))
            for sel, name in crops:
                # `Page.captureScreenshot` 的 `clip` 要的是**页面坐标**，
                # 所以先量 `getBoundingClientRect()` 再加上滚动量。
                box = await S.js(_rect_js(sel))
                if not box:
                    print("  !! %s 没找到 %s" % (path, sel))
                    continue
                r = await S.cmd("Page.captureScreenshot", {
                    "format": "png", "captureBeyondViewport": True,
                    "clip": dict(box, scale=2),
                })
                if not r.get("data"):
                    print("  !! %s 没找到 %s" % (path, sel))
                    continue
                p = os.path.join(OUT, name)
                with open(p, "wb") as f:
                    f.write(base64.b64decode(r["data"]))
                print("  %-24s %7.1f KB   <- %s" % (name, os.path.getsize(p) / 1024, sel))
        # 报告页面上真正生效的底图（CSS 里写了不等于浏览器认了）
        print("\n=== 生效的底图 ===")
        for path in ("/media.html", "/detail.html"):
            await S.goto(path, 1.8)
            print("  %s -> %s" % (path, await S.js(
                "(function(){const out=[];document.querySelectorAll("
                "'.mp-hero,.mp-lib,#stageHost,.stage-svg').forEach(e=>{"
                "const c=getComputedStyle(e);out.push(e.className||e.id);"
                "out.push(c.backgroundImage.slice(0,90));"
                "out.push('opacity='+c.opacity);});return JSON.stringify(out)})()")))
        errs = [e for e in S.errs if "camera" not in str(e)]
        print("\n控制台错误 %d 条%s" % (len(errs), ("：" + str(errs[:4])) if errs else ""))


def _q(s):
    return "'" + s.replace("'", "\\'") + "'"


def _rect_js(sel):
    """把某个选择器的盒子量成 `{x,y,width,height}`（页面坐标）。

    ⚠️ 故意**不用 f-string 也不用 `%` 拼一个带花括号的 JS 字面量** —— 上一版就是
       那么写的，`%s` 和 JSON 的花括号混在一起，括号配平直接崩在语法检查那一步
       （`SyntaxError: closing parenthesis '}' does not match ...`）。这里拆成
       三段纯字符串拼接，花括号只出现在普通字符串里。
    """
    return ("(function(){const e=document.querySelector(" + _q(sel) + ");"
            "if(!e)return null;const b=e.getBoundingClientRect();"
            "return JSON.stringify({x:b.left+window.scrollX,"
            "y:b.top+window.scrollY,width:b.width,height:b.height});"
            "})()")


asyncio.run(main())
