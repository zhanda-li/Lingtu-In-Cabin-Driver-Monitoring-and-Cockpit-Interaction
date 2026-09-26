# -*- coding: utf-8 -*-
"""真机定位 + 「小瑞会说的那句话」的端到端预演 —— **写导航页之前先把结论拿到**。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_geo_nearby.py

⚠️ 这一个**故意不复用 `_check_pages.Session`**：那个类把 `--headless=new` 写死了，
   而本条**必须**是有窗口的 Edge —— headless 没有定位源（实测 code 3 超时），
   拿不到真坐标，整条就白测。窗口用 `--window-position=-3200,-3200` 挪到屏幕外，
   跑完自己收掉。

它回答三件事（按顺序）：
  ① 真机浏览器**到底给不给坐标**（Windows 总开关是 Allow、lfsvc 在跑，但 Edge 那条
     应用级许可从没设过 —— 所以真机上第一次会弹权限气泡，这里用 CDP 预先授予，
     量的是"气泡点过之后能不能拿到"）；
  ② 拿到的坐标能不能查出服务区（写死的「前方 12 公里」要换成真的，换成什么？）；
  ③ 顺带把 `ui/amap.py` 要用的两个接口（周边搜索 + 驾车路线）先打一遍，
     **看真的返回什么**再动笔写解析。
"""
import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, _HERE)

_TMP = os.path.join(_HERE, "_tmp")
os.makedirs(_TMP, exist_ok=True)
os.environ["TEMP"] = os.environ["TMP"] = _TMP

import _check_pages as CP                                     # noqa: E402

EDGE = CP.EDGE
PORT = "8808"
CDP = 9475

_A = json.load(open(os.path.join(ROOT, "ui", "config.json"),
                    encoding="utf-8")).get("amap", {})
WEB_KEY = _A.get("web_key") or ""
JS_KEY = _A.get("js_key") or ""
RADIUS = int(_A.get("radius_m") or 50000)
KEYWORDS = _A.get("keywords") or ["服务区", "加油站"]

GEO_JS = """
new Promise((res) => {
  if (!navigator.geolocation) return res(JSON.stringify({ok:false, why:'没有 API'}));
  let done = false;
  const fin = (o) => { if (!done) { done = true; res(JSON.stringify(o)); } };
  const t0 = Date.now();
  // ⚠️ 硬上限：`getCurrentPosition` 那个 `timeout` 选项**在权限气泡还挂着的时候
  //    不生效**（它是"授权之后"才开始算的）。没有这一层，整支脚本会一直挂着，
  //    表现就是"什么都没输出"。
  setTimeout(() => fin({ok:false, why:'硬上限 20 s 到，还没结果（多半是权限气泡挂着）'}),
             20000);
  navigator.geolocation.getCurrentPosition(
    (p) => fin({ok: true, ms: Date.now() - t0,
                lat: p.coords.latitude, lng: p.coords.longitude,
                acc: Math.round(p.coords.accuracy)}),
    (e) => fin({ok: false, ms: Date.now() - t0, code: e.code, msg: e.message}),
    { timeout: 12000, maximumAge: 0 });
})
"""


def rest(path, params, timeout=8):
    q = "&".join("%s=%s" % (k, urllib.parse.quote(str(v)))
                 for k, v in params.items())
    url = "https://restapi.amap.com/v3/%s?%s&key=%s" % (path, q, WEB_KEY)
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


