# -*- coding: utf-8 -*-
"""量封面上「左栏文字」和「小瑞立绘」到底谁压着谁、压了多少。

    python _scratch/_probe_cover_geom.py 8765

判据是**几何**不是观感：把它俩的矩形并排报出来，再报"横向重叠多少 px"。
⚠️ 立绘那格是 `object-fit:contain`，**盒子 ≠ 画面**：盒子报 44x46rem 时，
   里面那张 420x613 的图按 contain 只画到 46rem 高（宽 = 46×0.685 ≈ 31.5rem），
   左右还各留一段空白。所以还要单独报**画面**的框（`containBox()`），
   拿盒子去算重叠会把"只是空白"也算成"压住了"。
"""
import asyncio
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
DBG = 9342

JS = r"""
(function(){
  function r(sel){
    var e = document.querySelector(sel);
    if (!e) return null;
    var b = e.getBoundingClientRect();
    return {x:Math.round(b.left), y:Math.round(b.top),
            w:Math.round(b.width), h:Math.round(b.height), r:Math.round(b.right)};
  }
  function containBox(sel){
    var e = document.querySelector(sel);
    if (!e || !e.naturalWidth) return null;
    var b = e.getBoundingClientRect();
    var s = Math.min(b.width / e.naturalWidth, b.height / e.naturalHeight);
    var w = e.naturalWidth * s, h = e.naturalHeight * s;
    return {x:Math.round(b.left + (b.width - w) / 2), y:Math.round(b.top + (b.height - h) / 2),
            w:Math.round(w), h:Math.round(h),
            r:Math.round(b.left + (b.width - w) / 2 + w),
            nat:e.naturalWidth + 'x' + e.naturalHeight};
  }
  return JSON.stringify({
    vw: innerWidth, vh: innerHeight,
    stage: r('.cover-stage'),
    coverL: r('.cover-l'),
    h1: r('.cover-l h1'),
    feats: r('.cover-feats'),
    lastFeat: r('.cover-feats .feat:last-child'),
    coverR: r('.cover-r'),
    mascotBox: r('.cover-r .mascot'),
    halo: r('.cover-r .halo'),
    imgBox: containBox('#coverMascotImg'),
    root: getComputedStyle(document.documentElement).fontSize
  });
})()
"""


async def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    p = subprocess.Popen([EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                          "--remote-debugging-port=%d" % DBG, "--window-size=1672,940",
                          "--no-first-run", "--user-data-dir=" + tempfile.mkdtemp(),
                          "about:blank"],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    t = None
    for _ in range(60):
        try:
            with urllib.request.urlopen("http://127.0.0.1:%d/json/list" % DBG, timeout=2) as r:
                x = [q for q in json.load(r) if q["type"] == "page"]
            if x:
                t = x[0]
                break
        except Exception:
            pass
        time.sleep(0.5)
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(t["webSocketDebuggerUrl"], max_msg_size=0) as ws:
                n = [0]

                async def cmd(m, pr=None):
                    n[0] += 1
                    await ws.send_str(json.dumps({"id": n[0], "method": m, "params": pr or {}}))
                    while True:
                        r = json.loads(await ws.receive_str())
                        if r.get("id") == n[0]:
                            return r.get("result", {})

                await cmd("Page.enable")
                await cmd("Emulation.setDeviceMetricsOverride",
                          {"width": 1672, "height": 940, "deviceScaleFactor": 1,
                           "mobile": False})
                await cmd("Page.navigate", {"url": "http://127.0.0.1:%d/" % port})
                await asyncio.sleep(4.0)
                d = json.loads((await cmd("Runtime.evaluate", {
                    "returnByValue": True, "expression": JS}))["result"]["value"])
    finally:
        for ln in subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                 timeout=20).stdout.splitlines():
            f = ln.split()
            if len(f) >= 5 and f[3] == "LISTENING" and f[1].endswith(":" + str(DBG)):
                subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Stop-Process -Id %s -Force -ErrorAction SilentlyContinue" % f[4]],
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        p.terminate()

    print("视口 %dx%d   根字号 %s" % (d["vw"], d["vh"], d["root"]))
    for k in ("stage", "coverL", "h1", "feats", "lastFeat", "coverR", "mascotBox", "halo",
              "imgBox"):
        v = d[k]
        if not v:
            print("  %-10s  —— 没有这个元素" % k)
            continue
        extra = ("  图 %s" % v["nat"]) if "nat" in v else ""
        print("  %-10s x[%4d..%4d] y[%4d..%4d]  %4dx%d%s"
              % (k, v["x"], v["r"], v["y"], v["y"] + v["h"], v["w"], v["h"], extra))
    # 重叠：文字块右边缘 vs 立绘**画面**左边缘（盒子不算，见文件头）
    txt_r = max([d["h1"]["r"], d["feats"]["r"]])
    img_l = d["imgBox"]["x"]
    halo_l = d["halo"]["x"] if d["halo"] else None
    print("\n  文字块右边缘 %d  |  立绘画面左边缘 %d  |  差 %+d px"
          % (txt_r, img_l, img_l - txt_r))
    print("  （正数 = 立绘画面在文字右边、不压；负数 = 压了这么多 px）")
    if halo_l is not None:
        print("  光晕左边缘 %d（光晕压字是**故意的**，见 pages.css 那段「咬在一起」的注释）"
              % halo_l)


asyncio.run(main())
