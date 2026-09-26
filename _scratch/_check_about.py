# -*- coding: utf-8 -*-
"""帮助 & 关于（`ui/web/about.html`）+ 首页那一格入口 —— 真的渲染出来了吗。

用户这次要的是两件事，各验各的：
  A  介绍页本身：六节内容都在、`**重点**` 全转换成了 <b>（**没转换的话页面上
     会明晃晃挂着星号**）、四档色带四色不同、架构框图五个节点四个箭头、
     每个卡头都有图标、返回键渲染出来了。
  B  首页那一格：`a[href="about.html"]` 在、href 对、
     **「导航」和它同一行且导航在左**（用户 2026-09-25 晚点名的左右顺序），
     而且**点一下真的到这一页**。
     ⚠️ 2026-09-25 晚（第十七次改版）之前这一格是 `qk-full`（跨满整行）。
        用户点名要「导航」和「帮助 & 关于」同一行，`index.html` 摘掉了 `qk-full`，
        所以"跨满"这条判据**跟着退役**（不是漏写）—— 换成了"同一行 + 左右顺序
        + 每行都铺满"。洞的判据（每行宽度之和 ≈ 网格宽度）保留，它才是当年
        那条判据真正要防的东西。

用法：
    python _scratch\\_check_about.py [端口] [CDP端口] [页面路径]
⚠️ 页面路径默认是 `/static/about.html`，**不是** `/about.html` —— 理由见下面那段。
⚠️ **第三个参数以斜杠开头，在这个 shell 里必须带
   `MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*'`**：本机 Git Bash 会把它当 Windows
   路径改写成 `C:/Program Files/Git/about.html`，`goto` 于是导航到一个不存在的 URL、
   **页面静默留在上一张**（about:blank）。症状是 `S.js(A_JS)` 返回 `None`，随后在
   `a["path"]` 上抛 `TypeError: 'NoneType' object is not subscriptable` ——
   看着像脚本坏了，其实是**这一次调用**把参数传坏了。完整跑法：
       MSYS_NO_PATHCONV=1 MSYS2_ARG_CONV_EXCL='*' PYTHONIOENCODING=utf-8 ^
         D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_check_about.py 8765 9429 /about.html
⚠️ 服务器不在这里启动 —— 用用户自己那台（默认 8765，见别的 `_check_*`）。
⚠️ `_check_pages.Session` 的 `BASE` 是**模块级**的，`sys.argv[1]` 在 import 时读；
   所以下面先摆好 `sys.argv` 再 import（这一步漏了会打到默认的 8790 去）。

★★ 为什么 A 段验的是 `/static/about.html` 而不是 `/about.html`
   `ui/server.py` 的页面不是通配静态目录，而是 `PAGES` 元组**逐页注册**的路由。
   新页登记进去了，但**正在跑的那台服务器是登记之前启动的** —— 路由表在进程里，
   不重启就不认，`/about.html` 会回 404（浏览器里就是一张白页，
   看起来和"页面写错了"一模一样；这次就是这么踩的）。
   而 `/static` 是 `add_static(WEB, ...)` 整个目录挂上去的，
   所以**同一个文件**能从 `/static/about.html` 被真实地渲染一遍 ——
   CSS / JS / 图标走的都是绝对路径 `/static/...`，一个字都不用改，
   渲染结果和重启后的 `/about.html` 完全一致（唯一区别是 `location.pathname`）。
   重启之后可以直接把第三个参数传 `/about.html` 复核。
"""
import asyncio
import io
import os
import sys
import urllib.error
import urllib.request

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)

PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
CDP = int(sys.argv[2]) if len(sys.argv) > 2 else 9509
PAGE = sys.argv[3] if len(sys.argv) > 3 else "/static/about.html"
sys.argv = [sys.argv[0], PORT]                    # ← 必须在 import 之前

import _check_pages as CP                          # noqa: E402

CP.PORT = PORT
CP.BASE = "http://127.0.0.1:%s" % PORT
ck = CP.ck

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")

