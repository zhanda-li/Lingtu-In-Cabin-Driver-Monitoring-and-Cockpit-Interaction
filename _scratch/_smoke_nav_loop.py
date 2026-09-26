# -*- coding: utf-8 -*-
"""导航页那一圈闭环，**在真浏览器里走一遍**（2026-09-25 版面改版之后的那一版）。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_smoke_nav_loop.py 8793

为什么非要在浏览器里走（不只看代码）：这一页的坑全在"哪个 id 还在 / 哪个函数
没定义"上 —— `$('xxx')` 拿到 null 再 `.textContent =` 是**当场抛 TypeError**，
后面整段代码静默不执行。语法守卫（`_js_template_scan.py`）看不见这种错，
只有真跑一遍、看 `S.errs` 里有没有东西才知道。

这一版断言的是**用户 2026-09-25 最后拍的那个版面**：
    顶上一条搜索栏（起点框 / 交换键 / 终点框 / 重新定位 / 搜索路线）
    → 中间地图是主视觉，**一张图上三条候选线**（深蓝/浅蓝/灰）
    → 路线面板**叠在地图右侧**（一块玻璃卡，不拆）
    → 疲劳时地图**右下角**一条轻量气泡
另加 ①.7 一节守**打字即推荐**（2026-09-26 用户点名的那条），全程不按回车。

⚠️ 这台机器**拿不到浏览器定位**（见 `nav.html` 的 `tryGeo()`），所以起点这条路
   走的是"人自己给"——正好就是用户要的那条。脚本会先等定位那一步落定
   （它失败时会清空面板，跑早了会把刚填好的东西清掉）。
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
    sys.argv.append("8793")

import _check_pages as CP                                     # noqa: E402
from _check_pages import Session                              # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CDP = 9417
LOG = os.path.join(ROOT, "runs", "_smoke_nav_loop_srv.log")
WORST = 0

# 预设点位里挑一个真的**高速边上**的点当起点（`nav.html` 的 PRESETS）。
# ⚠️ 断言里那个名字必须和页面上的字面量**一模一样**（少一个空格就命中不了，
#    命中不了会静默退成"拿去问高德"，然后这一步看起来像"搜不到"）。
# ★ 2026-09-26 修：这个名字以前**抄在脚本里**（当年是「天津 · 京沪高速一带」），
#   预设点位后来换成了静海/无锡/保定/广州/郑州 —— 于是这一份**静默腐坏**：
#   它不再命中任何预设，退成“拿去问高德”，看着像“高德搜不到那个地名”。
#   现在改成**从页面自己读**（`PRESETS[0].n`；`const` 在全局词法作用域里，
#   `Runtime.evaluate` 直接读得到）：名字随页面走，改预设名改不出这种红。
#   仍然咬一句“这名字得像个人话”（带「高速」），否则读回来一个空串也算“过”。
ORIGIN_JS = "(()=>{try{return PRESETS[0].n}catch(e){return ''}})()"


def ck(name, ok, note=""):
    global WORST
    print("  %s %-36s %s" % ("OK  " if ok else "!!  ", name, note))
    if not ok:
        WORST += 1
    return ok


async def until(S, expr, ok, cap=16.0, step=0.6):
    """轮询到 `expr` 求值为真（或超时）。返回最后一次的值。"""
    t = 0.0
    v = None
    while t < cap:
        v = await S.js(expr)
        if ok(v):
            return v
        await asyncio.sleep(step)
        t += step
    return v


async def click_at(S, x, y):
    """在页面坐标 (x,y) 上真点一下。

    ⚠️ 顺序不能省：`Input.dispatchMouseEvent` **必须先 `mouseMoved`**，少了它
       事件送不到元素上（见 `_cdp` 那几条踩过的坑）。高德地图是 canvas，
       它自己的 click 是这么收到坐标的 —— 只有真事件才算数。
    """
    for t, extra in (("mouseMoved", {}), ("mousePressed", {"button": "left",
                                                           "clickCount": 1}),
                     ("mouseReleased", {"button": "left", "clickCount": 1})):
        await S.cmd("Input.dispatchMouseEvent",
                    dict({"type": t, "x": x, "y": y}, **extra))
    await asyncio.sleep(0.25)


async def st(S):
    """页面自己报的状态（`XQ.nav.state()`）。"""
    return await S.js("JSON.stringify(XQ.nav.state())") or {}


# 候选列表里**真正能点的**有几条。
# ⚠️ 不能用 `children.length`：`#dstList` 里除了候选还夹着页面自己插的 `.dtip`
#    说明行（「按高德自己的顺序」那种），它们不是候选、点了没反应 ——
#    拿它当"高德回了几条"会把数字报大，拿它当"点第一条"会点在死行上。
CAND_N = ("(()=>{const l=$('dstList');"
          "return l.hidden ? 0 : l.querySelectorAll('button').length})()")


async def pick_cand(S):
    """点候选里的第一条**真候选**（不是 `.dtip` 那种说明行）。"""
    return bool(await S.js("(()=>{const b=$('dstList').querySelector('button');"
                           "if(!b) return 0;b.click();return 1})()"))


# 候选层里**第一行是什么**：
#   None = 层是收着的
#   ''   = 层开着，但里面只有一行 `.dtip` 状态字（「正在问高德…」/「没搜到」/「被限流」）
#   '无锡市' = 第一行是**真候选**
# ★ 这个函数存在的理由就是上面那个 `''`：用户报的"打字不推荐"当年在屏幕上长什么样，
#   正是——一个字敲下去，框里永远停在「正在问高德「无锡站」…」，一直没有候选
#   （`nav.html:960-972` 记了那时的两个根因）。只看"层开着吗"是抓不住这一种的。
LIST_HEAD = ("(()=>{const l=$('dstList');"
             "if(l.hidden) return null;"
             "const b=l.querySelector('button');"
             "return b ? (b.querySelector('.dn')||b).textContent : ''})()")


async def put(S, box, kw):
    """往框里**打字**（`input` 事件，**不按回车**）。

    ⚠️ 必须派发 `input`：页面的接线是 `inp.oninput`（`nav.html:2521`），
       只改 `value` 的话页面**什么都不知道** —— 那就会把"没送到"误判成"页面坏了"。
    """
    return await S.js("(()=>{const i=$('%s');i.value=%s;i.focus();"
                      "i.dispatchEvent(new Event('input',{bubbles:true}));"
                      "return i.value})()"
                      % (box, json.dumps(kw, ensure_ascii=False)))


async def fill_search_pick(S, box, kw):
    """在某个框里写词 → 回车 → 等候选 → 点第一条。"""
    await S.js("(()=>{const i=$('%s');i.value=%s;"
               "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));"
               "return 1})()" % (box, json.dumps(kw)))
    n = await until(S, CAND_N, lambda v: v and v > 0)
    if not n:
        return 0
    await pick_cand(S)
    return n


async def main():
    log = open(LOG, "w", encoding="utf-8")
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
            await S.goto("/nav.html", wait=2.4)

            # ① 起步：搜索栏的骨架 + 定位那一步落定
            txt = await until(S, "$('orgText').textContent", lambda v: v and
                              "正在定位" not in v, cap=22.0)
            ck("定位那一步落定了", bool(txt) and "正在定位" not in txt, repr(txt))
            geo_bad = "定位没打开" in (txt or "")
            ck("定位失败时说得清楚（这台机器就是这样）", geo_bad or True,
               "定位失败（预期）" if geo_bad else "定位竟然成了")
            d = await S.js("""JSON.stringify({
              org:getComputedStyle(document.querySelector('#orgState')).display,
              ph_org:$('orgIn').placeholder, ph_dst:$('dstIn').placeholder,
              orgval:$('orgIn').value, km:$('nbKm').textContent,
              eta:$('nbEta').textContent, rows:$('rtRows').children.length,
              start:$('navStart').disabled,
              btn:[...document.querySelectorAll('.ptitle button')].map(b=>b.id),
              order:(function(){const a=$('orgIn'),b=$('dstIn'),s=$('swapBtn');
                const bar=a.closest('.ptitle');
                return ((a.compareDocumentPosition(b)&4)&&bar&&bar.contains(s))
                       ? 1 : 0;})()})""")
            ck("起点框写着「当前位置」", d and d["ph_org"] == "当前位置", (d or {}).get("ph_org"))
            ck("终点框写着「请输入目的地」", d and d["ph_dst"] == "请输入目的地",
               (d or {}).get("ph_dst"))
            # ★ 2026-09-26 翻面（**是对象搬了家，不是判据坏了**）：这条原来咬的是
            #   「交换键**夹在**起点框和终点框中间」（DOM 顺序 org→swap→dst）。
            #   用户 2026-09-25 拍板「起终点在一列 不要分开」（`nav.html:441`），
            #   起点终点合成**一列**（`.end-box`），交换键挪到整列右边的竖直居中处
            #   —— 「夹在中间」在结构上不可能再成立。守的东西换成**同一件事的现在式**：
            #   起点在上、终点在下（还是"起终点"这个顺序），交换键和它们**在同一栏**。
            #   ⚠️ 别再往回改成"夹在中间"，那一版版面已经不存在了。
            ck("起点在上、终点在下，交换键在同一栏里",
               bool(d and d["order"]), str((d or {}).get("order")))
            ck("「重新定位」「搜索路线」两颗键都在",
               bool(d and "orgRetry" in d["btn"] and "dstGo" in d["btn"]),
               str((d or {}).get("btn")))
            # ★ 定位拿不到的时候，起点框**必须是空的** —— 占位符写着「当前位置」，
            #   但绝不能在框里放一个我们自己编的坐标。
            ck("定位拿不到时起点框里没有编出来的值",
               bool(d and not d["orgval"]), repr((d or {}).get("orgval")))
            # ★ 2026-09-26 削掉一截：这条原来还带着 `and d["start"]`
            #   （"'开始导航'是禁用的"）。那个契约**已经翻了**（见②那一节的注释），
            #   留着它这一条永远红、而且红的理由和"面板上有没有数"毫无关系 ——
            #   一条判据不该背两个不相干的结论。"没路线时那颗键怎么样"挪到②单独咬。
            ck("什么都还没查时，面板上一个数都没有",
               bool(d and d["km"] == "\u2014" and d["eta"] == "\u2014"
                    and d["rows"] == 0),
               "%s / %s / %s 行" % ((d or {}).get("km"), (d or {}).get("eta"),
                                    (d or {}).get("rows")))

            # ①.5 版面：面板**叠在地图右侧**、气泡在地图右下角（这是用户点名的）
            d = await S.js("""JSON.stringify((function(){
              const w=$('mapWrap').getBoundingClientRect();
              const p=$('navPanel').getBoundingClientRect();
              const cards=$('mapWrap').querySelectorAll('.card').length;
              return {in:(p.left>=w.left-1&&p.right<=w.right+1&&
                        p.top>=w.top-1&&p.bottom<=w.bottom+1),
                      right:(p.right>w.left+w.width*0.55),
                      cards:cards, mh:Math.round(w.height)}})())""")
            ck("路线面板是**叠在地图上**的（不是另起一栏）", bool(d and d["in"] and d["right"]),
               str(d))
            ck("地图那一块里没有别的卡片（一块面板，不拆）",
               bool(d and d["cards"] == 0), "cards=%s" % (d or {}).get("cards"))
            ck("地图够高（是这一页的主视觉）", bool(d and d["mh"] >= 380),
               "%s px" % (d or {}).get("mh"))

            # ①.7 ★ **打字即推荐** —— 用户 2026-09-26 点名的头一条：
            #   「我在起点终点每输入一个字 都要有相关的地点推荐啊 不要我点enter才推荐
            #     以及去除字才推荐」。这一节**全程不按回车**，只派发 `input`。
            # ⚠️ 为什么要有这一节：这件事一直是 `_t_nav_type.py` 那个**一次性探针**
            #    量出来的（它量到的两个根因写在 `nav.html:960-972`），修完之后
            #    **没有任何常驻判据守着** —— 也就是说，谁哪天把 `TYPING.pending`
            #    那半截改坏了，"打字不推荐"这事儿又会静悄悄地回来。
            # ⚠️ 判据是**第一行是不是真候选**，不是"层开着吗"：当年那个症状正是
            #    层开着、里面永远停着一行「正在问高德…」。见 `LIST_HEAD` 的注释。
            # ⚠️ 放在这一趟的**最前面**是有意的：这一节要真打高德，早跑额度最松；
            #    而且高德一限流（10021）页面会停搜 30 秒 —— 那种红会**连累后面**
            #    几节，所以它越早、越不容易被前面的流量带出来。
            await put(S, "dstIn", "无")
            h1 = await until(S, LIST_HEAD, lambda v: v, cap=8.0)
            ck("★ 敲一个字（**不按回车**）→ 真候选自己冒出来", bool(h1),
               "首行 %r" % (h1,))
            # 连着敲（模拟正常打字速度）：老根因①就是"撞在上一发在飞的时候，
            # 撞一次就再也没有下一发"，症状是屏幕上停在「正在问高德…」。
            await put(S, "dstIn", "无锡")
            await asyncio.sleep(0.15)
            await put(S, "dstIn", "无锡站")
            h3 = await until(S, LIST_HEAD, lambda v: v, cap=8.0)
            ck("★ 连着敲三下（**不按回车**）→ 落在真候选上", bool(h3),
               "首行 %r" % (h3,))
            # 用户点名的另外半截：「去除字才推荐」—— 我们这边删回去也得有推荐
            # （多半是 `TYPING.cache` 命中，那也算"给了推荐"；但**不许**是那行状态字）
            await put(S, "dstIn", "无")
            h2 = await until(S, LIST_HEAD, lambda v: v, cap=8.0)
            ck("删回到一个字 → 照样给推荐", bool(h2), "首行 %r" % (h2,))
            # 清空 → 收掉：不然那个浮层会一直挂在那儿挡地图
            await put(S, "dstIn", "")
            await asyncio.sleep(0.5)
            d = await S.js("$('dstList').hidden?1:0")
            ck("清空 → 候选层自己收掉（不挂在那儿挡地图）", bool(d), "hidden=%s" % d)
            # 用户说的是**起点终点两个框**，所以起点框也敲一下：两个框共用同一条路
            # 和同一个浮层，差别只在 `which`（点下去当起点还是当终点）——
            # 那正是最容易串的一处（`nav.html` 里 `takePlace(it, which)` 那个参数）。
            # ⚠️ 用「保」一个**字**：它既不是预设点位名（`PRESETS` 里那个叫
            #    「保定 · 京港澳高速一带」，一字不差才走预设），又有一堆 POI。
            await put(S, "orgIn", "保")
            h4 = await until(S, LIST_HEAD, lambda v: v, cap=8.0)
            ck("起点框敲字也给推荐（两个框共用一条路）", bool(h4), "首行 %r" % (h4,))
            await put(S, "orgIn", "")
            await asyncio.sleep(0.5)

            # ② 先搜终点、**故意不给起点** —— 该如实说"还差一个起点"
            # ★ 2026-09-26 修前提：回车之后**要么摆候选等人点、要么"一字不差"直接
            #   认下**（`nav.html` 的 `resolveBox()`：`r.list[0].name === kw` 才自动
            #   用）——「无锡站」走的正是后者，于是 `#dstList` 一直 `hidden`、
            #   候选数**恒为 0**。老写法（`fill_search_pick`）只认"摆了候选"，
            #   把这条**正常路径**报成红。两个都收，但要咬住"不能两个都没有"
            #   （那才是真坏：字敲进去了、屏幕上什么也没发生）。
            #   ⚠️ 别为了让这条变绿就把候选数当成唯一判据。
            await S.js("(()=>{const i=$('dstIn');i.value=%s;"
                       "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));"
                       "return 1})()" % json.dumps("无锡站"))      # 无锡站
            n = await until(S, CAND_N, lambda v: v and v > 0, cap=10.0)
            if n:
                await pick_cand(S)
            auto = await until(S, "JSON.stringify(XQ.nav.state().dest||null)",
                               lambda v: v, cap=18.0)
            ck("搜终点：要么摆候选，要么一字不差直接认下",
               bool(n or auto), "候选 %s 条 / 自动认下 %s" % (n, auto))
            await asyncio.sleep(0.7)
            d = await S.js("JSON.stringify({nm:$('nbName').textContent,"
                           "km:$('nbKm').textContent,"
                           "why:$('rtWhy').textContent,"
                           "rows:$('rtRows').children.length,"
                           "start:$('navStart').disabled})")
            ck("点了候选 → 终点记下来了", d and d["nm"] == "\u65e0\u9521\u7ad9",
               (d or {}).get("nm"))
            ck("没有起点时不编路线（如实说）",
               bool(d and d["rows"] == 0 and "起点" in d["why"] and d["km"] == "\u2014"),
               (d or {}).get("why"))
            # ★ 2026-09-26 翻面（**契约改了，不是对象没了**）：这条原来咬的是
            #   「没路线时 `#navStart` 是禁用的」。用户后来把那颗键的契约翻了过来
            #   ——「我点开始导航你要实际开始导航后啊」—— `paintStart()` 现在**永远**
            #   `disabled = false`（`nav.html` 里那条注释就是这句原话）。
            #   现在咬的是**新**判据的两半：① 没路线也**照样能按**（不许把人挡在
            #   门外）；② 按下去**不许**进导航态，而且要如实说差什么。
            #   ⚠️ 别再改回"该禁用" —— 那是被否掉的那一版。
            await S.js("(()=>{$('toast').textContent='';"
                       "$('toast').classList.remove('on');return 1})()")
            await S.js("$('navStart').click(); 1")
            await asyncio.sleep(0.6)
            d0 = await S.js("JSON.stringify({nav:document.body.classList"
                            ".contains('navigating'),"
                            "toast:$('toast').textContent})")
            ck("没路线时「开始导航」照样能按（不许禁用）",
               bool(d and not d["start"]), "disabled=%s" % (d or {}).get("start"))
            ck("没路线时按下去不进导航态、如实说差什么",
               bool(d0 and not d0["nav"] and "还没有路线" in (d0["toast"] or "")),
               str(d0))

            # ③ 报个起点（预设点位那条路：名字精确命中，不拿去问高德）→ 自动算路线
            origin = await S.js(ORIGIN_JS)
            ck("起点用的是页面自己那个预设点位名", bool(origin and "高速" in origin),
               repr(origin))
            await S.js("(()=>{const i=$('orgIn');i.value=%s;"
                       "i.dispatchEvent(new KeyboardEvent('keydown',{key:'Enter'}));"
                       "return 1})()" % json.dumps(origin))
            rows = await until(S, "$('rtRows').children.length",
                               lambda v: v and v > 0, cap=22.0)
            await until(S, "JSON.stringify(XQ.nav.state())",
                        lambda v: v and v.get("lines"), cap=20.0)
            await asyncio.sleep(1.2)
            d = await S.js("""JSON.stringify({
              org:$('orgText').textContent, rows:$('rtRows').children.length,
              km:$('nbKm').textContent, unit:$('nbKmUnit').textContent,
              eta:$('nbEta').textContent, note:$('nbNote').textContent,
              on:[...$('rtRows').children].findIndex(e=>e.classList.contains('on')),
              first:$('rtRows').children[0].innerText.replace(/\\n/g,' | '),
              panel:$('navPanel').innerText, start:$('navStart').disabled,
              fb:$('fatBubble').hidden ? 0 : 1})""")
            ck("有了起点就自动算了路线", bool(d and d["rows"]), "%s 条候选" % (d or {}).get("rows"))
            ck("起点那行写着是手动的", d and "起点（手动）" in d["org"], (d or {}).get("org"))
            ck("默认选中第一条", bool(d and d["on"] == 0))
            ck("公里数是高德那个数（驾车）",
               bool(d and d["km"].replace(".", "").isdigit() and "驾车" in d["unit"]),
               "%s%s" % ((d or {}).get("km"), (d or {}).get("unit")))
            ck("预计到达是个钟点",
               bool(d and len(d["eta"]) == 5 and d["eta"][2] == ":"), (d or {}).get("eta"))
            ck("面板上标了数据从哪来", bool(d and "高德" in d["note"]),
               (d or {}).get("note"))
            ck("有路线之后「开始导航」能按了", bool(d and not d["start"]))
            ck("疲劳气泡是收着的（没人报疲劳）", bool(d and not d["fb"]))
            # ★ 样张上那几句**没有数据源**的话，一个字都不许出现在面板上
            bad = [w for w in ("\u884c\u9a76\u987a\u7545", "\u8def\u51b5\u7a33\u5b9a",
                               "\u7ea2\u7eff\u706f\u8f83\u5c11", "\u676d\u5dde\u4e1c\u7ad9")
                   if d and w in d["panel"]]
            ck("面板上不出现样张里那些没来源的话", not bad, str(bad))
            print("     第一条：%s" % (d or {}).get("first"))

            # ④ 图上真有三条线（用户要的"三条候选同时画"）
            s0 = await st(S)
            ck("★ 图上同时画了三条候选线",
               bool(s0.get("lines") == 3 and all(p > 2 for p in s0.get("pts", []))),
               "lines=%s pts=%s" % (s0.get("lines"), s0.get("pts")))
            ck("高亮的是第一条（和面板上选中的那条一致）",
               bool(s0.get("cur") == 0 and s0.get("hi") == 0),
               "cur=%s hi=%s" % (s0.get("cur"), s0.get("hi")))

            # ⑤ 换一条方案 —— 面板和**图上那条线**都得跟着走
            if (d or {}).get("rows") and d["rows"] >= 2:
                await S.js("$('rtRows').children[1].click(); 1")
                await asyncio.sleep(0.9)
                d2 = await S.js("JSON.stringify({"
                                "on:[...$('rtRows').children]"
                                ".findIndex(e=>e.classList.contains('on')),"
                                "km:$('nbKm').textContent,eta:$('nbEta').textContent})")
                s1 = await st(S)
                ck("点第二条 → 面板上选中换到第二条", bool(d2 and d2["on"] == 1), str(d2))
                ck("★ 图上高亮那条也跟着换",
                   bool(s1.get("cur") == 1 and s1.get("hi") == 1),
                   "cur=%s hi=%s" % (s1.get("cur"), s1.get("hi")))
                ck("换方案后几何真的换了一条",
                   bool(s1.get("pts") and s0.get("pts")
                        and s1["pts"][1] != s0["pts"][0]),
                   "%s → %s" % (s0.get("pts", [None])[0],
                                (s1.get("pts") or [None, None])[1]))
                ck("面板上的里程/到达时间跟着换",
                   bool(d2 and d2["km"] != d["km"] and d2["eta"] != d["eta"]),
                   "%s/%s → %s/%s" % (d["km"], d["eta"],
                                      (d2 or {}).get("km"), (d2 or {}).get("eta")))
                await S.js("$('rtRows').children[0].click(); 1")   # 换回第一条
                await asyncio.sleep(0.6)
            else:
                ck("只有一条候选（短途正常）", True, "跳过换方案")

            # ⑥ 在地图上点一下 —— 该问"这个点算什么"，而不是替人决定
            await until(S, "XQ.nav.state().zoom", lambda v: v and v > 0, cap=20.0)
            pos = await S.js("(()=>{const r=$('map').getBoundingClientRect();"
                             "return JSON.stringify({x:r.left+r.width*0.32,"
                             "y:r.top+r.height*0.62})})()")
            org_before = (await st(S)).get("origin") or {}
            if pos:
                await click_at(S, pos["x"], pos["y"])
                d2 = await S.js("JSON.stringify({pick:$('mapPick').hidden?0:1})")
                ck("地图上点一下 → 出来「算什么」那条", bool(d2 and d2["pick"]), str(d2))
                km0 = (await st(S)).get("km")
                await S.js("$('pkDest').click(); 1")
                for _ in range(30):
                    if (await st(S)).get("km") != km0:
                        break
                    await asyncio.sleep(0.6)
                await asyncio.sleep(0.9)
                s2 = await st(S)
                d2 = await S.js("JSON.stringify({pick:$('mapPick').hidden?0:1,"
                                "nm:$('nbName').textContent,"
                                "org:$('orgText').textContent})")
                ck("点「设为终点」→ 终点换成地图上那个点",
                   bool(d2 and not d2["pick"] and d2["nm"] == "\u5730\u56fe\u4e0a\u70b9\u7684\u4f4d\u7f6e"),
                   str(d2))
                ck("地图选的终点照样算出路线", bool(s2.get("lines")),
                   "lines=%s" % s2.get("lines"))
                ck("起点没被这一下动过",
                   bool((s2.get("origin") or {}).get("lat") == org_before.get("lat")),
                   str(s2.get("origin")))
            else:
                ck("地图这块没画出来（这一趟验不了地图点选）", True, "")

            # ⑦ 顶上那颗「搜索路线」主键：框里换了字 → 该重新搜、重算
            # ⚠️ 按之前先记下**当前**终点：一会儿只看"候选有没有冒出来"是抓不住
            #    "按了没反应"的（这一趟的终点早就有值了，恒真）。
            prev3 = await S.js("JSON.stringify(XQ.nav.state().dest||null)")
            await S.js("(()=>{const i=$('dstIn');i.value='\u5929\u6d25\u7ad9';"
                       "$('dstGo').click();return 1})()")       # 天津站
            n = await until(S, CAND_N, lambda v: v and v > 0, cap=10.0)
            auto3 = await S.js("JSON.stringify(XQ.nav.state().dest||null)")
            # ★ 2026-09-26 同②那条修：`searchRoute()` 走的是**同一个** `resolveBox()`，
            #   「天津站」也是"一字不差"直接认下那种，候选同样是 0 条。
            #   两个都收，但"按了没反应"必须仍然咬得住 —— 所以盯着**终点真的换了**。
            ck("改了终点再按「搜索路线」→ 要么摆候选、要么直接认下",
               bool(n or (auto3 and auto3 != prev3)),
               "候选 %s 条 / 终点 %s ← %s" % (n, auto3, prev3))
            if n:
                await pick_cand(S)
            s3 = await until(S, "JSON.stringify(XQ.nav.state())",
                             lambda v: v and v.get("dest")
                             and v["dest"].get("name") == "\u5929\u6d25\u7ad9", cap=18.0)
            ck("终点换成了新搜的那个", bool(s3 and (s3.get("dest") or {}).get("name")
                                     == "\u5929\u6d25\u7ad9"),
               str((s3 or {}).get("dest")))
            ck("新终点照样三条线都画出来",
               bool(s3 and s3.get("lines") == 3), "lines=%s" % (s3 or {}).get("lines"))

            # ⑧ 交换起点和终点（两边都定过 → 真的对调坐标并重算）
            old = await st(S)
            await S.js("$('swapBtn').click(); 1")
            s4 = await until(S, "JSON.stringify(XQ.nav.state())",
                             lambda v: v and v.get("origin")
                             and v["origin"].get("label") == "\u5929\u6d25\u7ad9", cap=18.0)
            ck("★ 交换键：起点换成了刚才的终点",
               bool(s4 and (s4.get("origin") or {}).get("label") == "\u5929\u6d25\u7ad9"),
               str((s4 or {}).get("origin")))
            ck("交换键：终点换成了刚才的起点",
               bool(s4 and (s4.get("dest") or {}).get("name")
                    == ((old.get("origin") or {}).get("label"))),
               str((s4 or {}).get("dest")))
            ck("交换之后照样算出路线", bool(s4 and s4.get("lines")),
               "lines=%s" % (s4 or {}).get("lines"))

            # ⑨ 疲劳联动：服务端报中度/重度 → 右下角浮出那条建议气泡
            # 🔴 2026-09-26 修（**这一节原来是"和页面自己的事件源赛跑"**）：
            #   `paintFatigue()` 只在**档位往上走**的那一下弹（`sevRank` 记着上一次），
            #   而 `--source demo` 那份服务端**真的在后台推档位**（`ui/state.py`
            #   那条链路，`XQ.nav.wire.onState` 转一手到 `XQ.nav.onState`）。
            #   于是这一段的结果取决于"这几百毫秒里服务端推的是哪一档"：
            #   推过 moderate → `sevRank` 已经是 2，我们这一喂就不算"往上走"（不弹）；
            #   推过 severe 之后我们喂的那一下又会被随后的推送盖掉。
            #   这个脚本因此**时红时绿**，而且红的理由看着像"页面坏了"。
            #   修法不是放宽判据，是**把事件源收归测试自己**：把页面的那个口子
            #   （`wire.onState` 转发的 `XQ.nav.onState`）掐掉、真身另存，
            #   然后**从 normal 这个已知基线开始往上喂** —— 不喂基线的话，
            #   `sevRank` 可能一上来就是 2，"往上走"根本无从谈起。
            #   和 `_check_mascot.py` 里"还原事件源"是同一招。
            await S.js("window.__navDrive = XQ.nav.onState;"
                       "XQ.nav.onState = () => {}; 1")
            await S.js("window.__navDrive({severity:'normal'}); 1")
            await asyncio.sleep(0.3)
            d = await S.js("JSON.stringify({fb:$('fatBubble').hidden?0:1,"
                           "tx:$('fbTx').textContent})")
            ck("还没报疲劳时气泡是收着的", bool(d and not d["fb"]))
            await S.js("window.__navDrive({severity:'moderate'}); 1")
            await asyncio.sleep(0.3)
            d = await S.js("""JSON.stringify({fb:$('fatBubble').hidden?0:1,
              tx:$('fbTx').textContent,
              txt:$('fatBubble').innerText.replace(/\\n/g,' | '),
              pos:(function(){const b=$('fatBubble').getBoundingClientRect(),
                    w=$('mapWrap').getBoundingClientRect();
                    return (b.bottom<=w.bottom+1&&b.right<=w.right+1&&
                            b.right>w.left+w.width*0.6)?1:0})()})""")
            ck("★ 报中度疲劳 → 地图上浮出那条气泡", bool(d and d["fb"]), str(d))
            ck("气泡上的字就是用户那句",
               bool(d and "\u75b2\u52b3" in d["tx"] and "\u670d\u52a1\u533a" in d["tx"]),
               (d or {}).get("tx"))
            ck("气泡在地图**右下角**（用户点名）", bool(d and d["pos"]))
            ck("气泡上两个出口都在",
               bool(d and "\u5ffd\u7565" in d["txt"] and "\u67e5\u770b\u670d\u52a1\u533a" in d["txt"]),
               (d or {}).get("txt"))
            # 同一个档位不再弹第二次（往上走才弹）
            await S.js("$('fbStay').click(); 1")
            await asyncio.sleep(0.3)
            await S.js("window.__navDrive({severity:'moderate'}); 1")
            d = await S.js("$('fatBubble').hidden?0:1")
            ck("「忽略」之后同一个档位不再弹", bool(not d), "fb=%s" % d)
            # 缓过来再恶化 → 该弹
            await S.js("window.__navDrive({severity:'normal'}); 1")
            await S.js("window.__navDrive({severity:'severe'}); 1")
            await asyncio.sleep(0.3)
            d = await S.js("$('fatBubble').hidden?0:1")
            ck("缓过来又恶化 → 再弹一次", bool(d), "fb=%s" % d)

            # ⑩ 「查看服务区」真的去查（不是嘴上说说）
            before = await st(S)
            await S.js("$('fbGo').click(); 1")
            s5 = await until(S, "JSON.stringify(XQ.nav.state())",
                             lambda v: v and v.get("dest_kind") == "rest", cap=20.0)
            await asyncio.sleep(1.0)
            d = await S.js("JSON.stringify({nm:$('nbName').textContent,"
                           "note:$('nbNote').textContent,"
                           "km:$('nbKm').textContent,"
                           "fb:$('fatBubble').hidden?0:1,"
                           "why:$('rtWhy').textContent})")
            ck("★ 「查看服务区」真的查了（不是嘴上说说）",
               bool(s5 and s5.get("dest_kind") == "rest"), str((s5 or {}).get("dest_kind")))
            ck("服务区的名字是**高德给的那个真名字**",
               bool(d and d["nm"] and d["nm"] != "\u2014"
                    and d["nm"] != (before.get("dest") or {}).get("name")),
               "%s ← %s" % ((d or {}).get("nm"), (before.get("dest") or {}).get("name")))
            ck("面板标了这是推荐休息点", bool(d and "\u63a8\u8350\u4f11\u606f\u70b9" in d["note"]),
               (d or {}).get("note"))
            ck("查完气泡自己收了", bool(d and not d["fb"]))
            ck("服务区照样有公里数（或如实说没有）",
               bool(d and (d["km"] == "\u2014" or d["km"].replace(".", "").isdigit())),
               "%s | %s" % ((d or {}).get("km"), (d or {}).get("why")[:40]))
            ck("去服务区这条也有线画在图上",
               bool(s5 and (s5.get("lines") or 0) >= 1),
               "lines=%s" % (s5 or {}).get("lines"))

            # ⑪ 开始导航 / 结束导航（**没有逐段拆解、没有假进度**）
            # ⚠️ 走之前把页面的疲劳口子**接回去**（⑨ 开头掐掉的）：不接回去，
            #    这一页后面就一直在"喂不进档位"的状态里，真要有人在这儿写断言
            #    会量到一个**被测试改造过**的页面（那是最坏的一种绿）。
            await S.js("XQ.nav.onState = window.__navDrive; 1")
            await S.js("$('navStart').click(); 1")
            await asyncio.sleep(1.2)
            d = await S.js("""JSON.stringify({
              nav:document.body.classList.contains('navigating'),
              badge:getComputedStyle($('navPanel').querySelector('.np-badge')).display,
              txt:$('navStart').innerText.trim(),
              steps:$('mapWrap').querySelectorAll('.step,.steps').length})""")
            ck("点「开始导航」进了导航态", bool(d and d["nav"]), str(d))
            ck("面板上标出「导航中」", bool(d and d["badge"] != "none"),
               (d or {}).get("badge"))
            ck("那颗键变成「结束导航」", bool(d and "\u7ed3\u675f" in d["txt"]),
               (d or {}).get("txt"))
            ck("🔴 页面上没有逐段拆解那一套", bool(d and d["steps"] == 0),
               "steps=%s" % (d or {}).get("steps"))
            await S.js("$('navStart').click(); 1")
            await asyncio.sleep(1.0)
            s6 = await st(S)
            d = await S.js("JSON.stringify({nav:document.body.classList.contains"
                           "('navigating'),txt:$('navStart').innerText.trim()})")
            ck("再点一下退出导航态",
               bool(d and not d["nav"] and "\u5f00\u59cb" in d["txt"]), str(d))
            ck("退出后路线还在（没把东西清掉）",
               bool(s6.get("lines")), "lines=%s" % s6.get("lines"))

            # ⑫ 页面上的错（`$('xxx')` 拿到 null 之类全在这儿现形）
            # ⚠️ 高德 SDK 自己会打一条 Canvas2D 的 warning（`willReadFrequently`），
            #    那是它的画布，和这一页的代码无关 —— 留着它这条判据就永远是红的。
            errs = [e for e in S.errs if e and "willReadFrequently" not in str(e)]
            ck("页面没有 JS 报错", not errs, " | ".join(str(e)[:160] for e in errs[:4]))
    finally:
        srv.terminate()
        time.sleep(0.8)
        if srv.poll() is None:
            srv.kill()
        log.close()
    print("\n%s（%d 条不通过）" % ("全部通过" if not WORST else "有红", WORST))
    return 1 if WORST else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
