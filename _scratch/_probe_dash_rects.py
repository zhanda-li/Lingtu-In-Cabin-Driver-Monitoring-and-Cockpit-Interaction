# -*- coding: utf-8 -*-
"""首页主视觉那块的小瑞图：把各块的**实际渲染矩形**打出来，并且回答一个具体问题 ——
**如果给它开 `pointer-events`，会挡住谁的点击？**

    PYTHONIOENCODING=utf-8 D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_probe_dash_rects.py [端口] [等几秒] [路径]

骨架照抄 `_probe_cover_rects.py`（同一个 CDP 套路）。
⚠️ 调试端口用 9335（9334 是封面的、9336 是 `_cov_variants.py` 的）—— 互不撞。
⚠️ 只读不落盘。收尾按**端口**杀自己起的 headless Edge，绝不按镜像名杀 `msedge.exe`。

--------------------------------------------------------------------------
三件事
--------------------------------------------------------------------------
1. 矩形：小瑞 vs `.dash-copy`（标题）/ `.dash-say`（问候气泡）/ `.dash-strip`
   里那四颗入口。撞上了就是"图盖住字"或"图盖住按钮"。
2. **点击穿透**（★ 这是本脚本存在的主要理由）。`pointer-events:none` 现在就是
   为了让小瑞不抢点击 —— 想给它加"点一下换形象"，先得知道它底下压着什么。
   做法：在小瑞的矩形上打 **9x9 网格**，逐点 `elementFromPoint`（那时图还是
   `pointer-events:none`，所以拿到的正是"图下面那个元素"），然后按
   **"这个元素是不是落在一个可点的祖先里（a / button / input / [onclick] /
   [role=button]）"** 归类。有任何一个采样点落在可点祖先里，开 pointer-events
   就是在**偷走**那个点击 —— 那时正确的做法是别开，并在报告里明说。
3. 换 `l` 那套素材之后矩形会不会变（`.dash-mascot` 是 `height:78%;width:auto`，
   宽高比一变，盒子的宽就跟着变，而 `right` 是写死的）。把 src 临时换成
   `assets/xq/l/p02.webp` 再量一遍，和现在那张逐项对照。

⚠️ 第 3 项的判据是**角色的渲染矩形**，不是 `<img>` 的盒子 —— 姿势库那套画布
   带着透明边（角色只占画布宽的 90.8%），盒子变宽不等于人变宽。脚本里两套都打。
"""
import asyncio
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
WAIT = float(sys.argv[2]) if len(sys.argv) > 2 else 4.0
PATH_ = sys.argv[3] if len(sys.argv) > 3 else "/index.html"
VW, VH = 1672, 940
CDP = 9335
SWAP_SRC = "assets/xq/l/p02.webp"      # 第 3 项要临时换成的那张