# ---------------------------------------------------------------- A 段探针
# 一次性把介绍页上所有要判的东西读回来。**别拆成多次 S.js**：每一次都是一趟
# CDP 往返，而且中途页面若重画，两次读数会来自两个不同的页面状态。
A_JS = r"""(function(){
  const doc = document.getElementById('doc');
  const txt = doc ? doc.textContent : '';
  const cards = doc ? doc.querySelectorAll(':scope > .card') : [];
  const h3svg = doc ? doc.querySelectorAll('.card-h h3 svg') : [];
  const dots = [...document.querySelectorAll('.ab-sev .dot')]
                 .map(e => getComputedStyle(e).backgroundColor);
  const v = document.querySelector('.ab-row .v');
  return JSON.stringify({
    path: location.pathname,
    title: document.title,
    h1: (document.querySelector('.ptitle h1') || {}).textContent || '',
    back: (document.querySelector('.ptitle .back') || {}).getAttribute
            ? document.querySelector('.ptitle .back').getAttribute('href') : '',
    backSvg: !!document.querySelector('#backBtn svg'),
    cards: cards.length,
    rows: doc.querySelectorAll('.ab-row').length,
    keys: [...doc.querySelectorAll('.ab-row .k')].map(e => e.textContent),
    lv: doc.querySelectorAll('.ab-sev .lv').length,
    lvNames: [...doc.querySelectorAll('.ab-sev .nm')].map(e => e.textContent),
    dots: dots,
    fn: doc.querySelectorAll('.fn').length,
    fa: doc.querySelectorAll('.fa').length,
    cells: doc.querySelectorAll('.ab-cell').length,
    h3: doc.querySelectorAll('.card-h h3').length,
    h3svg: h3svg.length,
    // ⚠️ 这条是这次最容易翻车的地方：`md()` 只认 `**…**`。
    //    有一个星号漏网，页面上就挂着一个 `**`。
    stars: (txt.match(/\*/g) || []).length,
    bold: doc.querySelectorAll('.ab-row .v b, .ab-cell p b').length,
    // 「已经做到的」清单：这些是方案里有、仓库里没有的模块，**这页不许出现**
    // （它们在 flow.html 里以虚线节点单列）。写进来就是给自己挖坑。
    leak: ['YOLO', 'MAX30102', '手势', '心率'].filter(w => txt.includes(w)),
    // 中文标点后面挂一个空格 = 排版毛病。两个来源都见过：
    //   ① 源码里的换行 —— HTML 把换行折成空格，中文句子中间就多一个空格；
    //   ② `**…**` 那个星号后面本来带的空格 —— 转换后它留在 `</b>` 后面，
    //      读出来是「检测。 姿态关键点」（`md()` 里第二条 replace 就是修它）。
    // ⚠️ **`） → ` 不算**：箭头两侧的空格是这页刻意排的（全站的 `· → ·` 都这样），
    //    排掉反而糊在一起。所以跟着箭头那一个不数。
    sp: (() => {
      const re = /[，。；：、）]\s+(.)/g; let m; const bad = [];
      while ((m = re.exec(txt))) if (m[1] !== '→') bad.push(m[0]);
      return bad.length;
    })(),
    // 第一段正文的头 40 个字，用来人眼确认不是空串、也不是一串星号
    sample: (v ? v.textContent : '').slice(0, 60),
    // ★★ 公共类名撞车检测（这一版新增）。
    //    这页有几处"纯文字"的格子，本该是**没有底色、没有描边**的。
    //    只要类名和 `pages.css` 里某个公共类重名，公共类的那几条属性就会漏进来
    //    —— 这次就撞上了：说明文字用了 `.nt`，而 `pages.css:1512` 的 `.nt` 是
    //    首页那三格「未接入」数字块（带底色 + 描边 + 圆角 + 内边距 + 居中），
    //    于是十来个字的说明被套上一个方块（实测高 31px，本该 19px）。
    //    **背景色和上边框是最直接的两个指纹**：撞上了它俩一定不是零。
    clean: (() => {
      const bad = [];
      for (const e of document.querySelectorAll('.ab-sev .ab-nt, .ab-row .v, .ab-cell p')) {
        const s = getComputedStyle(e);
        if (s.backgroundColor !== 'rgba(0, 0, 0, 0)' || s.borderTopWidth !== '0px')
          bad.push((e.className || '?') + ' 底色=' + s.backgroundColor
                   + ' 上边框=' + s.borderTopWidth);
      }
      return bad;
    })(),
    // 色带里那格说明**必须是一行**（窄到折行就说明两列分得不对）。
    ntH: Math.round(document.querySelector('.ab-sev .ab-nt')
                    .getBoundingClientRect().height),
    errs: 0,
  });
})()"""

