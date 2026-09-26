"""一次性探针：把「界面里的字到底多大、有没有撑破容器」实测出来。

为什么必须量、不能算：
  根字号是流式的 —— `html{font-size:clamp(11px, min(100vh/58, 100vw/112), 22px)}`，
  而布局尺寸 **163 处用 rem、只有 14 处用 px**（尺度不变：整个界面靠根字号缩放）。
  所以每个字的实际 px 完全取决于窗口大小：1440 宽根字号 12.86，1920 宽 17.14，
  1024 宽被夹到 11px 底。拿 CSS 里的 rem 值乘 16 去估，能差 25%。
  车规看的是**字符墨迹的视角（角分）**，所以只有量了才算数。

量三件事：
  1. 根字号 / 缩放倍率 —— 看清「设计意图」和「实际渲染」差多少
  2. 每个「有直接文字」的元素的 computed font-size → 换算成 700mm 视距下的角分，
     按 ISO 15008 三条线分档（12' 非关键 / 16' 关键 / 20' 最优）
  3. **溢出**：scrollWidth/Height 超出 clientWidth/Height 的元素（跳过本来就是
     auto/scroll 的容器）。这是「把字调大」唯一的真实风险 —— 改之前先留一份基线，
     改完再跑一次对比，就能证明没撑破。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_probe_type.py [--no-shot]

⚠️ 只量几何与溢出。**答不了**「好不好看」「读起来累不累」—— 那些要人眼。
"""

import asyncio
import base64
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_pages import Session  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
PY = Path(r"D:\Anaconda3\envs\dms\python.exe")
if not PY.exists():
    PY = Path(sys.executable)

SRV = 8811          # 服务端端口
CDP = 9456          # 浏览器调试端口（和 _check_pages 的 9411/9455 错开）
W, H = 1440, 960    # ★ 用户这台机器的**真实 CSS 视口**（14.2"/2880x1920/200%）
SHOT = ROOT / "_scratch" / "type_shot"

# 几何换算（全部实测得来，不是文献值）
CSSPX_MM = 300.0 / W          # 1 CSS px = 0.2083 mm（面板宽 30cm / 1440 CSS px，EDID 实测）
VIEW_MM = 700.0               # ISO 15008 常用视距假设
ARCMIN_PER_CSSPX = (CSSPX_MM / VIEW_MM) * 3437.75      # ≈ 1.023 角分/px
INK_CJK = 0.91                # 汉字墨迹 ÷ font-size（雅黑，canvas 实测）
INK_DIGIT = 0.79              # 数字墨迹 ÷ font-size（雅黑，canvas 实测）

# ⚠️ 2026-09-24：原来这里还有 "nav.html"，那一页当天整页删除（用户「把导航页删了吧」）。
# 它在列表里的话这一页会 404，量到的字号几何全是错误页的 —— 不是报错，是**悄悄量错**。
PAGES = ["index.html", "detail.html", "media.html",
         "settings.html", "chat.html", "cover.html"]

# ISO 15008 三条线（700mm 视距下的字符墨迹视角）
FLOOR_NONCRIT, FLOOR_CRIT, FLOOR_OPT = 12.0, 16.0, 20.0


def wait_port(port, secs=40):
    for _ in range(int(secs * 2)):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=2):
                return True
        except Exception:
            time.sleep(0.5)
    return False


def spawn(port, source):
    log = open(ROOT / "_scratch" / f"_srv_{port}.log", "w", encoding="utf-8")
    return subprocess.Popen([str(PY), str(ROOT / "ui" / "server.py"),
                             "--port", str(port), "--source", source],
                            stdout=log, stderr=subprocess.STDOUT,
                            env={**os.environ, "PYTHONUNBUFFERED": "1",
                                 "PYTHONUTF8": "1"})


