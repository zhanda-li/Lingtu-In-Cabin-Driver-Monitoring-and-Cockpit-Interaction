# -*- coding: utf-8 -*-
"""一次性探针：多媒体页到底有多少纵向空间、每一行吃掉多少、底下还剩多少。

    python _scratch/_probe_geom.py

**这个脚本是用来"量"的，不是用来"判"的** —— 判据在 `_check_media_lib.py`。
media.html 的栅格注释里那句「加东西之前先量」说的就是它：改 `.now-row .art`
或者 `.mp-lib ul.tracks` 的 `max-height` 之前先跑一遍，别照着 940 那个设计高度
心算（那是旧版塌掉的原因，见 media.html 里 `.mp-grid` 那段注释）。

⚠️ 自带宽高：它自己起一份服务（端口 8799、`--source demo` 不吃摄像头），
   跑完自己收摊。所以**别在 8799 上另起服务**，也别跟回归脚本同时跑。

2026-09-24 清账：原来它还会对着 `/static/_tmp_old_media.html` 跑第二遍做新旧
对照，那个文件早没了，于是每次都在第二遍上抛 TypeError —— 对照做不成，第一遍
的数也淹在回溯里。删掉第二遍，改成只量当前版 + 把"底下还剩多少"直接打出来。
"""
import asyncio, os, subprocess, sys, time, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _check_pages import Session

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT, CDP = 8799, 9419
BASE = "http://127.0.0.1:%d" % PORT

# ⚠️ 2026-09-24：查询里去掉了 `.mp-rec`（推荐歌单行，已删）、`.mp-eq`（音效设置
#    卡片，更早一次删的）和 `#mpHonest`（如实说明段，已删）—— 量不到的槽位留着
#    只会每次都打一行 None，读的人分不清"删掉了"和"探针写错了"。
#
# ⚠️⚠️ **整段包了 try/catch，返回 `{err: …}` 而不是抛出去。** 这不是防御式编程
#    的习惯，是这里踩过：`S.js` 在页面抛异常时返回的是 **None**（拿不到 `value`），
#    于是 `g["innerH"]` 报 `'NoneType' object is not subscriptable` ——
#    看起来像"探针写错了"，实际上信息全在页面那边，一句都传不回来。
#    同理**派生量全部写成可空的**（`.mp-lib` 不在时 `gapBottom` 给 null，
#    不是去 `.b` 上崩）：量版式的脚本最不该死在版式上。
Q = ("(() => { try {"
     " const R=(s)=>{const e=document.querySelector(s); if(!e) return null;"
     " const b=e.getBoundingClientRect();"
     " return {t:Math.round(b.top),b:Math.round(b.bottom),h:Math.round(b.height),"
     " l:Math.round(b.left),r:Math.round(b.right),w:Math.round(b.width)};};"
     " const sb=document.querySelector('.sub-body');"
     " if(!sb) return JSON.stringify({err:'页面上没有 .sub-body'});"
     " const sbb=sb.getBoundingClientRect();"
     " const lib=R('.mp-lib'), xq=R('.mp-xq'), ul=R('.tracks'), nm=R('#tName');"
     " return JSON.stringify({innerH:window.innerHeight,"
     " dpr:window.devicePixelRatio, zoom:Math.round(window.outerWidth/window.innerWidth*100)/100,"
     " topbar:R('.topbar'), mainsub:R('.main.sub'), sub:R('.sub-body'),"
     " subScroll:sb.scrollHeight, subClient:sb.clientHeight, ptitle:R('.ptitle'),"
     " talk:R('.talk'), hero:R('.mp-hero'),"
     " tname:nm, meta:R('.now-row .meta'), head:R('.now-head'), art:R('.now-row .art'),"
     " metaAvail:(() => { const hd=document.querySelector('.now-head');"
     " const a=document.querySelector('.now-row .art'); if(!hd||!a) return null;"
     " const g=parseFloat(getComputedStyle(hd).columnGap)||0;"
     " return Math.round(hd.getBoundingClientRect().width"
     "   - a.getBoundingClientRect().width - g); })(),"
     " lib:lib, xq:xq, libul:ul,"
     " libTracks:document.querySelectorAll('.tracks li[data-i]').length,"
     " gapBottom:lib ? Math.round(sbb.bottom - lib['b']) : null,"
     " xqStretch:(lib && xq) ? Math.round(xq['b'] - lib['b']) : null,"
     " ulSlack:ul ? (document.querySelector('.tracks').scrollHeight"
     "                - document.querySelector('.tracks').clientHeight) : null});"
     " } catch (e) { return JSON.stringify({err:String((e && e.message) || e)}); } })()")


