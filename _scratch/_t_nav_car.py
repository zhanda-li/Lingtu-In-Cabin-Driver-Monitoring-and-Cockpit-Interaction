# -*- coding: utf-8 -*-
"""图上那个"车"为什么有一帧是没的 —— 直接问浏览器，别猜。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_t_nav_car.py 8804

`_probe_nav_sim.py` 第 ③ 段有一条红：按了 ▶ 之后 1.5 秒 `car=0`（点没画出来），
可同一刻灰线已经在长了。灰线（`simPaintDone` → `simDonePath` → `simPos`）和车
（`simPaintCar`）用的是**同一个 `pos`**，所以"pos 是 null"这条解释不成立。
同一个脚本上一趟跑又是绿的 —— 说明它**不是每次都这样**，得量。

这个脚本顺带量三个数（`_probe_nav_sim.py` 里对不上、单看它看不出来的）：
    `SIM.totalS` / `SIM.totalM` / `SIM.totalW` —— 演示那把"尺"到底是什么单位、
    `SIM.geoms.length` vs `curSteps().length` vs `$('gdList').children.length`。
"""
import asyncio
import os
import subprocess
import sys
import time
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if len(sys.argv) < 2:
    sys.argv.append("8804")

import _check_pages as CP                                     # noqa: E402
from _check_pages import Session                              # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CDP = 9433
ORG = "静海 · 京沪高速一带"
DST = "无锡"

# ① 单独造一个 CircleMarker —— 不碰地图，只看这个类本身会不会抛。
MK = r"""(()=>{
  try {
    const m = new AMap.CircleMarker({ center:[120.1,30.2], radius:8,
      fillColor:'#1f4fa8', fillOpacity:1, strokeColor:'#fff', strokeWeight:3,
      zIndex:96, label:{ content:'车（演示）', direction:'top' } });
    return 'ok ' + (m && m.CLASS_NAME ? m.CLASS_NAME : typeof m);
  } catch (e) { return 'throw: ' + (e && e.message); }
})()"""

# ①b `CircleMarker` 上有哪几个方法、`setPosition` 会不会抛 —— `_t_nav_car` 量到
#     `ovCar` 在 有/null 之间**一跳一跳**（每帧新建一个再抛），像是某个 setter 没有。
MK2 = r"""(()=>{
  const out = {};
  try {
    const m = new AMap.CircleMarker({ center:[120.1,30.2], radius:8 });
    ['setPosition','setCenter','getPosition','getCenter','setOptions','show','hide']
      .forEach(k => { out[k] = typeof m[k]; });
    try { m.setPosition([120.2,30.3]); out._setPosition = 'ok'; }
    catch (e) { out._setPosition = 'throw: ' + (e && e.message); }
    try { m.setCenter([120.2,30.3]); out._setCenter = 'ok'; }
    catch (e) { out._setCenter = 'throw: ' + (e && e.message); }
  } catch (e) { out._new = 'throw: ' + (e && e.message); }
  return JSON.stringify(out);
})()"""

# ② 演示跑起来之后，图上到底有什么。
#    ⚠️ 整个包在 try 里：这条式子**返回过 None**（说明抛了），而 S.js 抛了只会给
#       你一个 None，什么也看不出。把 `e.message` 带回来才知道是哪一句。
DUMP = r"""(()=>{
  try {
    const g = SIM.geoms || [];
    return {
      playing: SIM.playing, t: +SIM.t.toFixed(5),
      totalS: SIM.totalS, totalM: SIM.totalM, totalW: SIM.totalW,
      geoms: g.length, usable: g.filter(x => x.pts.length > 1).length,
      step: SIM.step, stepIdx: stepIdx,
      ovCar: (typeof ovCar === 'undefined') ? '未定义'
             : (ovCar ? ('有 ' + (ovCar.CLASS_NAME || '?')) : 'null'),
      ovDone: ovDone ? '有' : 'null',
      // ⚠️ 原来看的是 `map.getOverlays()` —— 这个 SDK 上没有这个方法（报
      //    "not a function"）。换成"它到底是什么对象"，比数覆盖物更有用。
      mapCls: (!map) ? 'null' : (map.CLASS_NAME || typeof map),
      steps: curSteps().length,
      rows: document.getElementById('gdList').children.length,
      listOpen: SIM.listOpen,
    };
  } catch (e) { return { err: String(e && e.message || e) }; }
})()"""


async def main():
    log = open(os.path.join(ROOT, "runs", "_t_nav_car_srv.log"), "w",
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
            await S.goto("/nav.html", wait=2.5)
            print("typeof XQ.nav =", await S.js("typeof XQ.nav"))
            print("AMap          =", await S.js("typeof AMap"))
            for _ in range(30):
                t = await S.js("$('orgText').textContent")
                if t and "正在定位" not in t:
                    break
                await asyncio.sleep(0.7)

            print("\n① 单独造一个 CircleMarker：%s" % (await S.js(MK),))
            print("①b 它有哪些方法：%s" % (await S.js(MK2),))

            # 起终点 + 算路
            await S.js("(()=>{const i=$('orgIn');i.value=%s;"
                       "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',"
                       "bubbles:true}));return 1})()" % ("'" + ORG + "'"))
            await S.js("(()=>{const i=$('dstIn');i.value=%s;i.focus();"
                       "i.dispatchEvent(new Event('input',{bubbles:true}));"
                       "return 1})()" % ("'" + DST + "'"))
            for _ in range(40):
                if await S.js("XQ.nav.state().list"):
                    break
                await asyncio.sleep(0.5)
            await S.js("$('dstList').querySelector('button').click(); 1")
            for _ in range(40):
                if (await S.js("XQ.nav.state()")).get("routes"):
                    break
                await asyncio.sleep(0.7)
            await S.js("$('navStart').click(); 1")
            await asyncio.sleep(1.0)
            print("\n② 进了导航（还没按 ▶）：")
            d = await S.js(DUMP)
            for k in sorted(d, key=str):
                print("     %-10s %s" % (k, d[k]))

            print("\n③ 按 ▶ 演示，之后每秒 dump 一次（看车是第几秒出现的）")
            await S.js("$('simPlay').click(); 1")
            for i in range(6):
                await asyncio.sleep(1.0)
                d = await S.js(DUMP)
                if "err" in d:
                    print("  +%ds  抛了：%s" % (i + 1, d["err"]))
                    continue
                print("  +%ds  playing=%s t=%s step=%s ovCar=%s ovDone=%s "
                      "geoms=%s steps=%s rows=%s"
                      % (i + 1, d["playing"], d["t"], d["step"], d["ovCar"],
                         d["ovDone"], d["geoms"], d["steps"], d["rows"]))
            print("\n     `AMap.CircleMarker` 第二次：%s" % (await S.js(MK),))

            errs = [e for e in S.errs if "willReadFrequently" not in str(e)]
            print("\n④ 控制台报错 %d 条：" % len(errs))
            for e in errs[:8]:
                print("     ·", str(e)[:220])
    finally:
        srv.terminate()
        time.sleep(0.8)
        if srv.poll() is None:
            srv.kill()
        log.close()


asyncio.run(main())
