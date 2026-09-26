# -*- coding: utf-8 -*-
"""一次浏览器会话里给**多张页面**截屏 —— 用来目视核对小瑞新素材装上了没有。

    python _scratch/_shot_pages.py 8765 runs/_mascot / index.html chat.html phone.html

参数：端口、输出前缀、要截的路径（可以给多个）。

⚠️ 收尾必须**按端口**杀那个 headless Edge（`kill_port(9333)`），
   绝不能按镜像名杀 `msedge.exe` —— 那会关掉用户自己的浏览器（硬规矩）。
"""
import asyncio
import base64
import json
import subprocess
import sys
import time
import urllib.request

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT_DBG = 9334


def kill_port(port):
    """只杀 netstat 里占着这个调试端口的那个 PID（= 我们自己开的那个）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:
        return
    pids = set()
    for ln in out.splitlines():
        f = ln.split()
        if len(f) >= 5 and f[0] == "TCP" and f[3] == "LISTENING" and f[1].endswith(":" + str(port)):
            pids.add(f[4])
    for pid in pids:
        subprocess.run(["powershell", "-NoProfile", "-Command",
                        "Stop-Process -Id %s -Force -ErrorAction SilentlyContinue" % pid],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        subprocess.run(["taskkill", "/PID", pid, "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(15):
        try:
            busy = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                  timeout=20).stdout
        except Exception:
            return
        if not any(":" + str(port) in l and "LISTENING" in l for l in busy.splitlines()):
            return
        time.sleep(1)


async def main():
    port = int(sys.argv[1])
    prefix = sys.argv[2]
    pages = sys.argv[3:] or ["/"]
    specs = {}
    for p in pages:
        if "?" in p:
            specs[p] = p
    vw, vh = 1672, 940
    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--remote-debugging-port=%d" % PORT_DBG, "--window-size=%d,%d" % (vw, vh),
         "--no-first-run",
         "--user-data-dir=" + __import__("tempfile").mkdtemp(), "about:blank"],
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
                            return m.get("result", {})

                await cmd("Page.enable")
                await cmd("Emulation.setDeviceMetricsOverride",
                          {"width": vw, "height": vh, "deviceScaleFactor": 1,
                           "mobile": False})
                for p in pages:
                    url = "http://127.0.0.1:%d%s" % (port, p)
                    await cmd("Page.navigate", {"url": url})
                    await asyncio.sleep(4.0)
                    shot = await cmd("Page.captureScreenshot", {"format": "png"})
                    nm = p.strip("/").replace("/", "_").replace("?", "_").replace("=", "-")
                    out = "%s_%s.png" % (prefix, nm or "cover")
                    with open(out, "wb") as f:
                        f.write(base64.b64decode(shot["data"]))
                    # 顺手记录页面上小瑞图的实际 src 与尺寸 —— 证明载入的是新素材
                    ev = await cmd("Runtime.evaluate", {"expression": """JSON.stringify(
                        Array.from(document.querySelectorAll('img')).map(
                          i => (i.currentSrc||i.src).split('/').pop() + ' ' +
                               i.naturalWidth + 'x' + i.naturalHeight))""",
                        "returnByValue": True})
                    print("%-34s %s" % (out, ev["result"]["value"]))
        return 0
    finally:
        kill_port(PORT_DBG)


sys.exit(asyncio.run(main()))
