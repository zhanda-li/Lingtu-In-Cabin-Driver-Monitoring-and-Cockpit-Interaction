# -*- coding: utf-8 -*-
"""Request D 验收：**全站每一个"有小瑞"的位置都能点着换形象**。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_check_posedecks.py 8790

用户原话：「左下那个应该小瑞图片能变化的太少了 我不是有40多张图片吗 把那些出现
小瑞的地方都变成可以变化的 并且形象要多一些 太少了」。

这一份查的是**机制**，不是"文件在不在盘上"：每个槽都要真的点下去、真的换一张、
换到的是**它自己那一套**尺寸（`s`/`l`/`h` 三套不能串），而且弹完那一下之后
`data-act` 必须被摘掉（不摘掉这一格就永远不浮动了）。

------------------------------------------------------------------ 怎么找"点哪儿"
`XQ.poseDeck(im, host, opts)` 会给 host 挂上 `title='点一下换个形象'` 和
`cursor:pointer`，所以脚本**不写死宿主选择器**，而是从 img 往上找到第一个带这个
title 的祖先 —— 这正好就是在验"宿主挂对了没有"：宿主找不到 = 这一格根本没接上
deck；宿主挂到了别处（比如挂到 img 自己、而调用点本意是外层）也一眼看得出来。

`title` 是**指纹**这件事有个前提：`poseDeck` 那条 `host.title = opts.title ||
'点一下换个形象'`。要是哪天把默认标题改了，下面 `DEck_TITLE` 跟着改一处就行。

------------------------------------------------------------------ 为什么初始就不是 p01
两种槽的"起点"不一样，别当成 bug：

  · **纯造型位**（左栏、封面、`.dash-mascot`、settings 那两格、`deck:'h'` 那些）
    —— `src` 在 HTML 或 `mascotSlot` 里写死成形象库的某一张（多数是 `p01`，
    `.dash-mascot` 是 `p02`，因为它要对上原来那张 `xiaorui_welcome.png` 的姿势）。
  · **bind 槽**（`#mascotImg` / `#sideArt` / `#tipImg`）—— 起点是**待机动图**
    `xiaorui_live.webp`，不是形象库里的任何一张。但它挂的 deck 仍然从 `p01`
    起步（`base: XQ.isPose(base) ? base : 'p01'`），所以**第一次点击照样落到 p02**。
    ⚠️ 还有一层：`bind` 的 `onReady` 里会 `playOne(slot,'happy',2000)` 打个招呼，
    所以刚加载那 2 秒 src 是 `xiaorui_happy.png`。下面 `SETTLE` 就是等这个。
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.stdout.reconfigure(encoding="utf-8")
from _check_pages import Session, ck                      # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
CDP = 9521
DECK_TITLE = "点一下换个形象"
SETTLE = 2.9          # 等 bind 槽开场那个 happy（2000ms）演完回底图
HOLD = 620            # 和 live.js 的 posdedeck 默认 hold 对上

# 页 -> [(说明, img 选择器, 尺寸, 起始下标, 期望的初始 src 名字)]
# 起始下标 = `XQ.POSES.indexOf(base)`，决定**第一次点击**落到哪个名字：
#   下标 0（base p01）-> 第一次是 p02；下标 1（base p02）-> 第一次是 p03。
P_S = "s", "l", "h"
# 封面那层全屏片头的关闭开关（见 cover.html 末尾那段注释）。只用在 cover 上。
INTRO_OFF = "?intro=0"
SLOTS = {
    "cover.html": [
        ("封面立绘位", "#coverMascotImg", "l", 0, "p01"),
    ],
    "index.html": [
        ("左栏那一格", "#railXrImg", "s", 0, "p01"),
        ("首页主视觉立绘", ".dash-mascot", "l", 1, "p02"),
        # ⚠️ 首页**没有** `#talkAvaImg`：第五次改版把对话栏整个搬到驾驶监测页了，
        #    `app.js` 那边是 `if (talkAvaHost)` 守着调的（曾经就是这行空引用差点
        #    打断 onHello）。别往这张表里加回去 —— 加了就是查一个不该存在的槽。
        ("首页主形象(bind)", "#mascotImg", "s", 0, "bind"),
    ],
    "detail.html": [
        ("左栏那一格", "#railXrImg", "s", 0, "p01"),
        ("驾驶监测主形象(bind)", "#mascotImg", "s", 0, "bind"),
        ("驾驶监测对话头像", "#talkAvaImg", "h", 0, "p01"),
    ],
    "media.html": [
        ("左栏那一格", "#railXrImg", "s", 0, "p01"),
        ("多媒体主形象(bind)", "#mascotImg", "s", 0, "bind"),
        ("多媒体对话头像", "#talkAvaImg", "h", 0, "p01"),
    ],
    "monitor.html": [
        ("左栏那一格", "#railXrImg", "s", 0, "p01"),
        ("对话头像", "#talkAvaImg", "h", 0, "p01"),
    ],
    "settings.html": [
        ("左栏那一格", "#railXrImg", "s", 0, "p01"),
        ("立绘那格(bind)", "#sideArt", "s", 0, "bind"),
        ("第 1 栏圆头像", ".xq-ava img", "h", 0, "p01"),
        ("退出横幅方图", ".warm .art img", "h", 0, "p01"),
    ],
    "chat.html": [
        ("左栏那一格", "#railXrImg", "s", 0, "p01"),
        ("气泡头像(bind)", "#tipImg", "s", 0, "bind"),
    ],
    "phone.html": [
        ("左栏那一格", "#railXrImg", "s", 0, "p01"),
        ("手机 hero 0", "#phHero0Img", "h", 0, "p01"),
        ("手机 hero 1", "#phHero1Img", "h", 0, "p01"),
        ("手机 hero 2", "#phHero2Img", "h", 0, "p01"),
        ("手机 hero 3", "#phHero3Img", "h", 0, "p01"),
    ],
    "voice.html": [("左栏那一格", "#railXrImg", "s", 0, "p01")],
    "flow.html": [("左栏那一格", "#railXrImg", "s", 0, "p01")],
    "link.html": [("左栏那一格", "#railXrImg", "s", 0, "p01")],
}

# 页面上装一次的小工具。`info()` 把 src 拆成（尺寸, 名字），`hostOf()` 就是上面
# 说的那把"指纹尺"；`addEventListener` 那半段是数**这一格换了没有**用的。
HELPERS = """
window.__pd = {
  hostOf(sel){
    var e = document.querySelector(sel);
    if (!e) return null;
    for (var n = e; n && n !== document.documentElement; n = n.parentElement){
      if (n.title === %s) return n;
    }
    return null;
  },
  /* src -> {size, name}。两种 src 形状都要认：
       assets/xq/<size>/<pNN>.webp   —— 形象库
       assets/xiaorui_<act>.webp|png —— 待机动图 / 10 个动作 */
  split(s){
    var m = /assets\\/xq\\/([slh])\\/(p\\d+)\\.webp/.exec(s || '');
    if (m) return {size: m[1], name: m[2]};
    var a = /assets\\/xiaorui_(\\w+)\\.(?:webp|png)/.exec(s || '');
    if (a) return {size: '-', name: '@' + a[1]};
    return {size: '?', name: '?'};
  },
  info(sel){
    var e = document.querySelector(sel);
    if (!e) return null;
    var h = this.hostOf(sel);
    var raw = e.getAttribute('src') || '';
    var p = this.split(raw);
    return JSON.stringify({
      raw: raw, size: p.size, name: p.name,
      host: h ? (h.tagName + (h.id ? '#' + h.id : '') +
                 (h.className ? '.' + String(h.className).split(' ')[0] : '')) : null,
      cursor: h ? getComputedStyle(h).cursor : null,
      onHost: h ? h.contains(e) : null,
      act: e.getAttribute('data-act') || null
    });
  },
  click(sel){
    var h = this.hostOf(sel);
    if (!h) return false;
    h.click();
    return true;
  },
  /* 等 src 离开 `from`。等不到返回 '__timeout__' —— 这一条很要紧：换图是
     先 new Image() 探到 onload 才赋 src 的（见 poseDeck 的 ①），探不到就
     什么都不做，所以"点了没动"在这里表现出来就是超时，而不是换成了破图。 */
  waitChange(sel, from, ms){
    return new Promise(function(res){
      var e = document.querySelector(sel);
      if (!e) return res('__gone__');
      var t0 = Date.now();
      (function tick(){
        if ((e.getAttribute('src') || '') !== from) return res(e.getAttribute('src'));
        if (Date.now() - t0 > ms) return res('__timeout__');
        setTimeout(tick, 20);
      })();
    });
  },
  sleep(ms){ return new Promise(function(r){ setTimeout(r, ms); }); }
};
'ready'
""" % json.dumps(DECK_TITLE)


async def ajs(S, expr, ms=6000):
    """会 await 页面里 promise 的求值。`Session.js` 不带 awaitPromise，
    而"等这一张加载完"只能在页面里等，所以这里直接走 cmd。"""
    r = await S.cmd("Runtime.evaluate",
                    {"expression": expr, "returnByValue": True, "awaitPromise": True})
    d = r.get("result", {})
    return d.get("value")


def pos_name(i):
    return "p%02d" % (i + 1)


async def main():
    worst = 0
    async with Session(CDP) as S:
        await S.cmd("Page.enable")
        await S.goto("/index.html", 1.0)
        await S.js(HELPERS)

        for page, slots in SLOTS.items():
            print("\n=== %s · %d 个小瑞位 ===" % (page, len(slots)))
            # ⚠️ 封面 2026-09-25 起有一层 `z-index:9999` 的**全屏不透明品牌
            #    片头**，它会把这一段的 `.click()` **静默吃掉**（点在盖子上，
            #    页面什么都不发生、控制台也不报）。别的页没有片头，照旧。
            await S.goto("/" + page + (INTRO_OFF if page == "cover.html" else ""),
                         SETTLE)
            if await S.js("typeof window.__pd") != "object":
                await S.js(HELPERS)

            for label, sel, size, base_i, want0 in slots:
                info0 = await S.js("window.__pd.info(%s)" % json.dumps(sel))
                if not info0:
                    worst |= ck("%s · DOM 里找得到" % label, False, sel + " 不存在")
                    continue

                # ---- 1. deck 真的接上了（宿主 = 从 img 往上第一个带指纹的祖先）
                worst |= ck("%s · 接了 deck" % label,
                            info0["host"] is not None,
                            "宿主 %s cursor=%s" % (info0["host"], info0["cursor"]))
                if info0["host"] is None:
                    continue
                worst |= ck("%s · 宿主是真的能点的" % label,
                            info0["cursor"] == "pointer", info0["cursor"])

                # ---- 2. 起点。（bind 槽跟着动作层走，纯造型位是形象库里写死的那张）
                # ⚠️ bind 槽**不能**要求它就是待机动图：那一格同时挂着动作层，
                #    页面一加载 `react()` 就会按真实档位演一个动作，取样那一刻它
                #    可能正停在 `xiaorui_wow.png` 上（index/detail 上实测就是）。
                #    要验的是"起点**不是**形象库里的 pNN"—— 那才说明 deck 没抢底图。
                if want0 == "bind":
                    ok0 = info0["name"].startswith("@")
                    note0 = "%s/%s（要 @ 开头：待机动图或 10 个动作之一）" % (
                        info0["size"], info0["name"])
                else:
                    ok0 = (info0["name"] == want0 and info0["size"] == size)
                    note0 = "%s/%s（要 %s）" % (info0["size"], info0["name"],
                                               size + "/" + want0)
                worst |= ck("%s · 起点没被 deck 抢走" % label, ok0, note0)

                # ---- 3. 点一下：换到**这一套尺寸**的下一张
                if not await S.js("window.__pd.click(%s)" % json.dumps(sel)):
                    worst |= ck("%s · 点得动" % label, False, "宿主没接上 click")
                    continue
                raw_now = await ajs(
                    S, "window.__pd.waitChange(%s, %s, 5000)"
                    % (json.dumps(sel), json.dumps(info0["raw"])))
                info1 = await S.js("window.__pd.info(%s)" % json.dumps(sel))
                # ⚠️ `data-act` 必须**等 src 换完再读**。`click()` 只是启动
                #    `new Image()`，`apply()`（挂 data-act 的地方）在 onload 里 ——
                #    点完立刻读会读到一个随机结果：图快就 'swap'、图慢就 None。
                #    第一版就是栽在这儿（同一轮里 phone hero0 是 None、hero1~3
                #    是 'swap'，看着像"有的槽坏了"，其实只是抢跑）。
                act_now = info1["act"] if info1 else None
                want1 = pos_name(base_i + 1)
                worst |= ck("%s · 第 1 下真的换了张" % label,
                            info1 and info1["raw"] != info0["raw"] and raw_now != "__timeout__",
                            "%s -> %s" % (info0["name"], info1["name"] if info1 else "?"))
                worst |= ck("%s · 换到的是 %s 那套（不是别人的）" % (label, size),
                            info1 and info1["size"] == size and info1["name"] == want1,
                            "%s/%s（要 %s/%s）" % (info1["size"] if info1 else "?",
                                                  info1["name"] if info1 else "?",
                                                  size, want1))
                worst |= ck("%s · 换完那一瞬间挂着 data-act" % label,
                            act_now == "swap", "data-act=%r" % act_now)

                # ---- 4. 弹完要摘干净（不摘这一格就永远不浮动了）
                await ajs(S, "window.__pd.sleep(%d)" % (HOLD + 400))
                act_late = await S.js(
                    "document.querySelector(%s).getAttribute('data-act')"
                    % json.dumps(sel))
                worst |= ck("%s · %dms 后 data-act 摘掉了" % (label, HOLD + 400),
                            not act_late, "data-act=%r" % act_late)

                # ---- 5. 连着点：按 POSES 顺序走，不是随机、不是原地
                names, prev = [], info1["raw"]
                for k in range(2, 5):
                    await S.js("window.__pd.click(%s)" % json.dumps(sel))
                    await ajs(S, "window.__pd.waitChange(%s, %s, 5000)"
                              % (json.dumps(sel), json.dumps(prev)))
                    ii = await S.js("window.__pd.info(%s)" % json.dumps(sel))
                    names.append(ii["name"])
                    prev = ii["raw"]
                want_seq = [pos_name(base_i + k) for k in (2, 3, 4)]
                worst |= ck("%s · 连点按顺序走" % label, names == want_seq,
                            "%s（要 %s）" % (names, want_seq))

        # ---------------------------------------------------------------- 回绕
        print("\n=== 左栏那一格 · 43 张走一圈回不回得来 ===")
        await S.goto("/index.html", SETTLE)
        await S.js(HELPERS)
        sel = "#railXrImg"
        first = await S.js("window.__pd.info(%s)" % json.dumps(sel))
        prev, seen, sizes = first["raw"], [], []
        for _ in range(43):
            await S.js("window.__pd.click(%s)" % json.dumps(sel))
            await ajs(S, "window.__pd.waitChange(%s, %s, 5000)"
                      % (json.dumps(sel), json.dumps(prev)))
            ii = await S.js("window.__pd.info(%s)" % json.dumps(sel))
            seen.append(ii["name"])
            sizes.append(ii["size"])
            prev = ii["raw"]
        worst |= ck("43 下走完 43 个不重样", len(set(seen)) == 43,
                    "去重后 %d 个" % len(set(seen)))
        worst |= ck("43 下之后回到起点（p01）", seen[-1] == first["name"],
                    "%s -> %s" % (first["name"], seen[-1]))
        worst |= ck("43 张全部是 s 那套（没串到别人的目录）",
                    set(sizes) == {"s"} and all(s == "s" for s in sizes),
                    "出现过的尺寸 %s" % sorted(set(sizes)))
        worst |= ck("名字就是 p02..p43 再回 p01（顺序走，不是随机）",
                    seen == [pos_name(i) for i in range(1, 43)] + [pos_name(0)],
                    "头三个 %s ... 尾三个 %s" % (seen[:3], seen[-3:]))

        # ---------------------------------------------------------------- 控制台
        print("\n=== 控制台 ===")
        errs = [e for e in S.errs if "favicon" not in e]
        worst |= ck("全程零报错零警告", not errs, (errs[:3] if errs else ""))

    print("\n" + "=" * 68)
    print("**全绿**" if not worst else "**上面有 %d 条红**" % worst)
    return worst


sys.exit(asyncio.run(main()))
