# -*- coding: utf-8 -*-
"""「放音乐」那几颗圆钮**点得动吗** —— 用 `elementFromPoint` 量，不看截图也不看 CSS。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_music_click.py

为什么要单独量这一条：`detail.html` 的「舒缓音乐」圆钮**中心点**点下去命中的不是它自己。
2026-09-25 量到的真凶**不是 z-index，是几何**：`.mon-xq .xq-head`（`pages.css:1855`）
是 `flex:1 1 auto; min-height:0`，卡片被侧栏挤矮时它跟着缩到 **65.7 px**，
而里面那个 `.mon-xq .mascot` 是 **8.2rem（≈119 px）`flex:0 0 auto`**（**不许缩**）——
小瑞整个人**往下溢出**，正好压在 `.qk-round` 第一行上，而第一颗就是 music。
⚠️ 所以「给 `.ring` 加 `pointer-events:none`」那种修法是错的：光环后面还有
`#mascotImg`（矩形更大）和 `div.mascot` 自己，**透明 div 在这个项目里确实吃点击**
（`runs/_check_clickable.txt:16` 有实例）。只关光环，报出来的名字会从 `div.ring`
换成 `img#mascotImg` 再换成 `div.mascot`，**按钮照样是死的**。

⚠️ 余量只有几 px，**不许靠读 CSS 推** —— 这个脚本就是唯一说得清的那个权威。
⚠️ 挤压是**纵向**的（全站只有一条 `@media`，在 1180px，管封面），所以
   `SIZES` 里量的是**窗口高度**：答辩那台机器/投影的分辨率不是这台机器的。
   🔴 其中 `None` 那一档（**真实窗口，不 override**）**最不能省**：这台机器有显示缩放，
      `--window-size` 是设备像素，真实 CSS 视口只有 **1638x843** —— 用户报的那颗
      只有在这一档下才量得出来，换下面几个 override 尺寸全是绿的。

⛔ **点不着分两种，别混**（脚本自己分开数）：
   ① **被本卡的小瑞压住** —— 本探针的判据，修法是 `pages.css` 的 `.mon-xq .mascot`
      （`height:100%` + `max-height:8.2rem` + `aspect-ratio:1`，见那一段注释）。
   ② **整块被裁掉**（报出来的"最上面那个"是 `DIV.main.sub` 这种**祖先**）——
      元素在 DOM 里、盒子也量得出来，但**根本没画**：裁刀是
      `body{height:100vh; overflow:hidden}`（`style.css:346`），
      右栏内容比栏高时**不滚动、不报错**，直接从屏幕外消失。
      2026-09-25 在 `1280x600` 上量到过（`side sh/ch=465/424`）；
      **A/B 换掉那条 `.mascot` 规则，数字逐字一样** —— 所以它是**既有**问题，
      和本条无关，脚本只报不判（不让它把这一条变成永远红的）。

⚠️ 本脚本**只读**：不点、不派事件、不动任何状态。它回答的是"这个点上最上面是谁"。
"""
import asyncio
import os
import subprocess
import sys
import time
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

import _check_pages as CP                              # noqa: E402

# ⚠️ `_check_pages` 里**没有** ROOT/PY 这两个名字（它只管起 Edge 和判据），
#    别从它那儿取 —— 取了就是 `AttributeError`，而且是在起服务之前炸，
#    看着像脚本写错了。自己算一份。
ROOT = os.path.dirname(_HERE)
PY = r"D:\Anaconda3\envs\dms\python.exe"

PORT = "8806"
CDP = 9473

# 要量的窗口尺寸。高才是挤压的那个方向，见文件头。
# ⚠️ `None` = **不动**，就用 Edge 按 `--window-size=1672,940` 开出来的那个真实内尺寸。
#    这一格**不能省**：这台机器有显示缩放，`--window-size` 是**设备像素**，
#    于是真实 CSS 视口比 1672x940 小一圈 —— 而用户报的那个"点不着"正好
#    是在这个尺寸下才出现的（换到下面几个 override 尺寸反而量不出来）。
#    只用 override 量 = 把真正出问题的那一档漏掉。
SIZES = [None, (1672, 940), (1440, 900), (1280, 720), (1280, 600), (1920, 1080)]