# ---------------------------------------------------------------- B 段探针
# 首页那两格（「导航」+「帮助 & 关于」）。**洞的判据用"行内宽度之和 ≈ 网格宽度"**，
# 不要用"有没有第 N 格"—— 有几格本身证明不了任何事，**行有没有铺满**才是
# 当年那条判据真正要防的东西（右下一格空着），而铺满是几何事实，量出来才算数。
# ★ 2026-09-25 晚新增：这两格**必须同一行**，且导航在左 —— 用户点名的。
# 按 [[cdp-click-gotchas]]，`elementFromPoint` 才是"点得动吗"的权威，所以顺手量。
B_JS = r"""(function(){
  const g = document.querySelector('.qk-grid');
  if(!g) return JSON.stringify({none: 'no .qk-grid'});
  const gr = g.getBoundingClientRect();
  const cs = getComputedStyle(g);
  const items = [...g.querySelectorAll('.qk')];
  const gap = parseFloat(cs.gap) || 0;
  const a = g.querySelector('a[href="about.html"]');
  const nv = g.querySelector('a[href="nav.html"]');
  // 按 top 分行（容差 4px：同一行的卡 top 应当一致）
  const rows = [];
  for(const e of items){
    const r = e.getBoundingClientRect();
    const hit = rows.find(x => Math.abs(x.top - r.top) < 4);
    if(hit){ hit.w += gap + r.width; hit.n += 1; }
    else rows.push({top: r.top, w: r.width, n: 1});
  }
  const rect = (e) => e ? e.getBoundingClientRect() : null;
  const ra = rect(a), rn = rect(nv);
  /* 中心点上是谁 —— 点得动的唯一权威（截图和 CSS 都看不出谁压谁） */
  const hitAt = (e) => {
    const r = rect(e);
    if(!r) return 'null';
    const h = document.elementFromPoint(r.left + r.width/2, r.top + r.height/2);
    if(!h) return 'null';
    return (h === e || e.contains(h)) ? 'self' : (h.tagName.toLowerCase()
      + (h.id ? ('#'+h.id) : '') + (h.className && h.className.baseVal === undefined
        ? ('.'+String(h.className).trim().split(/\s+/).join('.')) : ''));
  };
  return JSON.stringify({
    n: items.length,
    full: !!a,
    href: a ? a.getAttribute('href') : '',
    label: a ? a.textContent.trim().slice(0, 20) : '',
    gridW: Math.round(gr.width * 10) / 10,
    rows: rows.map(x => ({n: x.n, w: Math.round(x.w * 10) / 10})),
    // 「导航」那一格的文案 + 它在不在
    navHere: !!nv,
    navLabel: nv ? nv.textContent.trim().slice(0, 20) : '',
    // 同一行 = 上下沿都对齐（容差 2px）
    sameRow: (!!ra && !!rn)
             ? (Math.abs(ra.top - rn.top) < 2 && Math.abs(ra.bottom - rn.bottom) < 2)
             : false,
    // 导航在左 = 它的左沿比「帮助 & 关于」的左沿靠左
    navLeft: (!!ra && !!rn) ? (rn.left < ra.left - 4) : false,
    // 跨满 = 左边贴网格左边、右边贴网格右边（**现在应当是 false**）
    flush: ra ? (Math.abs(ra.left - gr.left) < 1.5
                 && Math.abs(ra.right - gr.right) < 1.5) : null,
    aboutW: ra ? Math.round(ra.width * 10) / 10 : 0,
    hitAbout: hitAt(a), hitNav: hitAt(nv),
  });
})()"""