JS = r"""
(() => {
  const cs = (el) => getComputedStyle(el);
  const cls = (el) => {
    let c = el.className;
    if (c && c.baseVal !== undefined) c = c.baseVal;   // SVG 的 className 是对象
    return (typeof c === 'string' ? c : '').trim().split(/\s+/).slice(0, 3).join('.');
  };

  // 1) 有直接文字的元素（去重：一个元素只记一次）
  const texts = [];
  const seen = new Set();
  const walk = (el) => {
    for (const n of el.childNodes) {
      if (n.nodeType === 3) {
        if (n.textContent.trim() && !seen.has(el)) {
          seen.add(el);
          const c = cs(el);
          texts.push({ sel: el.tagName.toLowerCase() + (cls(el) ? '.' + cls(el) : ''),
                       px: parseFloat(c.fontSize), fam: c.fontFamily.split(',')[0].replace(/["']/g, ''),
                       wt: c.fontWeight, op: c.opacity,
                       txt: n.textContent.trim().replace(/\s+/g, ' ').slice(0, 12) });
        }
      } else if (n.nodeType === 1) walk(n);
    }
  };
  walk(document.body);

  // 2) 溢出（跳过本来就是滚动容器的）
  const of = [];
  for (const el of document.querySelectorAll('body *')) {
    const c = cs(el);
    const canScrollY = ['auto', 'scroll'].includes(c.overflowY);
    const canScrollX = ['auto', 'scroll'].includes(c.overflowX);
    const cw = el.clientWidth, ch = el.clientHeight;
    if (!canScrollX && cw > 0 && el.scrollWidth > cw + 1)
      of.push({ sel: el.tagName.toLowerCase() + (cls(el) ? '.' + cls(el) : ''),
                axis: 'x', over: el.scrollWidth - cw, got: el.scrollWidth, box: cw });
    if (!canScrollY && ch > 0 && el.scrollHeight > ch + 1)
      of.push({ sel: el.tagName.toLowerCase() + (cls(el) ? '.' + cls(el) : ''),
                axis: 'y', over: el.scrollHeight - ch, got: el.scrollHeight, box: ch });
  }

  const de = document.documentElement;
  return JSON.stringify({
    root: parseFloat(cs(de).fontSize),
    vw: window.innerWidth, vh: window.innerHeight,
    docX: de.scrollWidth, docY: de.scrollHeight,
    ntext: texts.length, texts, of: of.slice(0, 40), nof: of.length,
  });
})()
"""


async def main():
    shot = "--no-shot" not in sys.argv
    if shot:
        SHOT.mkdir(parents=True, exist_ok=True)
    print("=" * 74)
    print("字号 / 角分 / 溢出 基线实测      视口 %dx%d   视距 %.0fmm" % (W, H, VIEW_MM))
    print("=" * 74)
    print("几何：1 CSS px = %.4f mm -> %.4f 角分/px（视距 %.0fmm）"
          % (CSSPX_MM, ARCMIN_PER_CSSPX, VIEW_MM))
    print("      汉字墨迹 %.2f em、数字 %.2f em（雅黑，canvas actualBoundingBox 实测）"
          % (INK_CJK, INK_DIGIT))

    p = spawn(SRV, "demo")
    try:
        if not wait_port(SRV):
            print("!!  服务起不来，见 _scratch/_srv_%d.log" % SRV)
            return 1
        async with Session(CDP) as s:
            await s.cmd("Emulation.setDeviceMetricsOverride",
                        {"width": W, "height": H, "deviceScaleFactor": 1,
                         "mobile": False})
            for pg in PAGES:
                await s.cmd("Page.navigate", {"url": f"http://127.0.0.1:{SRV}/{pg}"})
                await asyncio.sleep(2.0)
                d = await s.js(JS)
                if not isinstance(d, dict):
                    print("\n### %-14s  ❌ 没量到" % pg)
                    continue

                # 角分（汉字墨迹口径 —— 中文界面的可读性看这个）
                for t in d["texts"]:
                    t["am"] = t["px"] * INK_CJK * ARCMIN_PER_CSSPX
                bad = [t for t in d["texts"] if t["am"] < FLOOR_NONCRIT]
                crit = [t for t in d["texts"] if t["am"] < FLOOR_CRIT]
                opt = [t for t in d["texts"] if t["am"] >= FLOOR_OPT]

                print("\n### %-14s 根字号 %5.2fpx（%.2f×16）  文字元素 %d 个"
                      % (pg, d["root"], d["root"] / 16.0, d["ntext"]))
                print("     <12' 违法 %-3d | <16' 未达关键档 %-3d | ≥20' 最优 %-3d"
                      % (len(bad), len(crit), len(opt)))
                if bad:
                    worst = sorted(bad, key=lambda t: t["px"])[:5]
                    for t in worst:
                        print("       %5.2fpx %5.2f'  %-26s %s"
                              % (t["px"], t["am"], t["sel"][:26], t["txt"]))
                if d["nof"]:
                    print("     ⚠️ 溢出元素 %d 个（横向最要命）:" % d["nof"])
                    for o in d["of"][:6]:
                        print("        %s %s 超出 %dpx (%d > %d)"
                              % (o["axis"], o["sel"][:30], o["over"], o["got"], o["box"]))
                else:
                    print("     ✅ 零溢出")
                if d["docX"] > d["vw"]:
                    print("     🔴 整页横向溢出：doc %d > 视口 %d" % (d["docX"], d["vw"]))

                if shot:
                    r = await s.cmd("Page.captureScreenshot", {"format": "png"})
                    (SHOT / pg.replace(".html", ".png")).write_bytes(
                        base64.b64decode(r["data"]))

            if s.errs:
                print("\n⚠️ 浏览器报错/警告 %d 条：" % len(s.errs))
                for k, m in s.errs[:8]:
                    print("   [%s] %s" % (k, m))
            else:
                print("\n✅ 全程零控制台报错")
        if shot:
            print("截图 -> %s" % SHOT)
    finally:
        p.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