# 可选：`... _probe_music_click.py 1280x600 real` 只量这几档（写字面量 `real` 就是那一档）。
# 不给参数就按 SIZES 全量跑。要排查某一档时用它，别改 SIZES —— 改了容易忘了改回来。
if len(sys.argv) > 1:
    SIZES = [None if a.lower() == "real" else
             tuple(int(v) for v in a.lower().split("x")) for a in sys.argv[1:]]

# 每张页面里"小瑞 + 一行控件"那套结构（**同一份 markup 抄了两处，改一处就要两处都量**）：
#   驾驶监测页 `.mon-xq` + `.qk-round`（四颗圆钮，第一颗就是用户报的那颗「舒缓音乐」）
#   多媒体页   `.mp-xq` + `.xq-say`（输入框 + 发送键，同样的 `flex:1 1 auto; min-height:0`
#              外壳 + `flex:0 0 auto` 的小瑞 —— 今天没坏，隐患一模一样）
DECKS = [
    ("/detail.html", ".mon-xq", ".mon-side", ".qk-round", "驾驶监测页"),
    ("/media.html", ".mp-xq", None, ".mp-xq .xq-say", "多媒体页"),
]

JS_CLICK = r"""(function(sel, cardSel){
  const el = document.querySelector(sel);
  if (!el) return {missing: true};
  const b = el.getBoundingClientRect();
  const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
  const top = document.elementFromPoint(cx, cy);
  const name = (e) => e ? (e.tagName + (e.id ? '#' + e.id : '')
                          + (e.className && typeof e.className === 'string'
                             ? '.' + e.className.trim().split(/\s+/).join('.') : ''))
                        : '(null)';
  return {
    missing: false,
    vis: !!b.width && !!b.height,
    box: {t: Math.round(b.top), l: Math.round(b.left),
          w: Math.round(b.width), h: Math.round(b.height)},
    top: name(top),
    /* 命中它自己 / 它的后代 = 点得动；命中的是别人 = 点不着 */
    ok: !!(top && (top === el || el.contains(top))),
    /* ★ 点不着**分两种**，修法完全不同，所以要在同一份输出里分开数：
       · `byMascot` —— 中心点上压的是**这张卡自己的小瑞**（`<card> .mascot` 里），
         也就是本探针盯着的那条：小瑞比 `.xq-head` 高、往下溢到圆钮上。
       · 其余（例如报出来是 `DIV.main.sub` 这种**祖先**）—— 说明这一块**整个被裁了**：
         元素还在 DOM 里、盒子也量得出来，但根本没画。本仓库的裁刀是
         `body{height:100vh; overflow:hidden}`（`style.css:346`）：
         右栏内容比栏高时**不滚动、不报错**，直接从屏幕外消失。
         ⚠️ 那是**既有**问题，和"小瑞压住按钮"不是一件事（2026-09-25 在
            1280x600 上 A/B 量过：换不换那条 `.mon-xq .mascot` 规则，
            数字逐字一样）。所以它**不算这一条的判据**，但也不许瞒着不报。 */
    byMascot: !!(top && top.closest && top.closest(cardSel + ' .mascot')),
    hitIntro: !!(top && top.closest && top.closest('.intro'))
  };
})"""