EDGE = next((p for p in (
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe") if os.path.exists(p)), None)

# 这几个是**可点**的东西（挡住了就是真问题）；其余是装饰（挡住了无所谓）。
CLICKABLE = ".dash-entry, .dash-cta, .rail a, .rail button, .ri, button, a, input"

SPEC = [
    ("主视觉面板", ".dash-visual"),
    ("文字块", ".dash-copy"),
    ("标题 h1", ".dash-copy h1"),
    ("副标题", ".dash-copy .dash-sub"),
    ("小瑞图", ".dash-mascot"),
    ("问候气泡", ".dash-say"),
    ("入口条", ".dash-strip"),
    ("左栏", ".rail"),
]
PAIRS = [
    ("小瑞图", "问候气泡"), ("小瑞图", "文字块"), ("小瑞图", "副标题"),
    ("小瑞图", "入口条"), ("小瑞图", "左栏"),
]

PRELUDE = """(() => {
  const spec = %s, pairs = %s, CLICK = %s;
  const rect = (e) => { const r = e.getBoundingClientRect();
                        return [r.left, r.top, r.width, r.height]; };
  const inter = (a, b) => { if (!a || !b) return null;
    const ox = Math.min(a[0]+a[2], b[0]+b[2]) - Math.max(a[0], b[0]);
    const oy = Math.min(a[1]+a[3], b[1]+b[3]) - Math.max(a[1], b[1]);
    return (ox > 0 && oy > 0) ? +(ox*oy).toFixed(1) : 0; };
  const name = (e) => !e ? '(null)' : e.tagName.toLowerCase()
      + (e.id ? '#'+e.id : '')
      + (typeof e.className === 'string' && e.className.trim()
         ? '.'+e.className.trim().split(/\\s+/).join('.') : '');
  const snap = () => {
    const R = {};
    for (const [n,q] of spec) { const e = document.querySelector(q); R[n] = e ? rect(e) : null; }
    return R;
  };
  /* 角色**可见**部分的矩形：就地把图画进 canvas 扫 alpha>32 的边界。不依赖任何
     外部数据 —— "盒子变宽了但人没变"这件事只有这样才能直接量出来。
     ⚠️ 同源图，canvas 不会被 taint（换 http:// 其它域就会当场抛 SecurityError）。 */
  const artRect = (im) => {
    if (!im || !im.naturalWidth) return null;
    const c = document.createElement('canvas');
    c.width = im.naturalWidth; c.height = im.naturalHeight;
    const g = c.getContext('2d');
    g.drawImage(im, 0, 0);
    const d = g.getImageData(0, 0, c.width, c.height).data;
    let x0 = 1e9, x1 = -1, y0 = 1e9, y1 = -1;
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        if (d[(y*c.width + x)*4 + 3] > 32) {
          if (x < x0) x0 = x; if (x > x1) x1 = x;
          if (y < y0) y0 = y; if (y > y1) y1 = y;
        }
      }
    }
    if (x1 < 0) return null;
    const b = im.getBoundingClientRect();
    const sx = b.width / c.width, sy = b.height / c.height;
    return [ b.left + x0*sx, b.top + y0*sy, (x1-x0+1)*sx, (y1-y0+1)*sy ];
  };
  /* 点击穿透：9x9 网格逐点 elementFromPoint。**此刻图是原样的 pointer-events**
     （首页那张是 none），所以拿到的正是"图下面那个元素"。 */
  const probe = (im) => {
    if (!im) return null;
    const r = im.getBoundingClientRect();
    const hits = {}, clicks = {}, n = 8;
    for (let i = 0; i <= n; i++) for (let j = 0; j <= n; j++) {
      const e = document.elementFromPoint(r.left + r.width*(i/n),
                                          r.top + r.height*(j/n));
      const k = name(e);
      hits[k] = (hits[k] || 0) + 1;
      if (e && e.closest(CLICK)) {
        const c = name(e.closest(CLICK));
        clicks[c] = (clicks[c] || 0) + 1;
      }
    }
    return { hits, clicks, total: (n+1)*(n+1) };
  };
  const measure = (im) => {
    const R = snap();
    return { R, art: artRect(im), nat: im ? [im.naturalWidth, im.naturalHeight] : null,
             pe: im ? getComputedStyle(im).pointerEvents : null,
             pairs: pairs.map(([a,b]) => [a, b, inter(R[a], R[b])]), probe: probe(im) };
  };
  window.__dashProbe = { measure: measure };
  return 1;
})()"""

# 四段：① 预置工具函数 ② 量「现在这张」 ③ 换 src ④ 等解码完再量一遍。
# ⚠️ 分四次 evaluate 是为了**不把 load 事件包进 Promise** —— 第一版写成
#    `Promise` + `awaitPromise:true`，回了个 null 值，现场什么信息都没有，白跑一轮。
# ⚠️ ②④ 都必须**接在已经做过 % 替换的 PRELUDE 后面**：`PRELUDE % (…)` 只替换
#    一次，先拼接再替换会留下字面量 `%s`，页面里当场 SyntaxError。
#    （第一版就是这么写的，报的是「Unexpected token '%'」，看着像页面坏了。）
_FULL = PRELUDE % (json.dumps(SPEC, ensure_ascii=False), json.dumps(PAIRS, ensure_ascii=False),
                   json.dumps(CLICKABLE))
JS = [
    _FULL,
    _FULL + """;JSON.stringify({root: getComputedStyle(document.documentElement).fontSize,
  before: window.__dashProbe.measure(document.querySelector('.dash-mascot'))})""",
    """(() => { const im = document.querySelector('.dash-mascot');
       if (!im) return 'no-mascot';
       window.__dashOld = im.getAttribute('src');
       im.setAttribute('src', %s);
       return 'ok'; })()""" % json.dumps(SWAP_SRC),
    _FULL + """;JSON.stringify({root: getComputedStyle(document.documentElement).fontSize,
  after: window.__dashProbe.measure(document.querySelector('.dash-mascot'))})""",
]


def kill_port(port):
    """按**端口**杀自己起的那个 headless Edge。

    ⚠️ `powershell` / `taskkill` **不在 PATH 里**（这台机器的 shell 里 coreutils 基本
       全没了）。第一版这里写的是裸名，结果它正好在最外层 `finally` 里抛
       `FileNotFoundError` —— 活干完了却非 0 退出，而且**该收的进程没收掉**，
       留下一个骗着调试端口的僵尸 Edge。所以这里一律写全路径。"""
    PS = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"
    TK = r"C:\Windows\System32\taskkill.exe"
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                             timeout=20).stdout
    except Exception as e:
        print("  netstat 拿不到：%s" % e)
        return
    pids = {ln.split()[4] for ln in out.splitlines()
            if len(ln.split()) >= 5 and ln.split()[0] == "TCP"
            and ln.split()[3] == "LISTENING" and ln.split()[1].endswith(":" + str(port))}
    if not pids:
        return
    for pid in pids:
        for cmd in ((PS, "-NoProfile", "-Command",
                     "Stop-Process -Id %s -Force -ErrorAction SilentlyContinue" % pid),
                    (TK, "/PID", pid, "/T", "/F")):
            if not os.path.exists(cmd[0]):
                continue
            try:
                subprocess.run(list(cmd), stdout=subprocess.DEVNULL,
                               stderr=subprocess.DEVNULL, timeout=30)
            except Exception as e:
                print("  杀 %s 失败：%s" % (pid, e))
    for _ in range(15):
        try:
            busy = subprocess.run(["netstat", "-ano"], capture_output=True, text=True,
                                  timeout=20).stdout
        except Exception:
            return
        if not any(":" + str(port) in l and "LISTENING" in l for l in busy.splitlines()):
            print("  已收掉端口 %d（pid %s）" % (port, ",".join(sorted(pids))))
            return
        time.sleep(1)
    print("  ⚠️ 端口 %d 还占着（pid %s），看一眼" % (port, ",".join(sorted(pids))))


async def main():
    if not EDGE:
        print("找不到 msedge.exe")
        return 1
    import shutil
    udd = os.path.join("runs", "_edge_profile_dashprobe")
    shutil.rmtree(udd, ignore_errors=True)
    os.makedirs(udd, exist_ok=True)
    subprocess.Popen(
        [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         "--remote-debugging-port=%d" % CDP, "--window-size=%d,%d" % (VW, VH),
         "--no-first-run", "--user-data-dir=" + os.path.abspath(udd), "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    d = None
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
                          {"width": VW, "height": VH, "deviceScaleFactor": 1,
                           "mobile": False})
                await cmd("Page.navigate",
                          {"url": "http://127.0.0.1:%s%s" % (PORT, PATH_)})
                await asyncio.sleep(WAIT)

                async def val(expr, tag):
                    r = await cmd("Runtime.evaluate",
                                  {"expression": expr, "returnByValue": True})
                    v = r.get("result", {}).get("value")
                    if v is None:
                        print("「%s」那段 JS 没回值，原样打出来：" % tag)
                        print(json.dumps(r, ensure_ascii=False)[:2500])
                        return None
                    return v

                if await val(JS[0], "预置工具") != 1:
                    return 1
                s1 = await val(JS[1], "量现在这张")
                if s1 is None:
                    return 1
                await val(JS[2], "换 src")
                # 等新图真的解码完（只看 `complete` + naturalWidth，比 sleep 靠谱）
                for _ in range(40):
                    ok = await val("(() => { const i = document.querySelector('.dash-mascot');"
                                   " return !!(i && i.complete && i.naturalWidth); })()",
                                   "等解码")
                    if ok:
                        break
                    await asyncio.sleep(0.25)
                s3 = await val(JS[3], "量换过之后")
                if s3 is None:
                    return 1
                d1, d3 = json.loads(s1), json.loads(s3)
                d = {"root": d1["root"], "before": d1["before"], "after": d3["after"]}
    finally:
        kill_port(CDP)
    if not d:
        return 1

    print("\n%s  视口 %dx%d  root font-size = %s" % (PATH_, VW, VH, d["root"]))
    for tag, key in (("现在这张", "before"), ("换成 %s" % SWAP_SRC, "after")):
        b = d[key]
        if not b:
            continue
        print("\n── %s ──" % tag)
        if b.get("nat"):
            print("  素材 %dx%d" % (b["nat"][0], b["nat"][1]))
        print("  %-10s %8s %8s %8s %8s" % ("元素", "x", "y", "宽", "高"))
        for nm, _ in SPEC:
            r = b["R"].get(nm)
            if r is None:
                print("  %-10s   —— 选择器没找到 ——" % nm)
                continue
            print("  %-10s %8.1f %8.1f %8.1f %8.1f" % (nm, r[0], r[1], r[2], r[3]))
        if b.get("art"):
            a = b["art"]
            print("  小瑞**角色**（alpha>32 的边界，不是 img 盒子）：x %.1f y %.1f 宽 %.1f 高 %.1f"
                  % (a[0], a[1], a[2], a[3]))
        print("  相交面积（>0 就是撞上了）：")
        for a_, b_, ov in b["pairs"]:
            print("    %-8s x %-8s %s" % (a_, b_,
                  "——" if ov is None else "%9.1f px² %s" % (ov, "  ★撞" if ov else "")))
        pb = b["probe"]
        # ⚠️ 页面没找到 `.dash-mascot` 时 probe 回 null —— 这条要显式说一句，
        #    不然下面 `pb["total"]` 直接 TypeError，看着像脚本坏了，
        #    实际是**跑错了页**（或者元素真没了）。
        if not pb:
            print("  ⚠️ 没找到 `.dash-mascot`，这一轮**点不到东西** —— 先确认跑的是 /index.html。")
            continue
        print("  它底下压着什么（9x9 = %d 个采样点，elementFromPoint）：" % pb["total"])
        for k, v in sorted(pb["hits"].items(), key=lambda x: -x[1]):
            print("    %-4d  %s" % (v, k))
        if pb["clicks"]:
            print("  ★ 采样点落在**可点元素**里 %d/%d 个：" % (sum(pb["clicks"].values()), pb["total"]))
            for k, v in sorted(pb["clicks"].items(), key=lambda x: -x[1]):
                print("      %-4d  %s" % (v, k))
            print("    → 给它开 pointer-events 会**偷走**上面这些点击。")
        else:
            print("  → 可点采样点 0 个：现在开 pointer-events **不会**偷走任何点击。")
    return 0


sys.exit(asyncio.run(main()))
