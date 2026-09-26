# -*- coding: utf-8 -*-
"""对话框被灌满之后，高度**长到哪儿去了** —— 一层一层量出来。

    PYTHONIOENCODING=utf-8 python _scratch/_diag_bubble.py 8799 runs/_diag_bubble

`_check_media_lib.py` 的 I2 段红了一条：灌 30 条之后 `#xqBubble` 的
`clientHeight == scrollHeight == 1824` —— 也就是说它**没有**在框里滚，而是
自己长到了内容那么高。这一页的设计（media.html 里 `.xq-head` / `.xq-bubble`
那两段注释）说的是"高度由卡片给，超出就在框里滚"，所以要么是 CSS 的高度链
在某一层断了，要么是那两段注释说的事情从来没成立过。

⚠️ 光看 `#xqBubble` 一个盒子分不出这两种情况，必须**从里往外每一层都量**：
   气泡 → .xq-head → .mp-xq（卡片）→ 网格行 → .sub-body → body。
   哪一层跟着长，断点就在它和它儿子之间。
⚠️ 只读不写（除了灌消息），不点任何按钮。
⚠️ 收尾按端口收 Edge，绝不按进程名（见记忆 [[windows-dev-env]]）。
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

PY = r"D:\Anaconda3\envs\dms\python.exe"
PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
TASKKILL = r"C:\Windows\System32\taskkill.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
CDP = 9337

# 从里到外每一层的实测高度 + 关键计算样式。`mh` 是 min-height，
# 断点最常见的成因就是某一层没写 min-height:0（flex/grid 子项默认 min-height:auto
# = 不许小于内容，于是"内容越高它越高"，滚动的那个盒子反而永远等不到溢出）。
CHAIN = r"""(() => {
  const ids = ['xqBubble', null];
  const nodes = [
    ['#xqBubble',     document.getElementById('xqBubble')],
    ['.xq-head',      document.querySelector('.xq-head')],
    ['.mp-xq(card)',  document.querySelector('.mp-xq')],
    ['grid row',      document.querySelector('.mp-xq').parentElement],
    ['.sub-body',     document.querySelector('.sub-body')],
    ['body',          document.body],
  ];
  const one = ([name, e]) => {
    if (!e) return {n: name, missing: true};
    const r = e.getBoundingClientRect();
    const c = getComputedStyle(e);
    return {n: name, h: Math.round(r.height), top: Math.round(r.top),
            bottom: Math.round(r.bottom),
            sh: e.scrollHeight, ch: e.clientHeight,
            mh: c.minHeight, hh: c.height, ov: c.overflowY,
            disp: c.display, flex: c.flex, as: c.alignSelf};
  };
  const b = document.getElementById('xqBubble');
  const mono = [...b.querySelectorAll('p.m')].filter((p) => !p.classList.contains('st'));
  return JSON.stringify({
    vh: innerHeight,
    bodySh: document.body.scrollHeight,
    n: mono.length,
    bubbleSh: b.scrollHeight, bubbleCh: b.clientHeight,
    chain: nodes.map(one),
    spill: b.scrollHeight - b.clientHeight});
})()"""


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
        subprocess.run([PS, "-NoProfile", "-Command",
                        "Stop-Process -Id %s -Force -ErrorAction SilentlyContinue" % pid],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
        subprocess.run([TASKKILL, "/PID", pid, "/T", "/F"],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    port = sys.argv[1] if len(sys.argv) > 1 else "8799"

    log = open(os.path.join(ROOT, "runs", "_diag_bubble_srv.log"), "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", port, "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    for _ in range(80):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%s/music.json" % port, timeout=2):
                break
        except Exception:
            time.sleep(0.5)

    proc = subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--remote-debugging-port=%d" % CDP, "--window-size=1672,940",
         "--autoplay-policy=no-user-gesture-required",
         "--no-first-run", "--user-data-dir=" + tempfile.mkdtemp(), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % CDP, timeout=2) as r:
                    pages = [t for t in json.load(r) if t["type"] == "page"]
                if pages:
                    target = pages[0]
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
                await cmd("Runtime.enable")
                await cmd("Emulation.setDeviceMetricsOverride",
                          {"width": 1672, "height": 940, "deviceScaleFactor": 1,
                           "mobile": False})
                await cmd("Page.navigate", {"url": "http://127.0.0.1:%s/media.html" % port})
                await asyncio.sleep(float(os.environ.get("WAIT", "8")))

                r = await cmd("Runtime.evaluate",
                              {"expression": CHAIN, "returnByValue": True})
                print("== 灌之前（空对话区）==")
                print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False, indent=1))

                for cnt in (2, 8, 30):
                    await cmd("Runtime.evaluate", {"expression": """(() => {
                      const b = document.getElementById('xqBubble');
                      const have = [...b.querySelectorAll('p.m')]
                                     .filter((p) => !p.classList.contains('st')).length;
                      for (let k = have; k < %d; k++) {
                        XQ.mediaLink.push('压测第 ' + (k + 1) + ' 句：'
                          + '这是一条会折行的长话，拿它把对话区撑满，看会不会把气泡压扁。');
                      }
                      return 1; })()""" % cnt})
                    await asyncio.sleep(0.6)
                    r = await cmd("Runtime.evaluate",
                                  {"expression": CHAIN, "returnByValue": True})
                    print("\n== 灌到 %d 条 ==" % cnt)
                    print(json.dumps(json.loads(r["result"]["value"]), ensure_ascii=False,
                                     indent=1))
        return 0
    finally:
        kill_port(CDP)
        srv.terminate()
        time.sleep(0.8)
        if srv.poll() is None:
            srv.kill()
        log.close()


sys.exit(asyncio.run(main()))
