# -*- coding: utf-8 -*-
"""`XQP` 在页面上到底有没有：`_check_player.py` A 段读到 None，先分清三件事。

    PYTHONIOENCODING=utf-8 python _scratch/_probe_player_js.py

None 只有两种来路：
  ① 这一页压根没加载（`chrome-error://`，那是导航的问题，见 goto 的注释）；
  ② 表达式抛了异常 —— `Session.js()` **把异常吞了**（它只看返回值里有没有
     `value`，`Runtime.evaluate` 的异常在 `exceptionDetails` 里，走不到那条路），
     于是外面只看到 None。这里直接把整个 result 打出来，异常就藏不住了。

⚠️ 也顺手看一眼 `/static/player.js` 服务端给不给（404 的话 window.XQP 永远不会有）。
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
PORT = 8794
CDP = 9416
LOG = os.path.join(ROOT, "runs", "_probe_player_js_srv.log")
BASE = "http://127.0.0.1:%d" % PORT

EXPRS = [
    "location.href + ' | ' + document.title",
    "typeof XQP + ' | ' + typeof XQ + ' | ' + typeof window.XQP",
    "!!document.getElementById('xqMiniCss')",
    "sessionStorage.getItem('xq.media.play')",
    "JSON.stringify(typeof XQP === 'object' ? XQP.stats() : null)",
]


async def main():
    log = open(LOG, "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", str(PORT),
                            "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(BASE + "/music.json", timeout=3):
                    break
            except Exception:
                time.sleep(0.5)
        # 服务端给不给 player.js
        for u in ["/static/player.js", "/static/live.js", "/static/chrome.js"]:
            try:
                with urllib.request.urlopen(BASE + u, timeout=4) as r:
                    print("%-22s %d %d 字节" % (u, r.status, len(r.read())))
            except Exception as e:
                print("%-22s 打不开：%s" % (u, e))
        async with Session(CDP) as S:
            for pg in ["/settings.html", "/media.html"]:
                await S.cmd("Page.navigate", {"url": BASE + pg})
                await asyncio.sleep(3.0)
                print("\n=== %s ===" % pg)
                for ex in EXPRS:
                    r = await S.cmd("Runtime.evaluate",
                                    {"expression": ex, "returnByValue": True})
                    res = r.get("result", {})
                    exc = r.get("exceptionDetails")
                    print("  %-52s -> %r%s" % (ex[:52], res.get("value"),
                                               "  ‼️ " + str(
                                                   (exc or {}).get("exception", {})
                                                   .get("description", ""))[:200]
                                               if exc else ""))
    finally:
        srv.terminate()
        time.sleep(0.6)
        if srv.poll() is None:
            srv.kill()
        log.close()


if __name__ == "__main__":
    asyncio.run(main())
