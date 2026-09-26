"""心率那一路在**三个页面**上真的跟着值走吗 —— 浏览器里验，不看代码。

    D:\\Anaconda3\\envs\\dms\\python.exe ui\\server.py --port 8790 --source demo
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_check_hr_ui.py [port] [cdp]

## 为什么单开一个脚本

2026-09-26 接上心率这一路（板子 D 帧 → `ui/serial_hr.py` → `st.hr` → 三个页面）。
`_check_hr_live.py` 只证到 **WebSocket 那一帧里有 `hr`**，证不到屏幕上那一格 ——
中间还隔着三段每段都能单独坏掉的东西：

  · 页面的 `render(s)` 有没有真去读 `s.hr`（漏写 = 那一格永远是初值「未接入」）；
  · `s.hr == null` 这个判断有没有写对（写成 `s.hr || '未接入'`，读数是 **0** 时就
    会把真值吞掉；写成 `s.hr.toFixed(0)` 不加守卫，`null.toFixed` 当场 TypeError）；
  · **失效态和有效态长得一不一样**。这是本脚本最值钱的一条 —— `monitor.html`
    那一格原来没有任何 `.mt .v.na` 规则，`class="v na"` 是个**空操作**：
    「未接入」会按**数值的**字号字重渲染（1.3rem / 600），看起来就是一个数。
    屏幕上分不出"没接入"和"接入了一个叫未接入的数"，这一路等于白接。

## 2026-09-26 晚扩的三块

1. **`未按压` 那一档**（用户当场报的：手指拿开之后页面写「未接入」，可板子明明
   接着）。判据从 `s.hr_finger` 来（`serial_hr.snapshot()` 的 `finger` 键）。
   三档必须**互不相同**：`off`→「未按压」、`on`→「--」、`unknown`→「未接入」。
   🔴 还有一条更隐蔽的：**`on` 那一档只给横杠、不给词**。`finger=on` 同时覆盖
   "在攒心跳"和"没搏动"（`snapshot` 里那条 `no_pulse`）两种情况，写任何一个词
   都会在另一种情况下变成**编的**。
2. **交流幅度 / PI 两格**（四页各两个）。判据同 `#rHr` 那条纪律：有数写数字 +
   拔掉 `.na`，没数写 `--` + 挂上 `.na`，**0 也是数**。
   ★ 2026-09-26 深夜：第一格**原本是 HRV-RMSSD**（`#rRr`/`#mRr`/`#mvRr`/`#dRr`），
   换成交流幅度（`hr_ac`，`#rAc`/`#mAc`/`#mvAc`/`#dAc`）。原因同 `ui/state.py`
   那条注释：RMSSD 实测 0.0% 的帧有数，屏幕上永远一根横杠，用户要"换个一直有的"。
   ⚠️ **判据不变**：注入一个值 → 页面必须写出那个数并摘掉 `.na`。
3. **PI 提示那一行**（只有首页有）。文案由服务端给，空串时那一行必须**收起来**
   （`hidden`）——它占的 13.4px 在 `.status` 卡里是算过的（卡是固定高度 +
   `overflow:hidden`，多出来的部分会被**静默**裁掉，见 `_hr_ui_probe.py`）。

## 红线：那句中文不许出现在前端源码里

本脚本**最后**会直接读盘，把 `ui/web/` 下所有 `.html/.js/.css` 过一遍，
断言「请调整手指按压位置」出现 **0 次**。这是"界面只留标签和数字"那条红线的
审计口径 —— 句子必须由服务端给（`serial_hr.PI_HINT`），
一旦有人图省事把它写进 HTML，这条就会红。
⚠️ 这个检查**必须放在浏览器那段之前**：下面 `put_st()` 会把这句中文注入进
页面自己收到的那一帧，注入之后再读 DOM 就必然"有"了。

⚠️ 本脚本证明不了"真人手指按上去板子出数"—— 那件事在 `_check_hr_live.py`
   的 A 段（真读串口）。这里的世界里 `hr` 全是注入的，demo 源下它是 None。
"""

import asyncio
import glob
import importlib.util
import io
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.argv = [sys.argv[0], sys.argv[1] if len(sys.argv) > 1 else "8790"]

_spec = importlib.util.spec_from_file_location(
    "_check_pages", os.path.join(_HERE, "_check_pages.py"))