# 把整条挤压链一次量出来：谁给了多少高度、谁溢出了多少、溢到谁头上。
JS_GEOM = r"""(function(cardSel, sideSel, rowSel){
  const R = (el) => { if (!el) return null; const b = el.getBoundingClientRect();
    return {t: Math.round(b.top), l: Math.round(b.left), w: Math.round(b.width),
            h: Math.round(b.height), b: Math.round(b.bottom)}; };
  const card = document.querySelector(cardSel);
  const side = sideSel ? document.querySelector(sideSel) : null;
  const head = document.querySelector(cardSel + ' .xq-head');
  const mas  = document.querySelector(cardSel + ' .mascot');
  const img  = document.querySelector(cardSel + ' .mascot-img');
  const row  = rowSel ? document.querySelector(rowSel) : null;
  const S = (el) => el ? {sh: el.scrollHeight, ch: el.clientHeight} : null;
  return JSON.stringify({
    vw: innerWidth, vh: innerHeight,
    rootFs: parseFloat(getComputedStyle(document.documentElement).fontSize),
    side: R(side), card: R(card), head: R(head), mascot: R(mas), img: R(img),
    row: R(row), rowFirst: row ? R(row.querySelector('button, a')) : null,
    cardScroll: S(card), sideScroll: S(side),
    /* 溢出量：小瑞的底边比它爸（`.xq-head`）的底边低多少 —— 正数就是"压到下面那行" */
    spill: (head && mas) ? Math.round(mas.getBoundingClientRect().bottom
                                      - head.getBoundingClientRect().bottom) : null,
    docSh: document.documentElement.scrollHeight,
  });
})"""


async def measure(S, size, path, cardSel, sideSel, rowSel, label, err0=0):
    if size is None:
        await S.cmd("Emulation.clearDeviceMetricsOverride")
    else:
        await S.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": size[0], "height": size[1], "deviceScaleFactor": 1,
                     "mobile": False})
    await S.goto(path, 2.0)
    # 封面那层不透明盖子会盖住整页 —— 先收掉它，不然量的是它
    await S.js("(function(){const b=document.getElementById('intro');"
               "if(b){b.classList.remove('on');b.classList.add('gone');}"
               "const o=document.getElementById('introOpen');"
               "if(o)o.hidden=true;return 'ok';})()")
    await asyncio.sleep(0.3)

    print("%s @ %s   %s"
          % (label, "%dx%d" % size if size else "真实窗口（不 override）", path))
    # ⚠️ 拼 JS 的实参**必须用 `j()`,不能直接用 `repr()`**：`repr(None)` 给出来的是
    #    Python 那个 `None`,在 JS 里是个**未定义的标识符** → 整个表达式 ReferenceError
    #    → `S.js` 回 `None` → 打印成"找不到 `.mp-xq`,结构改名了"。
    #    一句话就把探针自己的语法错误说成了产品的问题(这次真踩了)。
    j = lambda v: "null" if v is None else repr(v)      # noqa: E731
    g = await S.js("(%s)(%s,%s,%s)" % (JS_GEOM, j(cardSel), j(sideSel),
                                       j(rowSel)))
    if not (g or {}).get("card"):
        print("   !! 找不到 %r —— 结构改名了，先修这个探针" % cardSel)
        print()
        return
    for k in ("side", "card", "head", "mascot", "img", "row", "rowFirst"):
        if g.get(k):
            r = g[k]
            print("   %-9s t=%-5s h=%-5s b=%-5s   (l=%s w=%s)"
                  % (k, r["t"], r["h"], r["b"], r["l"], r["w"]))
    print("   真实视口 vw=%s vh=%s（`--window-size` 是设备像素，缩放后比它小）"
          % (g["vw"], g["vh"]))
    print("   rootFs=%s  card sh/ch=%s/%s  side sh/ch=%s/%s  docSh=%s"
          % (g["rootFs"], g["cardScroll"]["sh"], g["cardScroll"]["ch"],
             (g["sideScroll"] or {}).get("sh"), (g["sideScroll"] or {}).get("ch"),
             g["docSh"]))
    spill = g.get("spill")
    if spill is not None:
        print("   小瑞溢出 `.xq-head` 底边: %s px %s"
              % (spill, "🔴 压到下面的圆钮行上了" if spill > 0 else "OK 没溢出"))

    # 每一颗圆钮 + 小瑞自己（用户拍板：按钮要能点，小瑞在别处也要能点）
    # ⚠️ 枚举**不能**用 `> *:nth-child(n)`：`.qk-round` 的头一个孩子是
    #    `#quickBtns{display:contents}`（**没有盒子**，0x0），于是 nth-child(1)
    #    量的是 `elementFromPoint(0,0)` —— 报出来是顶栏，看着像"第一颗点不着"，
    #    其实是探针自己数错了。按标签选（`button` / `a`）才和眼睛看到的一列对上。
    sels = []
    if rowSel:
        for tag in ("button", "a"):
            n = await S.js("document.querySelectorAll(%s).length"
                           % repr(rowSel + " " + tag))
            sels += ["%s %s:nth-of-type(%d)" % (rowSel, tag, i + 1)
                     for i in range(n or 0)]
    sels.append(cardSel + " .mascot")
    # 圆钮是 `renderQuick()` 在 `onHello` 里填的 —— 一个都没填出来时，
    # 上面那些选择器会直接 `!! 找不到`，那种"空"要先说清楚，别当成布局问题。
    print("   #quickBtns 里渲染出 %s 颗（XQ.QUICK 有 %s 项）"
          % (await S.js("(document.getElementById('quickBtns')||{children:[]})"
                        ".children.length"),
             await S.js("(window.XQ && XQ.QUICK) ? XQ.QUICK.length : 'XQ 没加载'")))
    bad = 0        # 小瑞压住的（本探针的判据）
    cut = 0        # 整块被裁掉的（既有问题，只报不判）
    for sel in sels:
        r = await S.js("(%s)(%s,%s)" % (JS_CLICK, repr(sel), repr(cardSel)))
        if r.get("missing"):
            print("   !! 找不到 %r" % sel)
            bad += 1
            continue
        if r["ok"]:
            verdict = "点得动"
        elif r.get("byMascot"):
            verdict = "🔴 点不着 —— 被本卡的小瑞压住"
        else:
            verdict = "⛔ 整块被裁了（既有问题，非小瑞）"
        print("   %-30s %-34s 中心点上是 %-34s %s"
              % (sel.split('> ')[-1], str(r["box"]), r["top"], verdict))
        if not r["ok"]:
            if r.get("byMascot"):
                bad += 1
            else:
                cut += 1
    if not bad and not cut:
        print("   → 全部可点")
    for lvl, msg in S.errs[err0:]:
        print("   ⚠️ 控制台 %s: %s" % (lvl, msg))
    print()
    return bad, cut


