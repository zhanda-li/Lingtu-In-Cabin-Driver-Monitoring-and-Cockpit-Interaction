# -*- coding: utf-8 -*-
"""某一页的**版面填充**量一遍：哪一栏到底比旁边矮、矮多少、下面空了多少。

用法：
    PYTHONIOENCODING=utf-8 python _scratch/_shot_layout.py [页面] [宽] [高]
默认 /chat.html 1672x940（这个项目量版面一直用这个尺寸）。

★ 为什么要有这支：
  用户 2026-09-25 报「这个页面要布局满啊 右边第三栏下边空白了」。
  「下边空白了」是一句**关于高度的抱怨**，但它没说清是"这一栏自己没排满"还是
  "这一栏比相邻的那一栏矮、于是下面露出一块"。这两件事的改法完全不同：
    · 前者 = 栏内元素没撑开（加 `flex:1` / 调内边距 / 让卡片长起来）
    · 后者 = 栅格对齐（`align-items:stretch` / 让短的那栏补内容）
  所以量的是**每一栏的底边 y 坐标**，并且和视口底部、和相邻栏逐个比 ——
  数字一出来就知道是哪一种，不用猜。截图只是给人复核的。

⚠️ 只报告、不判定（EXIT 恒 0）。
⚠️ 自己起服务器（8793）和自己的 Edge（9422），**不碰用户那台 8765**。
"""
import asyncio
import base64
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _check_pages import Session                      # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8793
CDP = 9422
BASE = "http://127.0.0.1:%d" % PORT

PAGE = sys.argv[1] if len(sys.argv) > 1 else "/chat.html"
VW = int(sys.argv[2]) if len(sys.argv) > 2 else 1672
VH = int(sys.argv[3]) if len(sys.argv) > 3 else 940

# 量每一栏。`sel` 是这一栏的容器；顺带把它里面的直接子块也量一遍 ——
# "栏自己排满没有"往往要看它最后一个孩子停在哪。
MEASURE = r"""JSON.stringify((() => {
  const R = (e) => { const r = e.getBoundingClientRect();
    return {t: Math.round(r.top), b: Math.round(r.bottom),
            h: Math.round(r.height), w: Math.round(r.width), l: Math.round(r.left)}; };
  const cols = [];
  /* 三栏的通用认法：左导航条 / 中间内容 / 右栏。哪一页没有就自动跳过。 */
  const cand = [
    ['#rail',        '左导航条'],
    ['.sub-body',    '内容区'],
    ['.chat-wrap',   'chat 栅格'],
    ['.chat-box',    'chat 对话列'],
    ['aside',        '右栏 aside'],
    ['.main',        '整页主体'],
  ];
  for (const [sel, name] of cand) {
    const e = document.querySelector(sel);
    if (!e) continue;
    cols.push({sel: sel, name: name, box: R(e),
      kids: [...e.children].map(k => ({
        cls: (k.className && typeof k.className === 'string'
              ? k.className.split(' ').slice(0, 2).join('.') : k.tagName.toLowerCase()),
        box: R(k)})),
    });
  }
  /* 右栏里那几摞卡片各自停在哪儿 —— "下边空白"通常是最后一张卡片离得远。 */
  const asideKids = [...document.querySelectorAll('aside > *')].map(k => ({
    cls: (typeof k.className === 'string' ? k.className.split(' ').slice(0,2).join('.') : k.tagName),
    box: R(k)}));
  return {
    vw: innerWidth, vh: innerHeight,
    docH: document.documentElement.scrollHeight,
    bodyH: document.body.scrollHeight,
    cols: cols,
    asideKids: asideKids,
    /* 这一页还有没有"看着能点、点了不干活"的东西（用户的老规矩：不是摆设） */
    fakes: [...document.querySelectorAll('[title*="示意"],[title*="占位"]')]
             .map(e => e.tagName.toLowerCase() + '#' + (e.id||'') + ' ' + e.title),
    dead: ['player','pp','prev','next','bigWave','heart','cover']
            .filter(id => document.getElementById(id)),
    hasXQP: typeof XQP !== 'undefined',
  };
})())"""


async def shot(S, name):
    os.makedirs(os.path.join(ROOT, "runs"), exist_ok=True)
    r = await S.cmd("Page.captureScreenshot", {"format": "png"})
    p = os.path.join(ROOT, "runs", "%s.png" % name)
    with open(p, "wb") as f:
        f.write(base64.b64decode(r["data"]))
    print("  截图 -> runs/%s.png" % name)


async def main():
    log = open(os.path.join(ROOT, "runs", "_shot_layout_srv.log"), "w",
               encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", str(PORT),
                            "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(BASE + "/music.json", timeout=3):
                    break
            except Exception:                             # noqa: BLE001
                time.sleep(0.5)

        async with Session(CDP) as S:
            await S.cmd("Emulation.setDeviceMetricsOverride",
                        {"width": VW, "height": VH, "deviceScaleFactor": 1,
                         "mobile": False})
            await S.cmd("Page.navigate", {"url": BASE + PAGE})
            await asyncio.sleep(3.5)

            m = await S.js(MEASURE)
            print("\n===== %s  视口 %dx%d =====" % (PAGE, m["vw"], m["vh"]))
            print("  文档高 %d / body 高 %d   （比视口多 %d = 要滚动的部分）"
                  % (m["docH"], m["bodyH"], m["docH"] - m["vh"]))
            for c in m["cols"]:
                bx = c["box"]
                print("\n  [%s] %s  左%d 宽%d  顶%d 底%d  高%d   离视口底还差 %d"
                      % (c["name"], c["sel"], bx["l"], bx["w"], bx["t"], bx["b"],
                         bx["h"], m["vh"] - bx["b"]))
                for k in c["kids"]:
                    print("       %-22s 顶%4d 底%4d 高%4d"
                          % (k["cls"] or "?", k["box"]["t"], k["box"]["b"],
                             k["box"]["h"]))
            print("\n  右栏那几摞：")
            for k in m["asideKids"]:
                print("       %-22s 顶%4d 底%4d 高%4d"
                      % (k["cls"] or "?", k["box"]["t"], k["box"]["b"],
                         k["box"]["h"]))
            print("\n  已删元素还残留的 id = %s" % (m["dead"] or "无（干净）"))
            print("  页面上还写着「示意/占位」的控件 = %s"
                  % (m["fakes"] or "无"))
            print("  有没有 XQP = %s" % m["hasXQP"])

            await shot(S, "layout" + PAGE.replace("/", "_").replace(".html", ""))

            if S.errs:
                print("\n  控制台：")
                for lvl, txt in S.errs[:10]:
                    print("    !! %s：%s" % (lvl, txt))
            else:
                print("\n  控制台：零报错零警告")
    finally:
        try:
            srv.terminate()
            time.sleep(0.8)
            if srv.poll() is None:
                srv.kill()
        finally:
            log.close()
    print("\n（只报告，EXIT 恒 0）")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