cp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cp)
ck = cp.ck

HINT = "请调整手指按压位置"

# 页面真收到的那一帧 state 存哪儿。装 setter 而**不是**替换 WebSocket 构造函数：
# 换构造函数会让 `instanceof WebSocket` 变假、静态常量对不上，页面自己那套
# 重连逻辑有可能因此走岔 —— 那就成了"测试把被测对象弄坏了"。
HOOK = r"""
(function () {
  var d = Object.getOwnPropertyDescriptor(WebSocket.prototype, 'onmessage');
  window.__STATE = null;
  Object.defineProperty(WebSocket.prototype, 'onmessage', {
    configurable: true, enumerable: true,
    get: function () { return d.get.call(this); },
    set: function (fn) {
      d.set.call(this, function (ev) {
        try {
          var m = JSON.parse(ev.data);
          if (m && m.type === 'state') { window.__STATE = m.data; }
        } catch (e) {}
        return fn.apply(this, arguments);
      });
    },
  });
})();
"""


class S(cp.Session):
    PRELOAD = [HOOK]


# (页, 心率格的 id, "这个值不可用"用的那个类, [(衍生格 id, state 字段, 小数位, 单位, 样例值, 期望文本)], PI 提示格的 id)
#
# ⚠️ 样例值三页**必须逐字一样、期望文本也必须逐字一样** —— 这个工程把"两边文案
#    不一致"直接当 bug 抓，而这三个渲染器本来就是三份手写的代码
#    （`app.js` / `detail.html` / `monitor.html` 各一份，故意不共用，
#    因为它们要用的 DOM 结构和失效样式都不一样）。共用的是 `XQ.hrText`（心率那格）
#    和这两个数字的格式串。
PAGES = [
    ("index.html", "rHr", "muted",
     [("rAc", "hr_ac", 0, "", 498.3, "498", "na"),
      ("rPi", "hr_pi", 2, "%", 0.14, "0.14 %", "na")],
     "rPiHint"),
    ("detail.html", "mHr", "na",
     [("mAc", "hr_ac", 0, "", 498.3, "498", "na"),
      ("mPi", "hr_pi", 2, "%", 0.14, "0.14 %", "na")],
     None),
    ("monitor.html", "mvHr", "na",
     [("mvAc", "hr_ac", 0, "", 498.3, "498", "na"),
      ("mvPi", "hr_pi", 2, "%", 0.14, "0.14 %", "na")],
     None),
]
# ⚠️ 每个衍生格的最后那一位是**它自己**的失效样式类名，不是"这一页的"。
#   首页 `#rHr` 用 `.muted`（`style.css:1236`，它原来就有那一档），而 `.ntiles`
#   里新加的两格用 `.na` —— 同一页上两个类名。这是**既有事实**（那两格是照
#   `detail.html` / `monitor.html` 的写法加的），不是这次改出来的不一致；
#   真正要保证的是**观感一致**，而那一条由「两种状态长得不一样」逐格盯着。


def _lit(v):
    """Python 值 → JS 字面量。字符串走 repr（Python 3 的 repr 不转义非 ASCII，
    中文会原样出来 —— 所以那句提示文案能直接进 JS 源码）。"""
    if v is None:
        return "null"
    if isinstance(v, str):
        return repr(v)
    return str(v)


def probe_js(eid):
    """读那一格现在的：文字 / class / 生效后的字号字重颜色 / 占不占高度。"""
    return ("(function(){var e=document.getElementById(%r);"
            "if(!e)return null;var g=getComputedStyle(e);"
            "var r=e.getBoundingClientRect();"
            "return JSON.stringify({t:e.textContent.trim(),c:e.className,"
            "fs:g.fontSize,fw:g.fontWeight,col:g.color,hid:!!e.hidden,"
            "disp:g.display,h:+r.height.toFixed(1)});})()" % eid)