async def main():
    log = open(os.path.join(ROOT, "runs", "_probe_geom.log"), "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", str(PORT), "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    for _ in range(60):
        try:
            urllib.request.urlopen(BASE + "/music.json", timeout=2).read(10); break
        except Exception: time.sleep(0.5)
    try:
        async with Session(CDP) as S:
            await S.cmd("Page.navigate", {"url": BASE + "/media.html"})
            await asyncio.sleep(3.0)
            g = await S.js(Q)   # S.js 自己就把 JSON 串解开了
            # ⚠️ `S.js` 在页面那边抛异常时返回的是 None（拿不到 `value`），**不是报错**
            #    —— 表现得像"什么都没量到"。这里必须自己说清楚：
            #    上次它就这么静默地变成了下一行 `g["innerH"]` 上的一句
            #    `'NoneType' object is not subscriptable`，读起来像是探针写错了，
            #    其实是页面根本没导航过去。
            if g is None:
                print("!! 量不到东西 —— 表达式在页面里抛了，或者压根没导航到 media.html。")
                print("   location = %r" % (await S.js("location.pathname"),))
                print("   title    = %r" % (await S.js("document.title"),))
                print("   有 .sub-body 吗 = %r" % (await S.js("!!document.querySelector('.sub-body')"),))
                for lvl, m in S.errs[-8:]:
                    print("   控制台 [%s] %s" % (lvl, m))
                return
            if g.get("err"):
                print("!! 页面里的表达式抛了：%s" % g["err"])
                return
            print("=== /media.html ===")
            print("  视口高 %d   dpr %s   outer/inner %s" % (g["innerH"], g["dpr"], g["zoom"]))
            for k in ("topbar", "mainsub", "sub", "ptitle", "talk"):
                print("  %-8s %s" % (k, g[k]))
            print("  sub-body 内容 %d / 可视 %d   ==> 需要 %d / 有 %d（差 %d）"
                  % (g["subScroll"], g["subClient"], g["subScroll"], g["subClient"],
                     g["subScroll"] - g["subClient"]))
            for k in ("hero", "lib", "xq", "libul", "head", "art", "meta", "tname"):
                if g[k]:
                    print("  %-8s top=%-5d h=%-5d bottom=%-5d  left=%-5d w=%-5d"
                          % (k, g[k]["t"], g[k]["h"], g[k]["b"], g[k]["l"], g[k]["w"]))
            print("  列表：%d 行曲目" % g["libTracks"])
            print("  ★ 我的音乐卡底 -> sub-body 可视底 还空 %d px（判据要 <= 12）"
                  % g["gapBottom"])
            print("  ★ 右边小瑞卡底 - 我的音乐卡底 = %d px（判据要 |差| <= 2）"
                  % g["xqStretch"])
            print("  列表内部富余 %s px（负数=列表自己在滚，这是对的）" % g["ulSlack"])
            print("  ★ 歌名可用 %s px（判据要 >= 320；这是 .head − 封面 − 缝，"
                  "跟当前放的是哪首无关）" % g["metaAvail"])
    finally:
        srv.terminate(); time.sleep(0.8)
        if srv.poll() is None: srv.kill()
        log.close()

asyncio.run(main())
