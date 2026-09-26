# -*- coding: utf-8 -*-
"""「每敲一个字都要有相关地点推荐」—— 先量，别猜。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_t_nav_type.py 8802

用户 2026-09-26 原话：
    「我在起点终点每输入一个字 都要有相关的地点推荐啊 不要我点enter才推荐
     以及去除字才推荐」

「只有删字才推荐」这个描述很关键 —— 它指向**缓存命中**那条路：
删字时那个前缀多半早先已经问过了（`TYPING.cache` 里有），一命中就**立刻**回；
而新敲的字要走网络，正好撞上 `runType()` 开头的 `if (TYPING.busy) return;`
（那一条**丢掉之后不重排**，见下面 `FAST` 那段）。本脚本两件事一起量：
  ① 服务端 `/amap/search` 对一个字 / 两个字 / 三个字分别回什么（一个字真的搜不出来？）
  ② 真浏览器里**一个字一个字敲**，每一步把下拉框的内容抓下来（慢敲 / 快敲各一遍）
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
if len(sys.argv) < 2:
    sys.argv.append("8802")

import _check_pages as CP                                     # noqa: E402
from _check_pages import Session                              # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CDP = 9423
ORG = "静海 · 京沪高速一带"

# 每一步之后要抓的东西。`TYPING` 是 nav.html 内联脚本里的顶层 `const` ——
# 顶层 const/let 在**全局词法环境**里，CDP 的 Runtime.evaluate 按名字就能取到
# （这个项目正是靠这件事踩过"两个脚本顶层名字撞车"的坑）。
PROBE = r"""(()=>{
  const box = document.getElementById('dstList');
  const txt = box ? box.innerText.replace(/\s+/g, ' ').trim() : '';
  return {
    hidden: box ? !!box.hidden : null,
    n:    box ? box.querySelectorAll('button').length : -1,
    tip:  box && box.firstElementChild
            ? (box.firstElementChild.className || '') : '',
    txt:  txt.slice(0, 70),
    busy: !!TYPING.busy,
    pending: TYPING.pending || '',
    seq:  TYPING.seq,
    cache: Object.keys(TYPING.cache),
    stop: Math.max(0, Math.round((TYPING.stopUntil - Date.now()) / 1000)),
  };
})()"""

# 敲一个字（**已上屏**那一下，中文输入法走 `compositionend` → `onType`，
# 和这里 dispatch 一个 input 是同一个入口）。
TYPE = r"""(()=>{const i=$('dstIn');i.value=%s;i.focus();
  i.dispatchEvent(new Event('input',{bubbles:true}));return 1})()"""

# 「这一发落地了吗」：`#dstList` 里还写着「正在问…」就是**没落地**（那一发被吞了）。
# ⚠️ 落地也可能是 `.dtip`（"没搜到"那种实话），所以判据是**文字**，不是元素类型。
LANDED = r"""(()=>{
  const b = document.getElementById('dstList');
  if (!b || b.hidden) return {landed: false, n: 0, txt: ''};
  const t = b.innerText.replace(/\s+/g, ' ').trim();
  return {landed: !/正在问/.test(t), n: b.querySelectorAll('button').length,
          txt: t.slice(0, 60)};
})()"""


async def wait_render(S, timeout=3.0):
    """等下拉框**不再是「正在问高德…」**。回 (秒数, 内容)；超时回 (None, ...)。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        r = await S.js(LANDED)
        if r["landed"]:
            return time.time() - t0, r["txt"]
        await asyncio.sleep(0.12)
    return None, ""


async def main():
    log = open(os.path.join(ROOT, "runs", "_t_nav_type_srv.log"), "w",
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

        # ── ① 服务端：一个字 / 两个字 / 三个字 ────────────────────────────
        print("\n① `/amap/search` 对不同长度的关键词回什么（HTTP 层，直接问）")
        for kw in ["无", "无锡", "无锡站", "站", "服", "服务区", "京沪高速"]:
            u = (CP.BASE + "/amap/search?kw="
                 + urllib.request.quote(kw.encode("utf-8")))
            t0 = time.time()
            try:
                with urllib.request.urlopen(u, timeout=15) as fp:
                    d = json.loads(fp.read().decode("utf-8"))
                ms = int((time.time() - t0) * 1000)
                first = (d.get("list") or [{}])[0].get("name", "")
                print("   「%s」 ok=%s 候选=%s %sms  why=%s  第一条=%s"
                      % (kw, d.get("ok"), len(d.get("list") or []), ms,
                         (d.get("why") or "-")[:40], first))
            except Exception as e:                             # noqa: BLE001
                print("   「%s」 请求本身失败：%s" % (kw, e))
            await asyncio.sleep(0.35)      # 别自己把 QPS 撞了

        # ── ② 浏览器：一个字一个字敲 ─────────────────────────────────────
        async with Session(CDP) as S:
            await S.goto("/nav.html", wait=2.5)
            boot = await S.js("typeof XQ.nav")
            errs0 = [e for e in S.errs if "willReadFrequently" not in str(e)]
            if boot != "object" or errs0:
                print("!! 页面脚本没起来（%s）" % boot)
                for e in errs0[:5]:
                    print("   ·", str(e)[:200])
                return 1
            for _ in range(30):
                t = await S.js("$('orgText').textContent")
                if t and "正在定位" not in t:
                    break
                await asyncio.sleep(0.7)
            # 起点用预设（坐标页面里就有）
            await S.js("(()=>{const i=$('orgIn');i.value=%s;"
                       "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',"
                       "bubbles:true}));return 1})()" % ("'" + ORG + "'"))
            await asyncio.sleep(1.0)

            for name, gap in (("慢敲（一个字停 0.8 s）", 0.8),
                              ("正常速度（一个字停 0.6 s）", 0.6),
                              ("快敲（一个字停 0.15 s）", 0.15)):
                print("\n② %s —— 目的地框里逐字敲「无锡站」" % name)
                await S.js("(()=>{const i=$('dstIn');i.value='';"
                           "i.dispatchEvent(new Event('input',{bubbles:true}));"
                           "return 1})()")
                await asyncio.sleep(0.6)
                for i in range(1, 4):
                    kw = "无锡站"[:i]
                    await S.js(TYPE % ("'" + kw + "'"))
                    await asyncio.sleep(gap)
                    # ★ 这一条才是用户要的那件事：**敲完这个字之后，屏幕上有没有
                    #   落到这个字的那张表**（不是"正在问…"那种还没落地的样子）。
                    dt, what = await wait_render(S)
                    p = await S.js(PROBE)
                    print("   「%s」 落地=%s  候选=%s  缓存=%s busy=%s 待办=%r"
                          % (kw, ("%.2fs" % dt) if dt is not None else "**没有**",
                             p["n"], p["cache"], p["busy"], p["pending"]))
                    print("        %s" % (p["txt"] or "（框里是空的）"))
                await asyncio.sleep(2.0)
                p = await S.js(PROBE)
                print("   再等 2 s：候选=%s  busy=%s  最终停在：%s"
                      % (p["n"], p["busy"], (p["txt"] or "（空）")[:50]))
            print("\n   控制台报错：%d 条"
                  % len([e for e in S.errs
                         if "willReadFrequently" not in str(e)]))
            for e in S.errs[:5]:
                print("   ·", str(e)[:160])
        return 0
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:                                      # noqa: BLE001
            srv.kill()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