def put_st(pairs, eid, call_render=True):
    """改 **页面收到的那一帧** 的若干字段，再调页面自己的 render()。

    `pairs` 是 [(字段名, 值), ...]。这样才验得到"服务端真推的那一份"在屏幕上
    怎么落 —— 自己另编一个 state 对象只能证明"我编的对象能渲染"。
    """
    body = ";".join("st.%s=%s" % (k, _lit(v)) for k, v in pairs)
    return ("(function(){var st=window.__STATE;if(!st)return null;"
            "%s;%svar e=document.getElementById(%r);"
            "if(!e)return null;var g=getComputedStyle(e);"
            "var r=e.getBoundingClientRect();"
            "return JSON.stringify({t:e.textContent.trim(),c:e.className,"
            "fs:g.fontSize,fw:g.fontWeight,col:g.color,hid:!!e.hidden,"
            "disp:g.display,h:+r.height.toFixed(1)});})()"
            % (body, "render(st);" if call_render else "", eid))


def look(d):
    return (d["fs"], d["fw"], d["col"])


def text_scan():
    """红线：那句提示文案不许出现在前端的 .html/.js/.css 里。"""
    root = os.path.join(os.path.dirname(_HERE), "ui", "web")
    files = sorted(glob.glob(os.path.join(root, "*.html"))
                   + glob.glob(os.path.join(root, "*.js"))
                   + glob.glob(os.path.join(root, "*.css")))
    hits = []
    for p in files:
        n = io.open(p, encoding="utf-8", errors="replace").read().count(HINT)
        if n:
            hits.append("%s x%d" % (os.path.basename(p), n))
    return files, hits


