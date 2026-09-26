# -*- coding: utf-8 -*-
"""**关掉浏览器之后，摄像头到底多久才真松手** —— 用户报障的复现与验收。

    PYTHONIOENCODING=utf-8 D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_check_cam_release.py

用户原话（2026-09-25）：
    「关闭浏览器自动关闭摄像头 现在我把浏览器关了摄像头还开着」

这一条**必须真开摄像头**才能量（demo 源根本不碰设备）。所以：

  ① 起一个 `--source cam` 的服务 → 打开**之前**先探一次设备，记个数。
     （"启动时不抓设备"是这一版的设计，用户看到灯没亮不该以为坏了。）
  ② 用 headless Edge 打开驾驶监测页 → 等它自动接入。
  ③ 刷新一次、翻一页，量**旧 WS 关到新 WS 开**隔了多久 —— `CAM_IDLE_GRACE`
     定多大就看这个数（定小了 = 每刷一次都重开设备、卡几秒）。
  ④ **把浏览器整个关掉**（CDP `Browser.close`，等于用户点右上角那个 X），
     盯着日志看 `[cam] … 松手` 那行什么时候出来。

判据（**只有服务端日志算数**）：
  · `[ws] 页面 -1 → 0` —— 浏览器真把页面关了（不然下面全是假报障）；
  · `[cam] … 松手：没有页面在看了（空闲 X s）` —— 松手真的发生了，X 就是宽限值；
  · **不能出现**「⚠️ 松手后摄像头线程还活着」—— 设备是在 `CamSource._run()` 的
    finally 里 `release()` 的，线程没退 = 句柄可能还开着 = 灯不灭。

🔴 **`_probe_cam_free.py` 这里只当读数记，不当判据**：实测这台机器的内置摄像头
   能被**两个进程同时打开**（服务端正推着流，探测照样回 FREE），所以它分不出
   "我们攥着"和"没人攥"。理由写在那个脚本的 docstring 里。

⚠️ 自己起服务（8793）和自己那个 headless Edge（调试端口 9340），收尾按**端口**
   杀干净；绝不按镜像名杀 msedge.exe，也绝不动用户自己那个 8765。
⚠️ cam 模式进程里有**两个** mediapipe landmarker（析构各 42 s），所以收尾一律
   `taskkill /F` 硬杀，别等它自己退。
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = 8793
CDP = 9340
VW, VH = 1672, 940
PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG = os.path.join("runs", "_camrel_srv.log")
PROBE = os.path.join("_scratch", "_probe_cam_free.py")

EDGE = next((p for p in (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)), None)


def kill_port(port):
    """按**端口**收自己起的进程（绝不按镜像名杀）。"""
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception:
        return
    pids = {ln.split()[4] for ln in out.splitlines()
            if len(ln.split()) >= 5 and ln.split()[0] == "TCP"
            and ln.split()[3] == "LISTENING" and ln.split()[1].endswith(":" + str(port))}
    for pid in pids:
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


def probe(tag, want_free=None):
    """探一次设备。**这个动作本身会短暂抢一下设备**，所以只在关键节点用。"""
    t0 = time.monotonic()
    r = subprocess.run([PY, PROBE], cwd=ROOT, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=30)
    line = (r.stdout or "").strip().splitlines()
    line = line[-1] if line else "(没有输出)"
    free = r.returncode == 0
    mark = ""
    if want_free is not None:
        mark = "  ✅ 符合预期" if free == want_free else "  ❌ **和预期相反**"
    print("  [%s] %s（%.1fs）%s" % (tag, line, time.monotonic() - t0, mark))
    return free


def read_log():
    try:
        with open(LOG, "r", encoding="utf-8", errors="replace") as f:
            return f.read()
    except Exception:
        return ""


def ws_events(text):
    """日志里那两种临时行 → [(t, +1/-1)]。"""
    out = []
    for ln in text.splitlines():
        if "[ws] 页面" not in ln:
            continue
        try:
            t = float(ln.rsplit("t=", 1)[1])
        except Exception:
            continue
        out.append((t, 1 if "+1" in ln else -1))
    return out


def cam_events(text):
    """日志里的 [cam] 行 → [(t, 行内容)]。⚠️ 那两行是人读的，没有 t=，
    所以用**读到它的时刻**当时间戳（每秒轮询，误差 ≤1 s，够用了）。"""
    return [ln for ln in text.splitlines() if ln.startswith("[cam]")]


def start_server():
    log = open(LOG, "wb")
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.Popen([PY, "-u", "ui/server.py", "--port", str(PORT),
                          "--source", "cam"],
                         cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, env=env)
    for _ in range(120):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/index.html" % PORT,
                                        timeout=2):
                return p
        except Exception:
            time.sleep(0.5)
    print("服务端起不来，见 " + LOG)
    return None


async def main():
    if not EDGE:
        print("找不到 msedge.exe")
        return 1

    print("=" * 78)
    print("⓪ 开着服务之前：设备该是空的（没有任何进程在用它）")
    print("=" * 78)
    probe("起服务前", want_free=True)

    srv = start_server()
    if not srv:
        return 1
    print("\n服务已起（--source cam，端口 %d）。日志：%s" % (PORT, LOG))
    probe("服务起着但还没页面", want_free=True)

    udd = os.path.join("runs", "_edge_profile_camrel")
    shutil.rmtree(udd, ignore_errors=True)
    os.makedirs(udd, exist_ok=True)
    subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--remote-debugging-port=%d" % CDP, "--window-size=%d,%d" % (VW, VH),
         "--no-first-run", "--user-data-dir=" + os.path.abspath(udd), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    import aiohttp
    rc = 0
    try:
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % CDP,
                                            timeout=2) as r:
                    t = [x for x in json.load(r) if x["type"] == "page"]
                if t:
                    target = t[0]
                    break
            except Exception:
                pass
            time.sleep(0.5)
        if not target:
            print("连不上调试端口 %d" % CDP)
            return 1

        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(target["webSocketDebuggerUrl"],
                                    max_msg_size=0) as ws:
                n = [0]

                async def cmd(method, params=None):
                    n[0] += 1
                    await ws.send_str(json.dumps({"id": n[0], "method": method,
                                                  "params": params or {}}))
                    while True:
                        m = json.loads(await ws.receive_str())
                        if m.get("id") == n[0]:
                            return m.get("result", {})

                async def ev(expr):
                    r = await cmd("Runtime.evaluate",
                                  {"expression": expr, "returnByValue": True})
                    return r.get("result", {}).get("value")

                JS = r"""JSON.stringify((() => {
                  const g = (id) => document.getElementById(id);
                  return {
                    camLive: g('camLive') ? g('camLive').textContent : null,
                    camSrc: g('camStream') ? (g('camStream').getAttribute('src')||'') : null,
                    camHidden: g('camStream') ? g('camStream').hidden : null,
                    nfHidden: g('noFace') ? g('noFace').hidden : null,
                    nHist: (XQ.Hist && XQ.Hist.rows) ? XQ.Hist.rows.length : null,
                    toast: g('toast') ? g('toast').textContent : null,
                  };
                })())"""

                async def snap(tag):
                    d = json.loads(await ev(JS))
                    print("  [%s] 左上=「%s」 mjpg=%s(nf藏=%s) state样本=%s 提示=「%s」"
                          % (tag, d["camLive"], repr(d["camSrc"]),
                             d["nfHidden"], d["nHist"], d["toast"]))
                    return d

                async def shot(out):
                    await cmd("Page.enable")
                    r = await cmd("Page.captureScreenshot", {"format": "png"})
                    p = os.path.join("runs", out)
                    open(p, "wb").write(base64.b64decode(r["data"]))
                    print("  -> %s (%d bytes)" % (p, os.path.getsize(p)))

                await cmd("Page.enable")
                await cmd("Emulation.setDeviceMetricsOverride",
                          {"width": VW, "height": VH, "deviceScaleFactor": 1,
                           "mobile": False})
                await cmd("Page.navigate",
                          {"url": "http://127.0.0.1:%d/detail.html" % PORT})
                await asyncio.sleep(3.0)

                print("\n" + "=" * 78)
                print("① 页面打开 → 自动接入（--source cam：页面来了才开设备）")
                print("=" * 78)
                t_open = None
                for i in range(40):
                    d = json.loads(await ev(JS))
                    if d["camSrc"] and not d["camHidden"]:
                        t_open = time.monotonic()
                        print("  第 %.1f s：接上了 —— %s" % (i * 1.0, d["camLive"]))
                        break
                    time.sleep(1.0)
                if t_open is None:
                    print("  ❌ 20 s 内没接上，看日志：")
                    tail = read_log().splitlines()[-15:]
                    for ln in tail:
                        print("     " + ln)
                    return 1
                await asyncio.sleep(3.0)
                await snap("接上之后")
                await shot("_camrel_1_on.png")
                # 🔴 这一探**故意不设预期**：实测发现内置摄像头能被两个进程同时
                #   打开，所以"探测说 FREE"根本不代表服务端没攥着设备
                #   （理由写在 `_probe_cam_free.py` 的 docstring 里）。
                #   就当一次读数记下来，判据一律走服务端日志。
                probe("页面开着时（读数仅记录）")

                print("\n" + "=" * 78)
                print("② 刷新一次：量「旧 WS 关 → 新 WS 开」隔多久")
                print("   （这个数就是 `CAM_IDLE_GRACE` 的下限依据；顺带验一下"
                      "刷新**不该**重开设备）")
                print("=" * 78)
                before = len(ws_events(read_log()))
                await cmd("Page.reload")
                await asyncio.sleep(6.0)
                evs = ws_events(read_log())[before:]
                print("  这次刷新期间的 WS 事件：%s"
                      % ", ".join("%+.0f@%.3f" % e for e in evs))
                for i in range(len(evs) - 1):
                    if evs[i][1] == -1 and evs[i + 1][1] == 1:
                        print("  → 断连窗口 **%.2f s**" % (evs[i + 1][0] - evs[i][0]))
                d = await snap("刷新之后")
                cam_lines = cam_events(read_log())
                print("  日志里的 [cam] 行（刷新不该新增「接入」）：")
                for ln in cam_lines:
                    print("     " + ln)

                print("\n" + "=" * 78)
                print("③ 翻到另一页（首页）再回到监测页：同一个窗口，验证导航")
                print("=" * 78)
                before = len(ws_events(read_log()))
                await cmd("Page.navigate",
                          {"url": "http://127.0.0.1:%d/index.html" % PORT})
                await asyncio.sleep(4.0)
                evs = ws_events(read_log())[before:]
                print("  导航期间的 WS 事件：%s"
                      % ", ".join("%+.0f@%.3f" % e for e in evs))
                for i in range(len(evs) - 1):
                    if evs[i][1] == -1 and evs[i + 1][1] == 1:
                        print("  → 断连窗口 **%.2f s**" % (evs[i + 1][0] - evs[i][0]))

                print("\n" + "=" * 78)
                print("④ **把浏览器整个关掉**（＝用户点右上角那个 X），"
                      "看摄像头什么时候真松手")
                print("=" * 78)
                n_before = len(read_log().splitlines())
                t_close = time.monotonic()
                # fire-and-forget：发出去就不等回话了（浏览器一关，这条连接就没了）
                await ws.send_str(json.dumps({"id": 9999, "method": "Browser.close"}))
                print("  已发 Browser.close，t=0")

                t_release = None
                t_wsgone = None
                t_warn = None
                n_ws = len(ws_events(read_log()))
                for i in range(40):
                    await asyncio.sleep(0.5)
                    el = time.monotonic() - t_close
                    # 先确认浏览器**真的**把 WS 关了。没有这一条的话，
                    # "40 s 没松手"分不清是代码不松手还是浏览器根本没关干净
                    # （headless 下 `Browser.close` 万一不生效，就是假报障）。
                    if t_wsgone is None:
                        evs = ws_events(read_log())[n_ws:]
                        if any(e[1] == -1 for e in evs):
                            t_wsgone = el
                            print("  %5.1f s  WS 已断（浏览器真的关了）" % el)
                    for ln in read_log().splitlines()[n_before:]:
                        if ln.startswith("[cam]") and "松手" in ln \
                                and t_release is None:
                            t_release = el
                            print("  %5.1f s  服务端松手：%s" % (el, ln))
                        # 这一行要是出现，说明线程没赶上 `stop()` 那个 join ——
                        # 设备**可能还攥在进程里**（灯不灭就是这个原因）。
                        if "线程还活着" in ln and t_warn is None:
                            t_warn = el
                            print("  %5.1f s  ⚠️ **线程没退**：%s" % (el, ln))
                    if t_release is not None:
                        await asyncio.sleep(1.5)   # 让 stop_source 那句告警来得及打
                        for ln in read_log().splitlines()[n_before:]:
                            if "线程还活着" in ln and t_warn is None:
                                t_warn = el
                                print("  %5.1f s  ⚠️ **线程没退**：%s" % (el, ln))
                        break

                print("\n" + "=" * 78)
                print("结论")
                print("=" * 78)
                print("  ⓪ 浏览器关掉到 WS 真断：%s"
                      % ("%.1f s" % t_wsgone if t_wsgone is not None
                         else "**一直没断** —— 浏览器没关干净，下面的数不作数"))
                if t_release is None:
                    print("  ❌ 40 s 内日志里没有「松手」那行 —— 摄像头**没被放掉**")
                    rc = 1
                else:
                    print("  ① 服务端松手用了 **%.1f s**（= 空闲宽限 %.1f s + 放旧源"
                          "的时间）  ← 用户盯的就是这一段"
                          % (t_release, 3.0))
                print("  ② 松手时线程退干净了：%s"
                      % ("✅ 是（`cap.release()` 真跑了，设备句柄已关）"
                         if t_warn is None else "❌ **没有**，见上面那行告警"))
                if t_warn is not None:
                    rc = 1
                probe("收尾前（读数仅记录，不代表占用）")
                tail = read_log().splitlines()[-8:]
                print("\n  服务端日志尾巴：")
                for ln in tail:
                    print("     " + ln)
    finally:
        kill_port(CDP)
        try:
            srv.terminate()
        except Exception:
            pass
        time.sleep(1.0)
        kill_port(PORT)
        kill_port(PORT)
        print("\n（收尾）浏览器和服务都按端口收了；最后再探一次设备：")
        probe("收尾后", want_free=True)
    return rc


sys.exit(asyncio.run(main()))