async def main():
    import aiohttp
    import urllib.parse                                     # noqa: F401

    # ---- 起服务（只是为了有个安全的源；定位本身不需要服务）----
    log = open(os.path.join(ROOT, "runs", "_probe_geo_srv.log"), "w",
               encoding="utf-8")
    srv = subprocess.Popen([r"D:\Anaconda3\envs\dms\python.exe", "-u",
                            "ui/server.py", "--port", PORT, "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    proc = None
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%s/music.json"
                                            % PORT, timeout=3):
                    break
            except Exception:                              # noqa: BLE001
                time.sleep(0.5)

        # ---- 有窗口的 Edge，挪到屏幕外 ----
        # ⚠️ 挪到屏幕外 = Chrome 眼里"被遮挡"，会**限制后台/被遮挡窗口的定时器**，
        #    于是 Promise 里那些 setTimeout 全部延后，量出来的时间全是假的。
        #    这两个开关就是解它的，少一个都不行。
        prof = tempfile.mkdtemp(prefix="geo_", dir=_TMP)
        proc = subprocess.Popen(
            [EDGE, "--disable-gpu", "--no-first-run",
             "--disable-backgrounding-occluded-windows",
             "--disable-renderer-backgrounding",
             "--disable-background-timer-throttling",
             "--window-position=-3200,-3200", "--window-size=900,700",
             "--remote-debugging-port=%d" % CDP, "--user-data-dir=" + prof,
             "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        for _ in range(60):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % CDP,
                                            timeout=2) as r:
                    ps = [t for t in json.load(r) if t["type"] == "page"]
                if ps:
                    target = ps[0]
                    break
            except Exception:                              # noqa: BLE001
                time.sleep(0.5)
        if not target:
            raise RuntimeError("连不上调试端口")

        n = [0]
        async with aiohttp.ClientSession() as cm:
            ws = await cm.ws_connect(target["webSocketDebuggerUrl"], max_msg_size=0)

            async def cmd(method, params=None):
                n[0] += 1
                await ws.send_str(json.dumps({"id": n[0], "method": method,
                                              "params": params or {}}))
                while True:
                    m = json.loads(await ws.receive_str())
                    if m.get("id") == n[0]:
                        return m.get("result", {})

            async def js(expr):
                r = await cmd("Runtime.evaluate",
                              {"expression": expr, "returnByValue": True,
                               "awaitPromise": True})
                return r.get("result", {}).get("value")

            await cmd("Runtime.enable")
            await cmd("Page.navigate", {"url": "http://127.0.0.1:%s/settings.html"
                                               % PORT})
            await asyncio.sleep(2.0)
            try:
                await cmd("Browser.grantPermissions",
                          {"origin": "http://127.0.0.1:%s" % PORT,
                           "permissions": ["geolocation"]})
                print("已用 CDP 预授予 geolocation（免得气泡挡住）")
            except Exception as e:                         # noqa: BLE001
                print("预授予失败：%s" % type(e).__name__)

            print("\n=== ① 真机定位 ===")
            # ⚠️ 先确认"授权到底生效没有" —— 不然 code 3 会有两种完全不同的解释
            #    （权限没给 / 给了但定位源不理人），而这两件事的下一步动作完全相反。
            ps = await js("navigator.permissions.query({name:'geolocation'})"
                          ".then(p => p.state).catch(e => 'NA:' + e.message)")
            print("   权限状态: %s" % ps)
            g = await js(GEO_JS)
            print("   %s" % g)
            try:
                d = json.loads(g)
            except Exception:                              # noqa: BLE001
                d = {"ok": False}
            if not d.get("ok"):
                print("   → 拿不到坐标。导航页就该走「照实说查不到」那条路。")
                return 0

            lat, lng = d["lat"], d["lng"]
            print("   精度 ±%d 米" % d["acc"])

            print("\n=== ② 逆地理（这坐标在哪）===")
            re = rest("geocode/regeo", {"location": "%.6f,%.6f" % (lng, lat)})
            if re.get("status") == "1":
                rc = re.get("regeocode", {})
                print("   %s" % (rc.get("formatted_address") or "?"))
            else:
                print("   status=%s info=%s" % (re.get("status"), re.get("info")))

            print("\n=== ③ 周边搜索（按 config 里的关键词顺序试）===")
            best = None
            for kw in KEYWORDS:
                r = rest("place/around", {"location": "%.6f,%.6f" % (lng, lat),
                                          "keywords": kw, "radius": RADIUS,
                                          "offset": 25, "extensions": "all",
                                          "sortrule": "distance"})
                if r.get("status") != "1":
                    print("   %-5s status=%s info=%s" % (kw, r.get("status"), r.get("info")))
                    continue
                ps = r.get("pois") or []
                print("   %-5s 命中 %d 条" % (kw, len(ps)))
                for p in ps[:3]:
                    print("      · %-22s %6s m  %s" % ((p.get("name") or "?")[:22],
                                                       p.get("distance"),
                                                       (p.get("type") or "")[:34]))
                if ps and best is None:
                    best = ps[0]
            if not best:
                print("   → 找不着。小瑞照实说查不到。")
                return 0

            print("\n=== ④ 驾车路线（severity 那句「路线已经准备好」要靠它才敢说）===")
            plng, plat = (best.get("location") or ",").split(",")
            dr = rest("direction/driving",
                      {"origin": "%.6f,%.6f" % (lng, lat),
                       "destination": "%s,%s" % (plng, plat),
                       "extensions": "all", "strategy": 0})
            if dr.get("status") != "1":
                print("   status=%s info=%s → 没有路线，就不能说「已经准备好了」"
                      % (dr.get("status"), dr.get("info")))
                return 0
            path = (dr.get("route") or {}).get("paths", [{}])[0]
            steps = path.get("steps") or []
            npts = sum(len((s.get("polyline") or "").split(";")) for s in steps)
            print("   距离 %s m / 约 %s s / %d 步 / 折线 %d 个点"
                  % (path.get("distance"), path.get("duration"), len(steps), npts))

            km = int(round(int(path.get("distance") or 0) / 1000.0))
            mins = int(round(int(path.get("duration") or 0) / 60.0))
            print("\n=== 小瑞会说（真实数据）===")
            print("   「主人，最近的%s是%s，还有 %d 公里，开车约 %d 分钟。要我导过去吗？」"
                  % (KEYWORDS[0], best.get("name"), km, mins))
            return 0
    finally:
        if proc:
            proc.terminate()
        srv.terminate()
        time.sleep(0.8)
        if srv.poll() is None:
            srv.kill()
        log.close()


if __name__ == "__main__":
    import urllib.parse
    sys.exit(asyncio.run(main()))
