# -*- coding: utf-8 -*-
"""导航页**加载期**到底走到哪一步 —— `XQ.nav.state()` 怎么会是 null。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_nav_boot.py 8803

`_probe_nav_sim.py` 第一版在 `st.get("routes")` 上撞了 `NoneType`，说明
`S.js("XQ.nav.state()")` 回了 None（多半是页面里的 JS 抛了）。这个脚本只做一件事：
把"页面到底加载成什么样"一条条问出来，别猜。
"""
import asyncio
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.stderr.reconfigure(encoding="utf-8", errors="replace")
if len(sys.argv) < 2:
    sys.argv.append("8803")

import _check_pages as CP                                     # noqa: E402
from _check_pages import Session                              # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CDP = 9431

QS = [
    "location.pathname",
    "document.readyState",
    "typeof window.XQ",
    "XQ ? Object.keys(XQ).join(',') : '-'",
    "typeof XQ.nav",
    "typeof XQ.nav.state",
    "typeof window.AMap",
    "!!document.getElementById('orgIn')",
    "!!document.getElementById('gdList')",
    "!!document.getElementById('simRow')",
    "!!document.getElementById('navStart')",
    "typeof SIM",
    "(()=>{try{XQ.nav.state();return 'state() 通了'}catch(e){return 'state() 抛：'+e}})()",
]


async def main():
    log = open(os.path.join(ROOT, "runs", "_probe_nav_boot_srv.log"), "w",
               encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", CP.PORT,
                            "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen(CP.BASE + "/music.json", timeout=3):
                    break
            except Exception:                                  # noqa: BLE001
                time.sleep(0.5)
        async with Session(CDP) as S:
            for tag, wait in (("刚打开", 2.5), ("再等 6 秒", 6.0)):
                if tag == "刚打开":
                    await S.goto("/nav.html", wait=wait)
                else:
                    await asyncio.sleep(wait)
                print("\n── %s ──" % tag)
                for q in QS:
                    v = await S.js(q)
                    print("   %-46s => %s" % (q[:46], v))
                print("   控制台：")
                for e in S.errs[-8:]:
                    print("     ·", str(e)[:160])
    finally:
        srv.terminate()
        time.sleep(0.8)
        if srv.poll() is None:
            srv.kill()
        log.close()


asyncio.run(main())