async def main():
    log = open(os.path.join(ROOT, "runs", "_probe_music_srv.log"), "w",
               encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", PORT,
                            "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        for _ in range(40):
            try:
                with urllib.request.urlopen("http://127.0.0.1:%s/music.json"
                                            % PORT, timeout=3):
                    break
            except Exception:                          # noqa: BLE001
                time.sleep(0.5)
        CP.PORT = PORT
        CP.BASE = "http://127.0.0.1:%s" % PORT

        worst = 0
        cut_all = 0
        async with CP.Session(CDP) as S:
            for path, cardSel, sideSel, rowSel, label in DECKS:
                for size in SIZES:
                    b, c = await measure(S, size, path, cardSel, sideSel,
                                         rowSel, label, len(S.errs))
                    worst += b
                    cut_all += c
        if worst:
            print("🔴 %d 处被小瑞压住（这就是那条 bug，没修干净）" % worst)
        else:
            print("✅ 小瑞没压住任何一颗（本探针的判据全绿）")
        if cut_all:
            print("⛔ 另有 %d 处是**整块被裁**（`body{overflow:hidden}`，右栏装不下）"
                  "—— 既有问题，不是这一条的东西；见本文件头" % cut_all)
        return 1 if worst else 0
    finally:
        try:
            srv.terminate()
            time.sleep(0.8)
            if srv.poll() is None:
                srv.kill()
        finally:
            log.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