async def main():
    worst = 0

    # ---- 0. 先扫盘（必须在任何注入之前，见文件头）----
    files, hits = text_scan()
    print("=== 红线：提示文案只能由服务端给 ===")
    print("  扫了 %d 个文件（ui/web/*.html|js|css）" % len(files))
    worst |= ck("前端源码里 0 次出现「%s」" % HINT, not hits,
                "命中：" + "、".join(hits) if hits else "")

    async with S(9413) as B:
        for page, eid, na, extra, hint_id in PAGES:
            print("\n=== %s  #%s ===" % (page, eid))
            B.errs.clear()
            await B.goto("/" + page, wait=2.0)

            title = await B.js("document.title")
            if not title:
                worst |= ck("页面打得开", False, "title 空，多半 404")
                continue

            n = await B.js("window.__STATE ? Object.keys(window.__STATE).length : -1")
            worst |= ck("收到了页面自己那帧 state", isinstance(n, int) and n > 20,
                        "字段数 %s" % n)
            if not isinstance(n, int) or n <= 0:
                continue
            # ★ 服务端真会发这些键吗 —— **这一条必须在任何注入之前**。
            #   起因是一个注入式测试**结构上抓不到**的真 bug（2026-09-26 夜）：
            #   `XQ.hrText` 读 `s.hr_finger`，而 `serial_hr.apply_to_state` 从来
            #   没往 State 上写过它、`ui/state.py` 里也没这个字段。下面那些用例
            #   注入的是**测试自己编的** `hr_finger`，于是"注入 → 渲染 → 断言"
            #   整条链自洽地绿，而真机上手指拿开那一格照样写「未接入」——
            #   正是用户报的那一条，一个字没变。
            #   注入式测试验的是"给我这么一个对象你渲染得对吗"，**从不验
            #   "这个对象你会真收到吗"**。这条就是对后半句的补丁。
            #   🔴 以后在前端新增一处读 `s.xxx`，就把它加进下面这个表。
            for k in ("hr", "hr_ac", "hr_rmssd", "hr_pi", "hr_pi_hint",
                      "hr_finger"):
                has = await B.js(
                    "Object.prototype.hasOwnProperty.call(window.__STATE,%r)?1:0"
                    % k)
                worst |= ck("那一帧里**真的有** %s 这个键（前端在读它）" % k,
                            has == 1,
                            "服务端没发 ⟹ 前端读到 undefined ⟹ 下面注入式的"
                            "用例会绿，而真机上这一格永远是错的那一档")

            # ⚠️ **不能假设"demo 源 ⟹ hr 是 None"**。`hr` 来自串口读线程，和
            #   "这一帧是谁供的"完全无关（`Hub.tick` 里 `apply_to_state` 在源之外
            #   贴着那一帧）。板子在跑、手指按着的时候，**demo 源的页面上照样是
            #   真数** —— 本脚本第一版就是这么假设的，于是三条判据一起红，而
            #   产品是对的。那个错法和 `dms-heart-rate` 里记的「`_check_hr_ui.py`
            #   那条红是判据前提写错，不是产品坏了」是同一类。
            #   所以这一格**先注入"没数"再看**，不靠"现在应该是空的"。
            a = await B.js(put_st([("hr", None), ("hr_finger", "unknown")], eid))
            if not a:
                worst |= ck("那一格在页面上存在", False, "getElementById 拿到 null")
                continue
            worst |= ck("hr=None 且 finger=unknown 显示「未接入」", a["t"] == "未接入",
                        "实际「%s」" % a["t"])
            worst |= ck("按失效样式渲染", na in a["c"].split(), "class=%s" % a["c"])

            # ① 有数：72.4 必须变成「72 BPM」，而且**去掉**失效样式
            b = await B.js(put_st([("hr", 72.4)], eid))
            worst |= ck("hr=72.4 显示「72 BPM」", b["t"] == "72 BPM",
                        "实际「%s」" % b["t"])
            worst |= ck("有数时不再挂失效样式", na not in b["c"].split(),
                        "class=%s" % b["c"])
            worst |= ck("两种状态**长得不一样**", look(a) != look(b),
                        "未接入 %s/%s/%s  vs  72BPM %s/%s/%s"
                        % (a["fs"], a["fw"], a["col"], b["fs"], b["fw"], b["col"]))

            # ② 读数 0 不许被当成"没值"（`s.hr || '未接入'` 那种写法会在这儿红）
            z = await B.js(put_st([("hr", 0)], eid))
            worst |= ck("hr=0 仍然是个数（0 不是「没值」）", z["t"] == "0 BPM",
                        "实际「%s」" % z["t"])

            # ③ 再变回 None：类要回来（toggle 写反了只会在这一步露出来）
            # ⚠️ 同时把 `hr_finger` 归回 `unknown` —— 不然它在真机上还留着
            #    `'on'`（手指在传感器上），那一格会正确地显示 `--` 而不是
            #    「未接入」，于是这条判据假红。这一条也是上面那个"别假设"的同类。
            c = await B.js(put_st([("hr", None), ("hr_finger", "unknown")], eid))
            worst |= ck("hr=None 变回「未接入」", c["t"] == "未接入",
                        "实际「%s」" % c["t"])
            worst |= ck("失效样式跟着回来", na in c["c"].split(), "class=%s" % c["c"])

            # ---- ④ 三档区分（2026-09-26 晚加）----
            # 顺序是刻意的：先 `unknown`、再 `off`、最后 `on`，每一步都跟上一档
            # **对比**。只验"off 显示未按压"的话，一个把三档全写成「未按压」的
            # 实现照样会过。
            u = await B.js(put_st([("hr", None), ("hr_finger", "unknown")], eid))
            worst |= ck("finger=unknown -> 「未接入」", u["t"] == "未接入",
                        "实际「%s」" % u["t"])
            o = await B.js(put_st([("hr", None), ("hr_finger", "off")], eid))
            worst |= ck("finger=off -> 「未按压」（手指没在传感器上）",
                        o["t"] == "未按压", "实际「%s」" % o["t"])
            worst |= ck("「未按压」和「未接入」不是同一句话",
                        o["t"] != u["t"],
                        "unknown 给「%s」/ off 给「%s」" % (u["t"], o["t"]))
            worst |= ck("「未按压」仍按失效样式渲染", na in o["c"].split(),
                        "class=%s" % o["c"])
            p_on = await B.js(put_st([("hr", None), ("hr_finger", "on")], eid))
            worst |= ck("finger=on（手指在、但没数字）-> 横杠",
                        p_on["t"] in ("--", "—"),
                        "实际「%s」—— ⚠️ 这一档**不许给词**：finger=on 同时覆盖"
                        "「在攒心跳」和「没搏动」，写任何一个词都会在另一种情况下变假"
                        % p_on["t"])
            worst |= ck("三档三个样子",
                        len({u["t"], o["t"], p_on["t"]}) == 3,
                        "%s / %s / %s" % (u["t"], o["t"], p_on["t"]))

            # ---- ⑤ 衍生两格（交流幅度 / PI）----
            for xid, field, dec, unit, val, want, xna in extra:
                print("  -- #%s（%s，失效类名 .%s） --" % (xid, field, xna))
                m0 = await B.js(put_st([(field, None)], xid))
                if not m0:
                    worst |= ck("#%s 在页面上存在" % xid, False, "拿到 null")
                    continue
                worst |= ck("没值时显示 `--`", m0["t"] == "--",
                            "实际「%s」" % m0["t"])
                worst |= ck("没值挂失效样式", xna in m0["c"].split(),
                            "class=%s" % m0["c"])
                m1 = await B.js(put_st([(field, val)], xid))
                worst |= ck("%s=%s 显示「%s」" % (field, val, want),
                            m1["t"] == want, "实际「%s」" % m1["t"])
                worst |= ck("有值时拔掉失效样式", xna not in m1["c"].split(),
                            "class=%s" % m1["c"])
                worst |= ck("有值和没值**长得不一样**", look(m0) != look(m1),
                            "`--` %s/%s/%s  vs  有值 %s/%s/%s"
                            % (m0["fs"], m0["fw"], m0["col"],
                               m1["fs"], m1["fw"], m1["col"]))
                # 0 也是数：`v || '--'` 那种写法会在这儿红
                m2 = await B.js(put_st([(field, 0)], xid))
                # ⚠️ **单位可以没有**（`hr_ac` 就是无量纲的，见 `ui/web/app.js`）。
                #    原来这行无条件拼 `" " + unit`，于是"没单位"那格会要求页面
                #    写出一个**带尾空格**的 `"0 "` —— 而页面写的是 `"0"`，
                #    这条就假红（2026-09-26 深夜实测：三页各红一条，只有它红）。
                zt = "%.*f" % (dec, 0.0) + ((" " + unit) if unit else "")
                worst |= ck("%s=0 仍然是个数（0 不是「没值」）" % field,
                            m2["t"] == zt, "实际「%s」（要「%s」）" % (m2["t"], zt))
                m3 = await B.js(put_st([(field, None)], xid))
                worst |= ck("变回 None 还是 `--`", m3["t"] == "--",
                            "实际「%s」" % m3["t"])
                worst |= ck("失效样式跟着回来", xna in m3["c"].split(),
                            "class=%s" % m3["c"])

            # ---- ⑥ PI 提示那一行（只有首页有；别的页面是 None）----
            if hint_id:
                print("  -- #%s（PI 提示） --" % hint_id)
                h0 = await B.js(probe_js(hint_id))
                if not h0:
                    worst |= ck("#%s 在页面上存在" % hint_id, False, "拿到 null")
                else:
                    worst |= ck("文案为空时那一行**收起来**（不占高度）",
                                h0["hid"] and h0["disp"] == "none" and h0["h"] == 0.0,
                                "hidden=%s disp=%s h=%s"
                                % (h0["hid"], h0["disp"], h0["h"]))
                    h1 = await B.js(put_st([("hr_pi_hint", HINT)], hint_id))
                    worst |= ck("有文案时显示，且文字与服务端给的逐字相同",
                                h1["t"] == HINT and not h1["hid"] and h1["h"] > 0,
                                "实际「%s」hidden=%s h=%s"
                                % (h1["t"], h1["hid"], h1["h"]))
                    # 那一行撑出来之后卡片会不会被裁 —— 卡是固定高度 +
                    # `overflow:hidden`，多出来的会被**静默**吃掉。
                    ov = await B.js(
                        "(function(){var c=document.querySelector('.main.dash .status');"
                        "return c?c.scrollHeight-c.clientHeight:-1;})()")
                    worst |= ck("提示撑出来之后卡片没有被裁", ov == 0,
                                "scrollH-clientH = %s（>0 就是裁了）" % ov)
                    h2 = await B.js(put_st([("hr_pi_hint", "")], hint_id))
                    worst |= ck("文案变回空串时又收起来",
                                h2["hid"] and h2["h"] == 0.0,
                                "hidden=%s h=%s" % (h2["hid"], h2["h"]))

            await asyncio.sleep(0.6)
            for lvl, m in B.errs:
                print("  !!  [%s] %s" % (lvl, m))
            worst |= ck("注入这些拍之后控制台仍然零报错", not B.errs)

    print()
    print("退出码 0 = 全过" if worst == 0 else "有失败项，见上面 !! 行")
    return worst


if __name__ == "__main__":
    sys.stdout.flush()
    code = asyncio.run(main())
    sys.stdout.flush()
    sys.exit(code)
