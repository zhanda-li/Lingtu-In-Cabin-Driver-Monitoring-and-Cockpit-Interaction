# -*- coding: utf-8 -*-
"""给跨页悬浮播放条**找地方**：量，不猜。

    PYTHONIOENCODING=utf-8 python _scratch/_probe_mini_spot.py

悬浮条是 `position:fixed` 的一条胶囊（约 2.6rem 高、20rem 宽）。它压在谁身上
就成了"看得见但点不着"的死角 —— 尤其**左栏那张浮卡**（`.rail-card` 是从顶到
底的一整列，里面就是四个入口 `.ri`）和 `.rail-foot`（左下角那个 CHERY 车标，
用户点名要留的）。

这个脚本只做一件事：在每张座舱页上把**底部那一带**的矩形全打印出来，让我按
**真实数字**挑一个不压东西的位置。⚠️ 它只看、不改。

⚠️ 两个写法上的坑，都踩过：
   1. **别把 `getBoundingClientRect()` 直接塞进返回值**。DOMRect 没有可枚举的
      自有属性，`JSON.stringify` 出来是 `{}`；而 `{}` 在 Python 里是**假值**，
      于是 `if r:` 静默跳过 —— 第一次跑出来九张页全是空的，看着像"底部什么都没有"。
      一律摊成 `l/t/r/b` 四个数。
   2. **"能点的"不能只认 `a`/`button`/`[onclick]`**。这座舱里大量卡片是
      `addEventListener` 挂的、连 `onclick` 属性都没有，选择器一个都抓不到。
      改成认 `cursor:pointer`（人眼判断"这个能点"用的就是这条），再加标签兜底。
"""

import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from _check_pages import Session                  # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8794                       # 和 _check_player.py 同一个口（两者都别和别的脚本撞）
CDP = 9416                        # 9411=_check_pages 9415=_check_media_lib 9429=_check_theme2
LOG = os.path.join(ROOT, "runs", "_probe_mini_spot_srv.log")
BASE = "http://127.0.0.1:%d" % PORT

PAGES = ["index.html", "detail.html", "chat.html", "media.html", "settings.html",
         "phone.html", "link.html", "flow.html", "voice.html"]

MEASURE = """
JSON.stringify((() => {
  const rm = parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const vw = innerWidth, vh = innerHeight;
  const band = vh - 13 * rm;                   // "底部那一带"的上边界
  const rect = (e) => { const r = e.getBoundingClientRect();
    return {l: Math.round(r.left), r: Math.round(r.right),
            t: Math.round(r.top), b: Math.round(r.bottom),
            w: Math.round(r.width), h: Math.round(r.height)}; };
  const name = (e) => e.tagName.toLowerCase() +
    (e.id ? '#' + e.id : '') +
    (e.className && typeof e.className === 'string'
       ? '.' + e.className.split(' ').filter(Boolean).slice(0, 2).join('.') : '');
  // ① 底部那一带里"人能点的"：光标是 pointer 的，或者本身就是表单控件/链接
  const hits = [];
  for (const e of document.querySelectorAll('body *')) {
    const r = e.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0 || r.bottom < band) continue;
    const cs = getComputedStyle(e);
    if (cs.visibility === 'hidden' || cs.display === 'none') continue;
    const tag = e.tagName.toLowerCase();
    const clickish = cs.cursor === 'pointer' ||
                     ['a', 'button', 'input', 'select', 'textarea', 'label'].includes(tag);
    if (!clickish) continue;
    hits.push({what: name(e), ...rect(e)});
  }
  // ② 几个"必有"的容器，无论可不可点都要看位置
  const boxes = {};
  for (const sel of ['#rail', '.rail-card', '.rail-foot', '.climate', '#toast',
                     '#xqMini', '.main']) {
    const e = document.querySelector(sel);
    if (e) { const r = rect(e);
      if (r.w > 0 && r.h > 0) boxes[sel] = r; }
  }
  return {vw: vw, vh: vh, rm: rm, band: Math.round(band),
          href: location.href, title: document.title,
          hits: hits.sort((a, b) => a.l - b.l || a.t - b.t), boxes: boxes};
})())
"""


async def goto(S, path, wait=2.4, port=PORT):
    """⚠️ **别用 `S.goto()`** —— 同一个 Session 上的那个方法拼的是 `_check_pages`
    模块里的 `BASE`（= 那个脚本自己的 `PORT`，默认 **8790**），不是这里的 8796。
    复用它 = 把浏览器开到另一个端口上，而那边没有服务：表现是
    `location.href == 'chrome-error://chromewebdata/'`、标题变成 "127.0.0.1"、
    页面上每个 `getElementById` 都是 null —— **看着像"新页面炸了"，其实是
    "浏览器压根没到这一页来"**。见 `_check_media_lib.py` 里同样的一段。
    （自己发的 `Page.navigate` 带上 `errorText`，那种情况下会明说
    `net::ERR_CONNECTION_REFUSED`。）"""
    await S.cmd("Page.navigate", {"url": "http://127.0.0.1:%d%s" % (port, path)})
    await asyncio.sleep(wait)


def start_server():
    log = open(LOG, "w", encoding="utf-8")
    p = subprocess.Popen([PY, "-u", "ui/server.py", "--port", str(PORT),
                          "--source", "demo"],
                         cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                         env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    return p, log


def stop_server(p, log):
    p.terminate()
    time.sleep(0.8)
    if p.poll() is None:
        p.kill()
    log.close()


async def main():
    srv, log = start_server()
    try:
        ready = False
        for _ in range(40):
            try:
                with urllib.request.urlopen(BASE + "/music.json", timeout=3) as r:
                    print("服务端就绪：/music.json %d %d 字节" % (r.status, len(r.read())))
                ready = True
                break
            except Exception as e:
                print("  等 8796：%s %s" % (type(e).__name__, str(e)[:120]))
                time.sleep(0.5)
        print("就绪=%s  服务进程还活着=%s" % (ready, srv.poll() is None))
        async with Session(CDP) as S:
            for pg in PAGES:
                await goto(S, "/" + pg)
                d = await S.js(MEASURE)
                # ⚠️ 先把"读到的是哪一页"打出来。第一次跑这份脚本，九张页量出来
                #    全像 Edge 的报错页（底部只有一个 `#reload-button`），而同一台
                #    机器上服务是好的 —— 不打印 href/title 就分不清"导航没成"和
                #    "页面上真没有"。
                #    ★ 那次查清了：**是导航没成**（页面真长这样才怪）。当年那份
                #      一次性探针（`_probe_nav_ok.py`）已经删了，结论留在这儿。
                print("=== %s ===  视口 %d×%d  ①rem=%.1fpx  底部带从 y=%d 起"
                      % (pg, d["vw"], d["vh"], d["rm"], d["band"]))
                print("   实到：%s  title=%r  #rail=%s"
                      % (d["href"], d["title"], "#rail" in d["boxes"]))
                for sel, r in d["boxes"].items():
                    print("   %-12s l=%-5d r=%-5d t=%-5d b=%-5d" %
                          (sel, r["l"], r["r"], r["t"], r["b"]))
                if not d["hits"]:
                    print("   底部带里：**没有**能点的东西")
                else:
                    print("   底部带里能点的：")
                    for o in d["hits"]:
                        print("     %-30s l=%-5d r=%-5d t=%-5d b=%-5d" %
                              (o["what"], o["l"], o["r"], o["t"], o["b"]))
                print()
    finally:
        stop_server(srv, log)
    print("（量尺寸，不判对错）")


if __name__ == "__main__":
    asyncio.run(main())
