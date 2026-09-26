# -*- coding: utf-8 -*-
"""封面上「看不清」的两处，**用开关法**定位是哪个 CSS 属性造成的 —— 不是靠猜。

    PYTHONIOENCODING=utf-8 D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_cov_variants.py 8765

做法：同一个浏览器会话里停在 `/`，每次都往页面里塞一段覆盖 CSS 再截一张全图。
`base` 那张是**冻结动画**之后的基准 —— 小瑞身上挂着 `xqIdle` 4s 上下浮动
（`translateY(-2.2%)` ≈ 15px），不冻住的话两张截图之间人会自己挪，
量腿的位置就分不清"是发光层冲淡的"还是"人飘走了"。

**判据**（量的是屏上像素，不是我的说法）：
  · 腿：把「腿身」和「紧挨着的背景」分成两坨，比它们的**亮度差**。
    发光层要是把腿糊掉了，关掉它腿应该**变暗回它本来的蓝白**、和背景分开。
  · 标题：三段笔画亮度 vs 紧邻背景亮度，对比度要到 **3:1** 才算"读得出来"。

⚠️ 收尾按**调试端口**杀自己开的 Edge，绝不按镜像名杀 `msedge.exe`。
"""
import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT_DBG = 9336
VW, VH = 1672, 940
OUT = os.path.join("runs", "_covvar")
os.makedirs(OUT, exist_ok=True)

# 每一档都先冻动画（见文件头），再叠这一档自己的覆盖规则
FREEZE = ("*,*::before,*::after{animation:none!important;transition:none!important}")

G3 = (".cover-r .mascot::after{bottom:-10%!important;height:11%!important;"
      "background:radial-gradient(ellipse at center, rgba(255,255,255,.96) 0%,"
      "rgba(150,206,255,.55) 42%, transparent 74%)!important}")
G4 = (".cover-r .mascot::after{bottom:-10%!important;height:11%!important;"
      "filter:blur(4px)!important}")

T3 = (".cover-l h1{background:linear-gradient(100deg,#0B3EA8 6%,#1A5FD4 32%,"
      "#2470DC 48%,#1A5FD4 64%,#0A3790 100%)!important}")
T4 = (".cover-l h1{background:linear-gradient(100deg,#0B3EA8 6%,#1A5FD4 30%,"
      "#1E6BE0 48%,#1A5FD4 66%,#0A3790 100%)!important}")
T6 = T3 + ".cover-l h1{filter:drop-shadow(0 0 2px rgba(8,38,110,.9))!important}"

VARIANTS = [
    # 收尾：两处都写进 `pages.css` 了，这一档**不注入任何东西**，
    # 量的就是盘上那份 CSS 真正的结果（FREEZE 只关动画，不碰这两条）。 */
    ("final", ""),
]


def kill_port(port):
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:
        return
    pids = set()
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 5 and f[0] == "TCP" and f[3] == "LISTENING" \
                and f[1].endswith(":" + str(port)):
            pids.add(f[4])
    for pid in pids:
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    port = int(sys.argv[1])
    # ⚠️ `tempfile.mkdtemp()` 落在 C: 上，而那台机器 C: 是满的 —— 会**静默**拿不到目录，
    #    启出来的 Edge 用不了 profile。所以 user-data-dir 一律给 D: 盘的相对路径。
    import shutil
    udd = os.path.join("runs", "_edge_profile_covvar")
    shutil.rmtree(udd, ignore_errors=True)
    os.makedirs(udd, exist_ok=True)
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--remote-debugging-port=%d" % PORT_DBG, "--window-size=%d,%d" % (VW, VH),
         "--no-first-run", "--user-data-dir=" + os.path.abspath(udd), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % PORT_DBG,
                                            timeout=2) as r:
                    t = [x for x in json.load(r) if x["type"] == "page"]
                if t:
                    target = t[0]
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not target:
            print("连不上调试端口")
            return 1
        import aiohttp
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(target["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                n = [0]

                async def cmd(method, params=None):
                    n[0] += 1
                    await ws.send_str(json.dumps({"id": n[0], "method": method,
                                                  "params": params or {}}))
                    while True:
                        m = json.loads(await ws.receive_str())
                        if m.get("id") == n[0]:
                            if "error" in m:
                                raise RuntimeError("%s -> %s" % (method, m["error"]))
                            return m.get("result", {})

                await cmd("Page.enable")
                await cmd("Emulation.setDeviceMetricsOverride",
                          {"width": VW, "height": VH, "deviceScaleFactor": 1,
                           "mobile": False})
                await cmd("Page.navigate", {"url": "http://127.0.0.1:%d/" % port})
                await asyncio.sleep(5.0)
                # 建一个常驻 <style id="__probe">，每档只换它的 textContent
                await cmd("Runtime.evaluate", {"expression":
                          "(()=>{const s=document.createElement('style');"
                          "s.id='__probe';document.head.appendChild(s);return 1})()"})

                for name, css in VARIANTS:
                    await cmd("Runtime.evaluate", {"expression":
                              "document.getElementById('__probe').textContent="
                              + json.dumps(FREEZE + css)})
                    await asyncio.sleep(1.2)
                    shot = await cmd("Page.captureScreenshot", {"format": "png"})
                    p = os.path.join(OUT, "%s.png" % name)
                    with open(p, "wb") as f:
                        f.write(base64.b64decode(shot["data"]))
                    print("%-9s -> %s" % (name, p))
        return 0
    finally:
        kill_port(PORT_DBG)


sys.exit(asyncio.run(main()))