def http_status(path):
    """只用来**报告**（不当判据）：`/about.html` 现在通不通，取决于
    这台服务器是不是在登记 `about` 之后重启过。"""
    try:
        with urllib.request.urlopen(CP.BASE + path, timeout=4) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:                             # noqa: BLE001
        return str(e)


async def main():
    worst = 0
    print("\n[状态] /about.html -> %s   %s   /static/about.html -> %s"
          % (http_status("/about.html"),
             "（服务器未重启时会是 404，正常）" if http_status("/about.html") == 404 else "",
             http_status("/static/about.html")))

    async with CP.Session(CDP) as S:

        # ============================================================ A
        print("\n=== A 帮助 & 关于 · 内容真的渲染出来了 ===")
        await S.goto(PAGE, 2.2)
        a = await S.js(A_JS)

        worst |= ck("落在介绍页上", a["path"] == PAGE, a["path"])
        worst |= ck("标题是「帮助 & 关于」", a["h1"].strip() == "帮助 & 关于", a["h1"])
        worst |= ck("★ 六个内容节 + 尾部导航", a["cards"] == 7,
                    "`.flow > .card` = %d 张（六节 + 还想看细节）" % a["cards"])
        worst |= ck("★ 正文普通卡 7 张", a["cards"] == 7, "")
        worst |= ck("标签行 4+3+3+4 = 14", a["rows"] == 14, "读到 %d 行" % a["rows"])

        print("     标签： %s" % " / ".join(a["keys"]))
        worst |= ck("★ 「融合策略」那一行在",
                    any("融合" in k for k in a["keys"]), "标签表里有它")
        worst |= ck("四档色带 4 行", a["lv"] == 4, "读到 %d 行" % a["lv"])
        worst |= ck("四档名与代码一致",
                    a["lvNames"] == ["清醒", "轻度疲劳", "中度疲劳", "重度疲劳"],
                    " / ".join(a["lvNames"]))
        worst |= ck("★ 四档四色互不相同", len(set(a["dots"])) == 4,
                    "  ".join(d.replace("rgb(", "").replace(")", "")
                              for d in a["dots"]))
        worst |= ck("架构框图 5 节点", a["fn"] == 5, "读到 %d 个 .fn" % a["fn"])
        worst |= ck("节点之间 4 个箭头", a["fa"] == 4, "读到 %d 个 .fa" % a["fa"])
        worst |= ck("亮点四宫格 4 格", a["cells"] == 4, "读到 %d 格" % a["cells"])
        worst |= ck("每个卡头都有图标", a["h3svg"] == a["h3"],
                    "%d 个 h3 / %d 个图标" % (a["h3"], a["h3svg"]))
        worst |= ck("返回键渲染出来了", a["backSvg"] and a["back"] == "index.html",
                    "href=%s" % a["back"])
        # ↓↓↓ 这一条是这次改版最容易翻车的地方
        worst |= ck("★★ 正文里一个星号都不剩", a["stars"] == 0,
                    "残留 `*` = %d 个（`md()` 漏转换的话页面上就挂着 **）" % a["stars"])
        worst |= ck("★ 重点真的变了粗", a["bold"] >= 8,
                    "`.ab-row .v b` + `.ab-cell p b` = %d 处" % a["bold"])
        worst |= ck("未实现模块没混进来", not a["leak"],
                    "页面里搜到：%s" % (a["leak"] or "无"))
        worst |= ck("中文句子没被折行掺空格", a["sp"] == 0,
                    "标点后跟空格 = %d 处" % a["sp"])
        worst |= ck("★★ 纯文字格没被公共类套上底色", not a["clean"],
                    "  ".join(a["clean"]) if a["clean"] else "无底色、无边框")
        worst |= ck("★ 色带说明是一行", a["ntH"] <= 26,
                    "说明那格高 %dpx（折行会到 30+）" % a["ntH"])
        worst |= ck("★ 控制台无报错", not S.errs, str(S.errs[:3]))
        print("     正文抽样： %s…" % a["sample"])

        # ============================================================ B
        print("\n=== B 首页那两格入口（导航 + 帮助 & 关于）===")
        await S.goto("/index.html", 2.4)
        b = await S.js(B_JS)

        worst |= ck("首页有 .qk-grid", "none" not in b, b.get("none", ""))
        worst |= ck("★ 「帮助 & 关于」那一格在", b.get("full"),
                    "文案「%s」" % b.get("label", ""))
        worst |= ck("href 指向 about.html", b.get("href") == "about.html",
                    b.get("href", ""))
        worst |= ck("★ 「导航」那一格也在", b.get("navHere"),
                    "文案「%s」" % b.get("navLabel", ""))
        worst |= ck("快捷功能共 6 格", b.get("n") == 6, "读到 %d 格" % b.get("n", 0))
        # ★ 用户 2026-09-25 晚点名的：同一行、导航在左
        worst |= ck("★★ 两格**同一行**", b.get("sameRow"), "")
        worst |= ck("★★ **导航在左**、帮助 & 关于在右", b.get("navLeft"), "")
        # 第十七次改版取消了跨满 —— 这条现在是"别再跨回去"
        worst |= ck("★ 它**不再**跨满整行（第十七次改版）", b.get("flush") is False,
                    "跨满=%s 宽 %.1f / 网格 %.1f"
                    % (b.get("flush"), b.get("aboutW", 0), b.get("gridW", 0)))
        # 洞的判据：每一行"宽度之和"都该等于网格宽度
        bad = [r for r in b.get("rows", [])
               if abs(r["w"] - b.get("gridW", 0)) > 2]
        worst |= ck("★★ 每一行都铺满、右下角没有洞", not bad,
                    "行分布 " + " ".join("%d格/%.0fpx" % (r["n"], r["w"])
                                        for r in b.get("rows", [])))
        # 点得动吗 —— 中心点上必须是自己（不是被谁压着）
        worst |= ck("★ 两格中心点都点得动（没有被谁压着）",
                    b.get("hitAbout") == "self" and b.get("hitNav") == "self",
                    "帮助&关于=%s · 导航=%s" % (b.get("hitAbout"), b.get("hitNav")))

        # 点一下真的过去（不是只写了个 href）。
        # ⚠️ 服务器没重启时这一步**必然**落到 404 白页上 —— 那不是"链接写错了"，
        #    是路由表还没生效。这种时候报红会误导人，所以**说清楚再跳过**，
        #    而不是硬判一个必错的断言（判了就等于教人忽略这条红）。
        # ⚠️ 2026-09-25 晚：选择器从 `a.qk-full` 换成 `a[href="about.html"]`
        #    （那一格不再挂 `qk-full` 了）。
        if http_status("/about.html") == 404:
            print("  --  「点一下真的到介绍页」跳过：这台服务器还没重启，"
                  "/about.html 仍是 404")
            print("      （登记已经在 ui/server.py 的 PAGES 里了；重启后重跑本脚本即可）")
        else:
            await S.js("document.querySelector('.qk-grid a[href=\"about.html\"]')"
                       ".click()")
            await asyncio.sleep(1.8)
            here = await S.js("location.pathname")
            worst |= ck("★ 点一下真的到介绍页", here == "/about.html",
                        "落在 %s" % here)
        worst |= ck("首页控制台也无报错", not S.errs, str(S.errs[:3]))

    print("\nEXIT = %d  （0 = 全过）" % worst)
    return worst


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
