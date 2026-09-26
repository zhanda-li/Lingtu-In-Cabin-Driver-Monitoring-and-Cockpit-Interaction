"""验亮色调(12.png)那一整套 + 换品牌 + 删说明文 + 删气候栏 + 顶栏右上角换院徽。

范围：**全站 12 页**（2026-09-24 全量推广后是 11 页；2026-09-25 晚 nav 回来变 12）。
2026-09-23 它只管 cover / nav 两页（那时只有这两页是浅色）；
09-24 其余 9 页也刷成浅色，于是遍历扩到全站，并且把
`design.html` 加进来**反过来断言它必须是深色**（例外理由见 PAGES 上面那段）。
每页的期望主题由 PAGES 一处定义。

★★★★ 2026-09-25 深夜（最新一条，读别的之前先读这条）：
`nav.html` **整页建回来了**（左栏第五项「导航」，底下挂真高德）。
   ✅ 回来的：`PAGES` 里那一行（11 页 → 12 页，浅色）。
   ❌ **没回来的**（下面那段里删掉的东西，绝大多数依然没有对象）：
      · F 段整段（旧 nav 那张路线图的浅色配色判据）—— 新页没有那几个 SVG 部件；
      · D 段三条 + 探针里三个 key（`.unwired` / `.pill` / `#destNote`）——
        新页是卡片式页面，没有说明文、没有徽标、没有目的地计数；
      · `WX_PAGES`（天气那一组整块没了，跟 nav 在不在无关）。
   → 新页要守什么，写在 `_check_pages.py` 的 nav 那一段旁边（那里是把 09-24
     删掉的四条**按新页重写**的版本，不是照旧抄回来）。
   ⚠️ 新页也是浅色，所以它就是 PAGES 里的 `("nav", "/nav.html", "light")` 一行，
      其余判据（A 段读 `:root`、C 段截图存图）都自动覆盖到它。

★ 2026-09-24 晚：`nav.html` **整页删除**（用户「把导航页删了吧」），
所以 12 页变 11 页，nav 那一整段判据也跟着删了。**删掉的比"一页的计数"多得多**，
一并记在这里免得下次有人以为是漏写：
  · PAGES 里那一行、WX_PAGES 里的 `nav`（天气那条只在 cover 上等了）；
  · D 段三条 nav 专属（`.unwired` / `.ptitle .pill` / `#destNote`）；
  · **F 段整段** —— 那是 nav 那张路线图的**浅色配色判据**（路是墨蓝不是白、
    车标的芯 == `--on-accent`、环/终点 pin == `--accent`、水滴头 == `--accent`、
    以及"地图卡里不许有近黑填色"的兜底扫描）。**那张图随页一起没了，
    这一整段没有任何替代物** —— 别再去找它。
  · 探针里 9 个只为 nav 存在的键（`unwired` / `pill` / `destNote` / `roadStroke` /
    `carFill` / `carStroke` / `pinFill` / `pinHeadFill` / `mapDarkFills`）。
⚠️ 有一件事**没有**跟着 nav 走：下面那条「座舱页顶栏中间是空的」原来拿 nav 当靶子，
   已改指 `index`（那条验的规矩是全站性的，不是 nav 独有的）。

★ 2026-09-24 晚（第二批）：**顶栏右上角那一整格换掉了。**
用户原话「把这里边14.png的标放到首页的右上角 天气那些去掉」+ 追问确认
「整块 env 全去掉，连语音标识也去」。于是：

  · `XQ.env` 整个模块（定位 → 取天气、探测联网状态）**连根删**，
    模板里的 `<div class="env">`、style.css 的两组规则、mountChrome 里那句
    init 调用，四处一起走；
  · `XQ.tts.paintTopbar()`（填那个「小瑞语音」状态标识的）**连同它的两个
    调用点一起删** —— 语音开关本身还在（左导航那张说明牌 + `#voiceNote`），
    丢的只是顶栏那一份显示；
  · 顶上换成一个 `.collab` 格，里面放同济大学汽车与能源学院院徽，
    **只有封面传 `logo:true`**，其余 10 页这一格是空的（空着也占位）。
    ★ 2026-09-25 晚起，"其余 10 页这一格是空的"**不再成立**：用户点名要在
    右上角加一个用户入口，那 10 页的 `.collab` 里现在是它（封面仍是院徽，
    两拨共用一个格子、二选一）。所以 B2 那条"这一格是空的"改按 `.collab-logo`
    数（院徽那两张），用户入口单开 B3 段判 —— 见下面 B2 里那段说明，
    那是**判据腐坏**，不是页面坏了。

  连带删掉的判据（**对象没了，不是"少验了几条"**）：
    · `WX_PAGES` + `wait_wx()` + `is_num_temp()` + **E 段整段**
      （「天气不再是占位符」「给出了数字温度」「联网状态已落定」
        「说在线就真拿到了天气」「在线时信号格是亮的」）；
    · 探针里 `xqEnvInit` / `voiceTxt` / `voiceOff` / `voiceTitle` /
      `wx` / `net` / `wxHTML` / `barsLit` 八个键；
    · A0 那条「XQ.env.init 是函数」、I 段那三条语音标识的判据。
  ⚠️ **`re` 这个 import 也跟着没了** —— 全文件只有 `is_num_temp` 用它。
  ⚠️ 这同时意味着**本脚本不再依赖外网**了（原来"真天气"那条是全库唯一一条
     会因外网状况而假红的判据）。以后看到天气相关的假红，别再来这儿找。
  ✅ 换来的新判据：`clockHTML({logo:true})` 真吐出两张院徽的路径、
     封面 `.collab` 里两张图都在且都加载出来了、**其余 10 页这一格没有院徽**、
     以及全站 `.env` 元素一个不剩（"删干净"不是"藏起来"）。
  ★ 2026-09-25 晚新增 B3 段：右上角那个**用户入口**（座舱页有、封面没有），
    连同"封面那条分支里不许出现它"的**反向**判据 `clockLogoNoUser`。

★ 2026-09-24 晚（第三批）：**档位色由三档（疲劳程度）改成四档（安全级别）。**
用户原话「分心不是重度疲劳 我的训练模型里作为黄色预警 算作单独分心吧」。
`--sev-*` 由 `normal/mild/severe` 三值改成 `normal/glance/phone/fatigue` 四值
（键名跟 `src/live.py:58` 的 CLASS_LEVEL 走），只新增两个色值，
橙/红两档的值一个没动。所以本脚本的 WANT_LIGHT / WANT_DARK 各多一行。
  ✅ 同时新增 **K 段**：`--sev-*` 那两份**拷贝**（design.html 的 `.sev-s[data-sev]`
     四格、phone.html 的 `.phone[data-sev]` 三台）也要逐格验。
     为什么单开一段：A 段读的是 `documentElement` 上的 `:root` 值，
     **碰不到那两份拷贝** —— 改色改一半、抄错一个十六进制、漏抄一格，A 段全绿，
     而页面上那一格是错的色。⚠️ phone.html 那三格**故意只有三个键**，
     而且键名是"疲劳程度"不是"级别"（那是另一条轴，不是漏抄），见 K 段注释。

★ 2026-09-24 深夜（第四批，就是当前这一版）：**「只做疲劳」—— 键名换了一遍，
  值一个没动。** 上面第三批那条「四档=安全级别、phone.html 三格是另一条轴」的记录
  到这一步就作废了：两条轴（行为类别 / 疲劳档位）合成了一条，
  `--sev-*` 的键改成**档位名** `normal/mild/moderate/severe`
  （= `ui/state.py` 的 SEVERITY_NAMES 那四个键），`glance` 整档删除。
  因为只是**改名**，`#18D7C5 / #FFD400 / #FF9830 / #FF4055` 这四个值逐字保留，
  浅色那套同理 —— 所以这份表的"值"部分和改名前完全一样，变的只有键。
  ✅ 连带改：phone.html 从三台手机变成**四台**（补上中度那一档），
     K 段现在**两处都按四键断言**，"三格/三个键/另一条轴"那些话全部删掉。
  ⚠️ 键名是**档位**不是**类别**，别拿 `src/live.py` 的 CLASS_LEVEL
     （`normal/phone/fatigue`，只有三个键）来对照 —— 那是支路一的输出，
     只在 index.html 那三行概率条上出现。两套名字的分工写在
     ui/web/pages.css 顶部和 ui/state.py 的模块 docstring 里。

    python _scratch/_check_theme2.py 8790

跑之前服务得先起着（本脚本不负责起服务）：
    D:\\Anaconda3\\envs\\dms\\python.exe ui\\server.py --port 8790 --source demo

## 这个脚本要证明什么，以及**为什么每一条都得真去浏览器里读**

改的东西性质不一样，所以判据也不一样：

  · **主题真的生效了** —— 不能只看 HTML 里写了 `data-theme="light"`。
    写了但 CSS 选择器写错（比如写成 `[data-theme=light] .x` 而变量在 `:root` 上），
    页面会**照样按深色渲染**，而且一声不吭。所以这里读的是
    `getComputedStyle` 解出来的**变量实际值**，和 style.css 里那组字面量比。
  · **标志换对了** —— 两张图都在 DOM 里，靠 CSS 二选一。写错的表现是
    "两张都显示"（叠在一起）或"都不显示"（空框），两种都得判。
    所以 `.on-dark` / `.on-light` 要分别读 `display`，还要读 `naturalWidth`
    确认图**真的加载出来了**（`display:block` 但图 404 也是一样的空框）。
  · **删干净了** —— 气候栏、说明文、pill、天气那一组。这几个是"删掉"不是"藏起来"，
    所以查的是 `querySelector(...) === null`，不是可见性。
  · **顶栏右上角那一格换人换对了** —— 两张院徽图都在 DOM 里靠 CSS 二选一
    （和标志同一个机制，所以判据也照抄：`display` + `naturalWidth` 都要读），
    而且**只有封面有**（其余 10 页那一格必须是空的）。
    ⚠️ 和 `.env` 那组不同的是：这一格**只加不删**，所以"封面有图"和
      "别的页是空的"两条**都得判** —— 只判前者的活，哪天有人把 `logo:true`
      抄进所有页也照样绿。

⚠️ 这个脚本**证明不了**：亮色调好不好看、12.png 那套色对不对味、标志大小合不合适。
   那些只有人眼说了算，所以它会顺带出两张截图。
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
SHOTS = Path(__file__).parent / "_shots"
CDP = 9429          # ⚠️ 必须是 **int**：Session 里拿它直接喂 socket.connect

# style.css 里浅色那组的关键值。**故意写死在这里**（不是从 CSS 里读回来比）：
# 从 CSS 里读回来再和自己比是恒真的，等于没验。
WANT_LIGHT = {
    "--page-bg": "#E4F0FB",
    "--ink": "#0E2A4A",
    "--cta-a": "#3E9BF0",
    # ★ 2026-09-24 第四次改版：原来这里是 `"none"`（浅色主题**没有**底图，
    #   夜景图被撤掉，底就是一片 --page-bg）。用户点名「把刚打开浏览器 没进入
    #   座舱前的背景变成 背景.png 图」之后，浅色也有底图了 —— 座舱内那几页用
    #   `bg_wash.jpg`（缩小+模糊+白蒙版洗成纹理），封面用 `bg_scene.jpg` 原色。
    #   这里跟着改成真实值。**留一个 `"none"` 就会横着红 10 页**，而真凶是
    #   底图换代了、判据没跟上（形态和"底图丢了"一模一样，别被它带偏）。
    "--bg-img": 'url("assets/bg_wash.jpg")',
    # 四档状态色（2026-09-24 从 6 处硬编码收进变量；当晚由三档改成四档，
    # 深夜「只做疲劳」又把键名换成档位名 —— 值两次都没动）。
    # **必须逐字比** —— 抄错的表现是"某一档的文字/圆点颜色不对"，不报错、也不显眼。
    "--sev-normal":   "#1E7FD8",
    "--sev-mild":     "#A87B00",
    "--sev-moderate": "#D98212",
    "--sev-severe":   "#D62B44",
}
WANT_DARK_INK = "#F4F8FA"      # 没写 data-theme 的页应该还是这个

# ── 2026-09-24 全量推广：11 页里 10 页刷成浅色，**design.html 故意保持深色**
# 为什么它例外：design.html 整篇讲的就是**深色那套色板**（满页是 .sev-s /
# .glass-demo 这些样本，正文连"浅色"两个字都没出现过）。刷成浅色会和它自己的
# 内容打架 —— 一份"色板说明书"本身用的是另一套色板，没法读。
# ⚠️ 所以这里对它**反过来断言**（必须是深色），免得哪天有人"顺手统一一下"。
# ★ 这里原来还有 nav 一行（12 页）；nav.html 09-24 整页删除（见文件头那段），
#   **2026-09-25 晚又建回来了**（左栏第五项「导航」，底下挂真高德）→ 12 页，
#   nav 那一行也回来了，位置按左栏的次序排在 `monitor` 前面。
#   ⚠️ 它这次**不是**原来那张画几何图的自制页，所以 F 段（旧 nav 的浅色配色判据）
#      依然**没有**复活 —— 那些判据的对象（路/车标/终点 pin 那几个 SVG 部件）
#      在新页上不存在。新页要守什么，见 `_check_pages.py` 的 nav 那一段。
# ★ 2026-09-25「第八次改版」加了 monitor 一行：`detail.html` 的「更多」跳到它，
#   它和 detail 同主题（浅色）、用的是同一套 chrome（`XQ.mountChrome`）。
# ⚠️ 每行第 4 个字段（"这一页要不要等天气"）2026-09-24 随天气那一组一起删了 ——
#    现在 PAGES 是**三元组**，两个解包点（这里和 main 的遍历）都要跟着改。
PAGES = [
    # ⚠️ `?intro=0`：封面 2026-09-25 起有一层**全屏不透明的品牌片头**。
    #    这个脚本要量"这一页浅色渲染成什么样"并**存图给人看**，一层 `#000`
    #    盖子会让所有判读失真。片头的开关见 cover.html 末尾那段注释。
    ("cover",    "/?intro=0",      "light"),
    ("index",    "/index.html",    "light"),
    ("detail",   "/detail.html",   "light"),
    ("monitor",  "/monitor.html",  "light"),
    # ★ 2026-09-26：「数据详情」页（首页那一格 / 驾驶监测页那个入口）。
    #   浅色，和它两个入口的页面同主题。它**不在左导航里**（`active: ''`，
    #   照 about.html 的做法），但这和"要不要截图看它"是两件事 ——
    #   这个清单只管后者，而它是唯一会让人眼看到这一页的入口。
    ("data",     "/data.html",     "light"),
    ("nav",      "/nav.html",      "light"),
    ("media",    "/media.html",    "light"),
    ("settings", "/settings.html", "light"),
    ("chat",     "/chat.html",     "light"),
    ("flow",     "/flow.html",     "light"),
    ("link",     "/link.html",     "light"),
    ("phone",    "/phone.html",    "light"),
    ("voice",    "/voice.html",    "light"),
    ("design",   "/design.html",   None),
]
# 页名 → 该页应处的主题（`None` = 不该有 data-theme 属性，即深色）。
# 从 PAGES 派生而不是手抄一遍：抄的话这两处哪天会不一致，
# 而不一致的表现是"判据和遍历对不上"，比报错难查。
EXPECT = {name: want for name, _path, want in PAGES}

# ★ 2026-09-24：`WX_PAGES = ("cover",)` 和它配套的 `wait_wx()` 已删 ——
#   天气那一组整块没了，没有"要等的页"这回事了。见文件头那段。

# design.html 该有的深色值。**只列可靠的两条** ——
# `--bg-img` 的计算值是 `url("assets/bg.jpg")`，引号/转义容易被写成一个恒假的判据。
WANT_DARK = {
    "--page-bg": "#050B14",
    "--ink":     WANT_DARK_INK,
    # 四档色的深色那套。和 `body[data-sev]` 里那四条**逐字相同** ——
    # 分叉的话表现是"design.html 的样本和自己的 --accent 不是一个色"。
    "--sev-normal":   "#18D7C5",
    "--sev-mild":     "#FFD400",
    "--sev-moderate": "#FF9830",
    "--sev-severe":   "#FF4055",
}

# 冻结动画/WebSocket，理由同 _theme_shots.py：截图要确定性。
# ★ 2026-09-24：原来这里还写着「**不桩 fetch** —— 天气那条正是本次要验的东西」。
#   天气整块删掉之后**没有理由再保留 fetch 了**，但也没理由去桩它：
#   现在全站一个 fetch 都不发。留着那句注释会让人以为"这里不桩是有讲究的"。
WS_STUB = """
(() => { const D = function(){ this.readyState = 0; this.send = () => {};
  this.close = () => {}; this.addEventListener = () => {}; };
  D.CONNECTING = 0; D.OPEN = 1; D.CLOSING = 2; D.CLOSED = 3;
  window.WebSocket = D; })();
"""
FREEZE = """
(() => {
  const st = document.createElement('style');
  st.textContent = '*,*::before,*::after{animation:none !important;transition:none !important;}';
  document.head.appendChild(st);
})()
"""

# 页面上一次性把该读的都读了。用 `JSON.stringify` 回来，`S.js` 会自动解。
PROBE = r"""
JSON.stringify((() => {
  const cs = getComputedStyle(document.documentElement);
  const vars = {};
  ['--page-bg','--ink','--cta-a','--bg-img','--fill-2','--hair','--track',
   '--on-accent','--sev-normal','--sev-mild','--sev-moderate','--sev-severe']
    .forEach(k => vars[k] = cs.getPropertyValue(k).trim());
  /* ⚠️ `--accent` **不在 `:root` 上**，它按档位定义在 `body[data-sev=...]`
     （style.css:102-104，浅色那组在 164-166）。从 documentElement 读它必然是空串 ——
     我第一次写这条判据就是这么假红的（`vs ` 后面空着）。
     判据是从**计算值**读的，所以必须从**真正定义了它的那个元素**读。 */
  vars['--accent'] = getComputedStyle(document.body).getPropertyValue('--accent').trim();

  /* ★ 2026-09-24 晚：**采样格自己有没有拿到档位色**。
     为什么要单验：`--sev-*` 那四个变量定义在 `:root` 上（A 段读的就是它），
     而页面里那些样本格 —— design.html 的 `.sev-s[data-sev]`、phone.html 的
     `.phone[data-sev]` —— 是**各自又写了一遍字面量**的（前者的页内 <style>、
     后者的页内 <style> 都有一份拷贝）。抄错一个十六进制、漏抄一格、或者
     值改了一半，A 段那几条断言**全都照样绿**（它读的是 documentElement），
     而页面上那一格是错的色。所以从**真正定义它的那个元素**上读 --accent。 */
  const accents = (sel) => {
    const r = {};
    document.querySelectorAll(sel).forEach((e) => {
      r[e.dataset.sev] = getComputedStyle(e).getPropertyValue('--accent').trim();
    });
    return r;
  };

  const img = (sel) => {
    const e = document.querySelector(sel);
    if (!e) return { missing: true };
    const s = getComputedStyle(e);
    return { display: s.display, naturalWidth: e.naturalWidth,
             src: e.getAttribute('src') || '' };
  };
  const txt = (sel) => {
    const e = document.querySelector(sel);
    return e ? (e.textContent || '').trim() : null;
  };
  /* ★ 2026-09-24 晚新增：读属性。品牌那两行字进了图片之后，
     "这张图画的是灵途智行"这件事**只剩 alt 问得到**。 */
  const attr = (sel, name) => {
    const e = document.querySelector(sel);
    return e ? (e.getAttribute(name) || '') : null;
  };
  return {
    theme: document.documentElement.getAttribute('data-theme'),
    vars,
    /* 两份拷贝各自的 --accent（没这页就是空对象，见 K 段） */
    sevSamples: accents('.sev-s'),
    phoneSamples: accents('.phone[data-sev]'),
    /* ★ chrome.js 有没有**真的干了活**。
       2026-09-23 补，起因是我在 clockHTML 那个模板字符串的注释里写了反引号，
       模板被当场截断 —— 整份 chrome.js 不执行、顶栏空白，
       而**浏览器控制台一条错都不报**，`G` 那条"零报错"给了一个假的通过。

       ⚠️ 所以这里**不是** `typeof XQ.clockHTML === 'function'` 就完事 ——
          模板截断之后 `XQ.clockHTML` **照样是个函数**（函数体语法合法），
          只是**一调就抛**。光看类型等于没验。
          必须**真调一遍**，并且检查返回的东西长得像不像那段 HTML。 */
    build: (() => {
      const r = {};
      const probe = (name, fn, ...needles) => {
        let s;
        try { s = fn(); } catch (e) { r[name] = 'THREW ' + e.name + ': ' + e.message; return; }
        if (typeof s !== 'string') { r[name] = 'not a string: ' + typeof s; return; }
        const miss = needles.filter(n => s.indexOf(n) < 0);
        r[name] = miss.length ? ('缺 ' + miss.join(',') + ' len=' + s.length)
                              : ('OK len=' + s.length);
      };
      /* ★ 2026-09-25 晚新增：**反过来的**那条 —— 某串必须不在模板里。
         为什么需要它：右上角那个用户入口只有座舱页该有，封面那一格放的是院徽。
         只有 probe 的话，"封面也被塞进了 tb-user"这个错**永远看不见**
         （两者会挤在同一个 .collab 里），而它恰恰是最容易犯的错 ——
         照抄上面那行 probe 的时候顺手带过去就行了。
         ⚠️ 报出来的形态要和 probe 区分开，别都叫"缺"：一个缺该有的、
           一个是多了不该有的，看日志的人得一眼分得清。 */
      const probeAbsent = (name, fn, needle) => {
        let s;
        try { s = fn(); } catch (e) { r[name] = 'THREW ' + e.name + ': ' + e.message; return; }
        if (typeof s !== 'string') { r[name] = 'not a string: ' + typeof s; return; }
        r[name] = s.indexOf(needle) < 0
          ? ('OK 没有 ' + needle + ' len=' + s.length)
          : ('不该出现 ' + needle + ' len=' + s.length);
      };
      /* ⚠️ 2026-09-24：needles 里原来有 `envWx` / `envVoice`，那一组删了 →
         换成 `class="collab"`（新那一格必须真的出现在模板里 —— 只是把
         `<div class="env">` 删掉、忘了补 `.collab` 的话，这一条就是唯一
         抓得住的地方，因为 `.collab` 空的也"看起来正常"）。 */
      /* ★ 2026-09-24 晚：needles 里那个 `LINGTU ZHIXING` 换成了两张图的路径。
         品牌组并成整张 lockup 之后，模板里**再也没有那几个拉丁字母** ——
         留着它就是一个恒假判据（报的形态是"chrome.js 没干活"，而其实是搬家）。
         换成两条路径**同时要**：只放一张的实现（比如只放深色版）在浅色顶栏上
         整个看不见，而那是封面唯一的主题。 */
      probe('clock', () => XQ.clockHTML(), 'class="brand"',
            'lingtu_lockup.png', 'lingtu_lockup_ink.png',
            'tbTitle', 'class="collab"',
            /* ★ 2026-09-25 晚：座舱页（logo 为假，就是这一条）右上角必须有
               那个用户入口。针脚挑 `user_avatar` 和 `tbUserBtn` 两个：
               前者证明**真头像接上了**（不是又画了个 SVG 人形），
               后者证明它是个**真按钮**（上一版"管理员"是个点不动的 div）。 */
            'class="tb-user"', 'id="tbUserBtn"', 'user_avatar');
      /* ★ 2026-09-24 新：**传了 logo:true 的**那条分支。
         和上面那条是两个不同的调用，必须分开验 —— 上面那条走的是
         `logo = false`（默认值），院徽那张图的路径根本没进过模板，
         所以只验上面那条的话，"院徽压根没接上"这个错是**看不见**的。
         ⚠️ 判据是**两张图的路径都在**：只写一张的实现（比如只放深色版）
             在浅色封面上会整个看不见，而那正是封面唯一的主题。 */
      probe('clockLogo', () => XQ.clockHTML({ title: 'x', logo: true }),
            'tongji_logo.png', 'tongji_logo_ink.png', 'class="collab"',
            'class="collab-logo on-dark"', 'class="collab-logo on-light"');
      /* ★ 2026-09-25 晚：封面那条分支上**不许**出现用户入口。
         `.collab` 只有一个格子，封面放院徽、座舱页放用户入口，二选一 ——
         两样都塞进去的话那一格会挤成一块，而且"院徽只有封面有"这条判据
         也再没人守得住。见上面 probeAbsent 的注释（这个错 probe 抓不到）。 */
      probeAbsent('clockLogoNoUser', () => XQ.clockHTML({ title: 'x', logo: true }),
                  'tb-user');
      /* ⚠️ 这里原来传的是 `active: 'navi'`；'navi' 09-24 从 NAV 里删了，
         再传它是个**不存在的 key**（不会报错，只是哪个都不点亮，探针照样绿 ——
         所以这条不会自己暴露）。改成 'mon'，它现在确实在 NAV 里。
         ★ 2026-09-25：'navi' 又回到 NAV 里了，但**这里继续用 'mon'** ——
         这条验的是"railHTML 能把某一项点亮"，不是"某一项还在"；
         用哪个 key 都一样，换来换去只会让上面这段注释白写一遍。 */
      probe('rail',  () => XQ.railHTML({ active: 'mon' }), 'rail-foot', 'CHERY');
      /* ★ 2026-09-23：时钟那条链**必须真的断了**，不能只是"没显示"。
         查的是函数本身没了 —— 这是"删干净"和"藏起来"的分界：
         函数还在、只是模板里没那个元素的话，mountChrome 里那个
         setInterval 会每 10 秒空转一次，而且**开够 10 秒才报错**。 */
      r.tickClock = typeof XQ.tickClock;
      return r;
    })(),
    /* ★ 2026-09-24：`xqEnvInit` 这个键已删（XQ.env 从根上没了），
       A0 那条断言跟着走。见文件头。 */
    topbarFilled: !!((document.getElementById('topbar') || {}).innerHTML),
    /* ★ 2026-09-24 晚：品牌组从「标志图 + 两行 HTML 文字（`.lingtu` /
       `.lingtu-mark` / `.lingtu-txt b,em`）」并成**一张整 lockup**
       （用户：「直接整张图替换所有左上角出现灵途智行标的部分」）。
       所以这里换个量法：`brandAlt` 读的是图片的 alt —— 那两行字**在图里**了，
       只读文件字节看不见它们，而 alt 是唯一还能在 DOM 上问"这张图画的是什么"
       的地方（_mk_lingtu2.py 生成的那张图上就有这四个字）。 */
    onDark:  img('.lingtu-lockup.on-dark'),
    onLight: img('.lingtu-lockup.on-light'),
    brandAlt: attr('.lingtu-lockup.on-light', 'alt'),
    brandLockup: img('.dash-brand img'),
    vline: document.querySelectorAll('.brand .vline').length,
    /* ⚠️ 必须**限定在 `#topbar` 里**。原来写的是 `.brand img[src*="chery"]`，
       而 `.brand` 这个类**封面页脚也在用**（那个 CHERY 是用户明确要求保留的，
       见 cover.html 页脚注释），于是这条判据在 cover 上**必然假红** ——
       它报的是"顶栏还有 CHERY"，实际匹配到的是页脚那张。
       教训：判"某处没有 X"时，选择器一定要**收窄到那一处**，
       全站扫同名类会把"别处合法存在"读成"这里没删干净"。 */
    cheryInTopbar: !!document.querySelector('#topbar img[src*="chery"]'),
    /* 左下角那个 CHERY 必须**还在**（用户：左下角不去除） */
    railFootMark: img('.rail-foot .brand-mark'),
    railFootName: txt('.rail-foot .rf-txt b'),
    /* 删掉的东西：查 null，不是查可见性 */
    climateEl: document.querySelectorAll('.climate').length,
    climateFn: typeof XQ.climateHTML,
    /* ★ 2026-09-24 这里原来还有三个 key —— `unwired` / `pill` / `destNote`，
       是 nav.html 的三条"说明文/徽标/目的地计数"判据的探针。nav 整页删除后
       没有任何一条断言再读它们，所以**一起删掉**了（留着就是三个每页都跑一遍、
       结果没人看的 querySelector）。同理见下面地图那几个。
       ⚠️ 2026-09-25 nav.html 建回来了，**这三个 key 也不要加回来** ——
          新页没有 `.unwired` 说明文、没有 `.ptitle .pill` 徽标、也没有"目的地计数"
          （它是卡片式页面，不是原来那张路线图）。要验新页就新开 key，
          别借这三个旧名字，否则读的人会以为是同一张页。 */
    coverSub: document.querySelectorAll('.cover-l .sub').length,
    coverTags: document.querySelectorAll('.cover-foot .tags').length,
    /* ★ 2026-09-24（照 13.png 第三次改版）：`eyebrow` 这一项**换掉了**。
       原来取的是 `#eyebrow`（左栏那颗眉标胶囊「灵途智行 · 小瑞情感化…」），
       13.png 的左栏第一行就是大标题、没有胶囊，那颗胶囊整块删了 ——
       留着这条探针就是每页查一个恒为 null 的选择器。
       现在取**新加的副标题**（13.png 大标题下面那一行）。
       ⚠️ 别把这一项删掉：下面 F 段那条断言是它唯一的用处，
          "副标题被谁删了/清空了"这个错只有它抓得住。 */
    coverSubLine: txt('.cover-l .cover-sub'),
    /* 整页正文里还有没有「奇瑞」这两个字。判"换成灵途智行"只查眉标是不够的 ——
       眉标看对了、别处还挂着一个，一样是同页两个品牌。 */
    bodyHasQirui: (document.body.innerText || '').indexOf('奇瑞') >= 0,

    /* ═══ 顶栏改版（2026-09-23 第二次）═══
       时钟整块拿掉、中间换成页面自管的槽。 */
    clockEl: document.querySelectorAll('.clock').length,
    hhmm: !!document.getElementById('hhmm'),
    tbTitle: txt('#tbTitle'),
    /* ═══ 顶栏右上角那一格（2026-09-24 第二次改版）═══
       原来那一整组「天气 / 信号格 / 联网 / 小瑞语音状态」删掉，换成院徽。
       ★ 判据分两半，**两半都要**：`envEl == 0`（旧的删干净了）和
         `collabEl`（新那一格真的在）。少了任何一半，一种"改到一半"都能溜过去。
       ⚠️ `envAvatar` 这个键已删：它查的是 `.env > svg` 里那个人头像，
          而 `.env` 整个没了 —— 那条断言会**恒真**（0 个），
          看起来是绿的、其实什么都没验。恒真的判据比没有判据更坏。 */
    envEl: document.querySelectorAll('.env').length,
    collabEl: document.querySelectorAll('.collab').length,
    collabDark: img('.collab .on-dark'),
    collabLight: img('.collab .on-light'),
    /* 🔴 2026-09-25 晚：这里原来是 '.collab img'，**必须改成 '.collab-logo'**。
       `.collab` 现在装了右上角那个用户入口，而它里面那个头像是**真 img** ——
       继续数 '.collab img' 的话，座舱页会从 0 变成 1，下面那条"这一格是空的"
       当场**假红**（红的是判据，不是页面）。按 `.collab-logo` 数才是
       "院徽只有封面有"这条判据的本意。
       ⚠️ chrome.js 里那段注释早就写着"B2 段数是 .collab-logo"—— 那是**它写错了**，
          代码从 2026-09-24 起一直是 .collab img。当时头像不在，两种写法等价，
          所以没人发现；这一版把两边对齐了（改的是代码，不是注释）。 */
    collabImgs: document.querySelectorAll('.collab-logo').length,
    /* ★ 2026-09-25 晚：右上角那个用户入口。座舱页有、封面没有 ——
       和院徽正好相反，两拨共用一个 .collab 格（见 chrome.js 的 clockHTML）。 */
    tbUser: document.querySelectorAll('.tb-user').length,
    tbName: txt('.tb-user .tb-name'),
    tbAva: img('.tb-user .tb-ava'),
    tbBtnTag: (function(){ const b = document.getElementById('tbUserBtn');
                           return b ? b.tagName.toLowerCase() : null; })(),
    tbMenuHidden: (function(){ const m = document.getElementById('tbUserMenu');
                               return m ? !!m.hidden : null; })(),
    /* ★★ 2026-09-25 晚：**位置**和**遮挡**。这两条是被用户当场抓出来的两个
       真 bug，而它们**只判"元素在不在"是一条都抓不到的**（B3 原来就是那样，
       所以两个 bug 全都溜过去了）：
         · 位置：`.collab` 没写 `grid-column` 时它落进中间那列，胶囊跑到
           **屏幕正中**（用户：「最右边啊 你放到中间干嘛」）；
         · 遮挡：浅色主题 `.topbar` 上那条 backdrop-filter 给它造了个层叠
           上下文，整条顶栏连同弹出来的个人档都被后面的 `.main` 盖住
           （用户：「展开后为啥小瑞头像挡住了」）。
       ⚠️ 量位置量的是 `.tb-user`（**那颗胶囊**），不是 `.collab` ——
          `.collab` 是 1fr 的格子，盒子本来就占右半屏，拿它判"在不在中间"
          必然假红（我自己第一版就写错了，见 _scratch/_tmp/_chk_topbar_right.py）。
       ⚠️ 遮挡必须**先把菜单临时展开**再采样，采完立刻还原 —— 菜单默认是
          `hidden` 的，收着的时候 `elementFromPoint` 一个菜单里的点都取不到，
          那样判据会**恒真**（永远"没被盖住"）。恒真的判据比没有更坏。 */
    tbRightGap: (function(){ const u = document.getElementById('tbUserBtn');
      if (!u) return null;
      return Math.round(window.innerWidth - u.getBoundingClientRect().right); })(),
    tbMenuOccl: (function(){
      const m = document.getElementById('tbUserMenu');
      if (!m) return null;
      const was = m.hidden;
      m.hidden = false;
      const b = m.getBoundingClientRect();
      let n = 0; const who = [];
      for (let i = 1; i <= 6; i++) {
        for (let j = 1; j <= 4; j++) {
          const x = Math.round(b.left + b.width * i / 7);
          const y = Math.round(b.top + b.height * j / 5);
          const e = document.elementFromPoint(x, y);
          if (!e || !m.contains(e)) {
            n++;
            if (who.length < 3 && e) {
              who.push(e.tagName.toLowerCase() + (e.id ? '#' + e.id : '')
                       + (e.className ? '.' + String(e.className).split(' ')[0] : ''));
            }
          }
        }
      }
      m.hidden = was;
      return { n: n, who: who };
    })(),
    /* ═══ 封面上「技术数字」全清 ═══
       用户点名的：「严禁出现帧数、识别类别、延迟等任何技术测试数字」。
       ⚠️ 判据是**扫正文**，不是查那几个容器在不在 —— 查容器的话，
          数字被搬去页脚、或被别处重新写进去，判据都照样绿。
          下面这几个词就是"技术数字"的可检索形态（四个数各自的特征词）。 */
    coverTechWords: ['帧', '延迟', '识别', '回归', '4 类', '45', '121', '3.7']
      .filter(w => (document.body.innerText || '').indexOf(w) >= 0),
    coverLede: document.querySelectorAll('.cover-lede').length,
    coverMeta: document.querySelectorAll('.cover-meta').length,
    /* 浅色底图上那层洗白（`.bg::after`）在不在、长什么样。
       ⚠️ 这个键原来叫 `skylineLayer`（量的是一层手搭的天际线），2026-09-24 晚
          跟着 J 段一起改名 —— 现在量的是"洗白层"，和天际线没关系了。 */
    bgLayer: (() => {
      const e = document.querySelector('.bg');
      if (!e) return null;
      const s = getComputedStyle(e, '::after');
      return { content: s.content, bg: s.backgroundImage || '' };
    })(),
    /* ★ 2026-09-24：这里原有 4 个天气/联网探针（`wx` / `net` / `wxHTML` /
       `barsLit`），随 E 段一起删。见文件头。 */
    /* ★ 2026-09-24 这里原来有 6 个 key，全是 nav.html 那张路线图的浅色配色探针：
         roadStroke / carFill / carStroke / pinFill / pinHeadFill / mapDarkFills
       —— 它们撑着 F 段那整段判据（路是墨蓝不是白、车标的芯 == `--on-accent`、
       环和终点 pin == `--accent`、水滴头 == `--accent`、以及"地图卡里不许有近黑
       填色"的兜底扫描）。**nav 整页删除，那张图不存在了，所以这一整组一起删。**
       ⚠️ 这不是"少验了几条"，是**验的对象没了**；那张图的浅色配色现在全库
          没有任何断言，别再去找替代品 —— 没有替代品。
       ⚠️ 顺带记一条当时踩出来的教训（比这几行代码值钱）：`mapDarkFills` 那条
          **兜底扫描**抓到了「按元素点名」的判据全都抓不到的 bug —— 终点水滴头
          写死 `fill="#06202A"`，深色下是钉子、浅色下是一块黑斑，而那些点名的
          判据一条都碰不到它（它当时连类名都没有）。
          以后做同类"换主题"的活，**点名判据之外要留一条不点名的兜底扫描**。 */
  };
})())
"""


# ★ 2026-09-24：这里原来有 `is_num_temp()` 和 `wait_wx()` 两个函数，
#   一个抠温度、一个轮询等天气那次 fetch 落定。天气整块删掉之后它们没有调用者了
#   （全文件 grep 确认），**一起删**。
#   ⚠️ 连带 `import re` 也删了 —— 全文件只有 `is_num_temp` 用 `re`。


async def main():
    SHOTS.mkdir(parents=True, exist_ok=True)
    fails = []

    def ck(ok, label, detail=""):
        print(("  OK  " if ok else "  !!  ") + label + (("  — " + str(detail)) if detail else ""))
        if not ok:
            fails.append(label)

    async with Session(CDP) as S:
        await S.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": 1672, "height": 940, "deviceScaleFactor": 1,
                     "mobile": False})
        await S.cmd("Emulation.setEmulatedMedia",
                    {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        await S.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": WS_STUB})

        got = {}
        for name, path, _want_theme in PAGES:
            await S.goto(path, 2.2)
            # ★ 2026-09-24：这里原来还有「这一页要不要等天气」那一步，
            #   随天气那一组删了（PAGES 也从四元组变回三元组）。
            await S.js(FREEZE)
            await asyncio.sleep(0.4)
            got[name] = await S.js(PROBE)
            r = await S.cmd("Page.captureScreenshot", {"format": "png"})
            import base64
            (SHOTS / ("theme2_%s.png" % name)).write_bytes(
                base64.b64decode(r["data"]))
            print("  截图 _shots/theme2_%s.png" % name)

    print("\n" + "=" * 68)
    print("A0. chrome.js 真的干了活（**不能靠控制台零报错、也不能靠 typeof**）")
    for name, d in got.items():
        ck(d["build"]["clock"].startswith("OK"), "%s clockHTML() 真调得动且内容齐" % name,
           d["build"]["clock"])
        ck(d["build"]["rail"].startswith("OK"), "%s railHTML() 真调得动且内容齐" % name,
           d["build"]["rail"])
        # ★ 2026-09-24：这里原来还有一条「XQ.env.init 是函数」，随天气那一组删了。
        # ⚠️ 换上来的这一条（传 logo:true 的院徽分支）**性质不同**：原来那条是
        # "旧东西删干净了吗"，这条是"新分支真的接上了吗" —— 两者都要有，
        # 但别把这条也当成"删除类"判据。
        ck(d["build"]["clockLogo"].startswith("OK"),
           "%s clockHTML({logo:true}) 吐出两张院徽" % name, d["build"]["clockLogo"])
        # ★ 2026-09-25 晚：封面那条分支不许带用户入口（两拨共用一个 .collab 格，
        # 只能二选一）。这条是 probeAbsent，**看的是"多了不该有的"**，
        # 和上面那条"缺了该有的"是两回事 —— 别把它读成同一条。
        ck(d["build"]["clockLogoNoUser"].startswith("OK"),
           "%s 封面那条分支里没有用户入口（院徽与它二选一）" % name,
           d["build"]["clockLogoNoUser"])
        ck(d["topbarFilled"], "%s 顶栏真的被填上了" % name)

    print("\nA. 主题真的生效（读的是计算值，不是 HTML 属性）")
    for name, d in got.items():
        want_theme = EXPECT[name]
        ck(d["theme"] == want_theme, "%s html[data-theme]" % name,
           "%r (要 %r)" % (d["theme"], want_theme))
        want = WANT_LIGHT if want_theme == "light" else WANT_DARK
        for k, v in want.items():
            ck(d["vars"][k] == v, "%s %s" % (name, k),
               "%r (要 %r)" % (d["vars"][k], v))

    print("\nB. 标志换对了（两张图都在 DOM 里，CSS 二选一）")
    for name, d in got.items():
        # ⚠️ 这两条**必须跟着该页的期望主题走**，不能无条件要求"浅色版显示"：
        #    深色页（design.html）要的正好是反过来的那个。2026-09-24 扩页时
        #    就是这里先报了两条假红 —— 判据写死了"浅色"这个前提。
        if EXPECT[name] == "light":
            show, hide = "onLight", "onDark"
        else:
            show, hide = "onDark", "onLight"
        ck(d[hide]["display"] == "none", "%s %s 版被藏掉" % (name, hide),
           d[hide]["display"])
        ck(d[show]["display"] != "none", "%s %s 版显示" % (name, show),
           d[show]["display"])
        # 两张图**都要真的加载出来**（只在 DOM 里、src 却没拿到是不算的）：
        # 藏起来那张也得是真图，否则下次把主题翻过来就是一张空框。
        ck(d[show]["naturalWidth"] > 0, "%s %s 版真加载出来了" % (name, show),
           d[show]["naturalWidth"])
        ck(d[hide]["naturalWidth"] > 0, "%s %s 版也是真图（只是被藏着）" % (name, hide),
           d[hide]["naturalWidth"])
        ck("lingtu_lockup_ink" in d["onLight"]["src"], "%s 浅色版是 ink 那张" % name,
           d["onLight"]["src"])
        ck("lingtu_lockup_ink" not in d["onDark"]["src"], "%s 深色版不是 ink 那张" % name,
           d["onDark"]["src"])
        # ★ 2026-09-24 晚：这两条原来是读 `.lingtu-txt b/em` 的**真文字**。
        #   那两行字现在在图里（用户：「直接整张图替换…」），DOM 上没有文字可读了，
        #   所以判据换成读 alt —— 它是唯一还能在 DOM 上问"这张图是什么"的地方。
        #   ⚠️ **不要把它降级成"alt 非空"**：那对"图换成院徽了"照样是绿的。
        #      这里咬着"灵途智行"这四个字，换错图才会红。
        ck(d["brandAlt"] == "灵途智行 · 与你同行", "%s 品牌图 alt 写的是品牌名" % name,
           repr(d["brandAlt"]))
        # ★ 2026-09-25 反转：用户「**里边那个灵途的标不用放了**」——
        #   主视觉卡片左上角那个 lockup（`.dash-brand`）连同 DOM 和 CSS 一起删了，
        #   所以这条判据从"图必须对"翻成"**必须没有**"。
        #   ⚠️ 为什么必须改、不能留着：原来那条带 `if not missing` 护栏
        #      （`.dash-brand` 只有 index.html 有），元素一删**护栏就把整条判据吞了** ——
        #      它不会红、也不会报错，就是**再也没验过任何东西**。这个仓库里
        #      "看着绿、其实什么都没验"是踩过的坑（见下面 H 段那段说明），
        #      所以两个方向都要咬：现在是"这一格必须空"。
        #   ⚠️ 顶栏那个 lockup 仍然由 B 段（`brandAlt`）和 `_check_mascot.py` 盯着，
        #      这条只删的是主视觉卡片里那一处。
        ck(bool(d["brandLockup"].get("missing")),
           "%s 主视觉卡片里那个 lockup 已经删掉了" % name,
           d["brandLockup"].get("src"))
        ck(d["vline"] == 0, "%s 那道竖线没了" % name, d["vline"])
        ck(not d["cheryInTopbar"], "%s 顶栏没有 CHERY 了" % name)

    print("\nB2. 顶栏右上角：旧那一组删干净、新那一格只封面有院徽")
    for name, d in got.items():
        # (1) 旧的整组删掉了 —— 查 null 不查可见性（"藏起来"不算删）
        ck(d["envEl"] == 0, "%s 顶栏没有 .env 那一组了" % name, d["envEl"])
        # (2) 新那一格在（空着也得在：它是 1fr 的定位格，删了顶栏中线会漂）
        ck(d["collabEl"] == 1, "%s 有且只有一个 .collab 格" % name, d["collabEl"])
        # (3) 院徽**只有封面有**，其余 10 页是空的 —— 这两条必须都判，
        #     只判"封面有图"的话，有人把 logo:true 抄进全站也照样绿。
        if name == "cover":
            ck(d["collabImgs"] == 2, "%s 封面那一格是两张院徽（深/浅各一张）" % name,
               d["collabImgs"])
            # 走 B 段同一套逻辑：浅色主题显 on-light、藏 on-dark
            ck(d["collabLight"].get("display") not in (None, "none"),
               "%s 院徽浅色版显示" % name, d["collabLight"].get("display"))
            ck(d["collabDark"].get("display") == "none", "%s 院徽深色版被藏掉" % name,
               d["collabDark"].get("display"))
            # 藏起来那张也必须是**真图**，否则哪天主题翻过来就是一张空框
            ck(d["collabLight"].get("naturalWidth", 0) > 0,
               "%s 院徽浅色版真加载出来了" % name, d["collabLight"].get("naturalWidth"))
            ck(d["collabDark"].get("naturalWidth", 0) > 0,
               "%s 院徽深色版也是真图（只是被藏着）" % name,
               d["collabDark"].get("naturalWidth"))
            ck("tongji_logo_ink" in (d["collabLight"].get("src") or ""),
               "%s 浅色那张是 _ink 命名" % name, d["collabLight"].get("src"))
            ck("tongji_logo_ink" not in (d["collabDark"].get("src") or ""),
               "%s 深色那张不是 _ink" % name, d["collabDark"].get("src"))
        else:
            ck(d["collabImgs"] == 0, "%s 除了封面，这一格没有院徽" % name,
               d["collabImgs"])

    print("\nB3. 顶栏右上角：用户入口（座舱页有、封面没有 —— 和院徽正好相反）")
    for name, d in got.items():
        if name == "cover":
            ck(d["tbUser"] == 0, "封面那一格放的是院徽，没有用户入口", d["tbUser"])
            continue
        # (1) 真的在。**空着不算数** —— 所以下面几条一起判，不是只看元素数。
        ck(d["tbUser"] == 1, "%s 右上角有且只有一个用户入口" % name, d["tbUser"])
        # 下面两条是这一格的**内容判据**，不是版式判据：头像得是真照片
        # （上一版"管理员"画的是内联 SVG 人形，所以这里必须量 naturalWidth ——
        # 一个 src 写错但元素还在的头像，只数元素是看不出来的）。
        ck(d["tbAva"].get("naturalWidth", 0) > 0,
           "%s 用户头像真的加载出来了（不是空框）" % name, d["tbAva"])
        ck("user_avatar" in (d["tbAva"].get("src") or ""),
           "%s 头像引的是用户本人那张 user_avatar.jpg" % name,
           d["tbAva"].get("src"))
        ck(bool(d["tbName"]), "%s 名字那行有字" % name, d["tbName"])
        # (2) 它必须是个**真 button**。上一版被否掉的理由就是"点不动的假控件"，
        #     所以这条钉的是"能不能点"，不只是"长没长出来"。
        ck(d["tbBtnTag"] == "button", "%s 那个入口是真 button（点得动）" % name,
           d["tbBtnTag"])
        # (3) 下拉默认关着。判 hidden 这个**属性**，不判可见性 ——
        #     它是 JS 在控的（XQ.userMenu），判可见性就等于把 CSS 当开关。
        ck(d["tbMenuHidden"] is True, "%s 个人档默认是收起的" % name,
           d["tbMenuHidden"])
        # (4) ★ 位置：胶囊必须贴在最右边。阈值 40px = 顶栏 padding(1.6rem≈24px)
        #     再留一点余量；跑到中间的话这个数会是几百。
        #     **这条抓的是"没写 grid-column 就落进中间那列"**那个真 bug。
        ck(d["tbRightGap"] is not None and d["tbRightGap"] <= 40,
           "%s 用户胶囊贴在最右边（离右边缘 %s px，要 ≤40）" % (name, d["tbRightGap"]),
           d["tbRightGap"])
        # (5) ★ 遮挡：展开之后不能被页面内容盖住。
        #     **这条抓的是"顶栏被 backdrop-filter 造了层叠上下文、整条被 .main
        #     压在下面"**那个真 bug —— 小瑞立绘盖住个人档就是它的症状。
        occl = d["tbMenuOccl"] or {}
        ck(occl.get("n") == 0,
           "%s 展开的个人档没有被页面内容盖住" % name,
           "被 %s 个采样点盖住，最上面是 %s" % (occl.get("n"), occl.get("who")))

    print("\nC. 左下角 CHERY **保留**（用户：左下角不去除）")
    for name, d in got.items():
        if name == "cover":
            continue          # 封面把整条 rail 藏了，这一页本来就看不到
        ck("chery_mark" in d["railFootMark"].get("src", ""),
           "%s rail-foot 还是 chery_mark.png" % name, d["railFootMark"].get("src"))
        ck(d["railFootName"] == "CHERY", "%s rail-foot 还是 CHERY" % name,
           d["railFootName"])

    print("\nD. 删干净的东西（查 null，不是查可见性）")
    for name, d in got.items():
        ck(d["climateEl"] == 0, "%s 没有 .climate 元素了" % name, d["climateEl"])
        ck(d["climateFn"] == "undefined", "%s XQ.climateHTML 不存在了" % name,
           d["climateFn"])
    # ★ 2026-09-24：这里原有三条 nav 专属（.unwired 说明 / .ptitle .pill 徽标 /
    #   #destNote 目的地计数），随 nav.html 一并删除。见文件头那段。
    #   ⚠️ 2026-09-25 新 nav.html 回来了，但**这三条依然不复活** —— 新页上没有
    #      那三样东西，见探针里那段注释。这里只多一条：新页也得是浅色（PAGES 管）。
    ck(got["cover"]["coverSub"] == 0, "cover 那段 .sub 说明文没了",
       got["cover"]["coverSub"])
    ck(got["cover"]["coverTags"] == 0, "cover 页脚那排 tags 没了",
       got["cover"]["coverTags"])
    ck(not got["cover"]["bodyHasQirui"],
       "cover 整页正文里没有「奇瑞」了", got["cover"]["bodyHasQirui"])
    # ★ 2026-09-24（照 13.png 第三次改版）：这条原来盯的是眉标胶囊里的品牌名
    #   （「灵途智行 · 小瑞情感化驾驶员监测系统」）。**眉标整块删了**，
    #   换成盯**新加的副标题**，并且要保住原来那条判据的性质 —— **两个方向都咬**：
    #     · 副标题被删掉 / 清成空串 → 空串，红（原来"眉标没了"也是红）；
    #     · 那行字被改成别的（尤其写回旧的「分心 / 疲劳驾驶实时检测系统」）→ 红。
    #   ⚠️ 品牌那条（"别挂奇瑞"）**没有丢**：上面 `bodyHasQirui` 管整页正文，
    #      顶栏那几条管标志组。副标题里本来就不出现品牌名，
    #      硬要它 startswith("灵途智行") 就是写一条**恒假**的判据。
    sub_line = (got["cover"]["coverSubLine"] or "").strip()
    ck(sub_line.endswith("情感化智能座舱驾驶员健康监测预警系统") and len(sub_line) > 8,
       "cover 副标题是那句系统名（不是旧的技术名、也不是空的）", sub_line)

    print("\nH. 封面按 13.png 版式清干净（用户：严禁技术测试数字 / 下方无多余文字）")
    for name, d in got.items():
        # 顶栏的时间日期 —— 用户点名「不要在页面顶部放置时间日期」，全站
        ck(d["clockEl"] == 0, "%s 没有 .clock 元素了" % name, d["clockEl"])
        ck(not d["hhmm"], "%s 没有 #hhmm 元素了" % name, d["hhmm"])
        ck(d["build"].get("tickClock") == "undefined",
           "%s XQ.tickClock 整个删掉了（不是藏起来）" % name,
           d["build"].get("tickClock"))
        # ★ 2026-09-24：原来这里还有一条「右上角那个装饰性人头像没了」，
        #   查的是 `.env > svg` 里的人形 —— `.env` 整个删掉之后那条**恒真**，
        #   成了"看着绿、其实什么都没验"。它的职责已由 B2 段接手
        #   （`envEl == 0` 比"没有那个人头像"强：整组都在才算没了吗）。
    ck(got["cover"]["coverLede"] == 0, "cover 那行技术名没了", got["cover"]["coverLede"])
    ck(got["cover"]["coverMeta"] == 0, "cover 那排数字没了", got["cover"]["coverMeta"])
    # ★ 扫正文找技术数字：查容器是不够的（数字搬个地方判据就瞎了）
    ck(not got["cover"]["coverTechWords"], "cover 正文里一个技术数字都不剩了",
       got["cover"]["coverTechWords"])
    # ★ 2026-09-25：期望值换成**缩短后**的那一行。用户原话：「顶部标题重复：
    #   大字已经写了『情感化智能座舱驾驶员健康监测预警系统』，顶部小字可以精简…
    #   顶部改成简短一行：情感化智能座舱 | 驾驶员健康监测预警」。
    #   顶栏那行只有 1.06rem（style.css 的 .tbtitle），左栏 `.cover-sub` 才是
    #   1.75rem 的"大字"—— 用户要消掉的重复在**顶栏这一处**。
    #   ⚠️ 这条**仍然是全等比对**，别顺手放松成 `in` / `startswith`：
    #      它要咬的就是"顶栏到底写了什么"，一放松，把整句原样写回去也会是绿的。
    #   ⚠️ 上面 F 段那条 `sub_line.endswith(...)` 盯的是 `.cover-sub`（大字那行），
    #      **一个字都没改，不许改** —— 改了就变成"用错误去迁就改动"。
    ck(got["cover"]["tbTitle"] == "情感化智能座舱 | 驾驶员健康监测预警",
       "cover 顶栏中间是项目主题文字（缩短版）", got["cover"]["tbTitle"])
    # 座舱页**故意不挂**标题：那一页自己已经有页面标题，顶栏再来一行是重复
    # ★ 2026-09-24：这条原来拿 `nav` 当靶子，nav.html 删了 → 改指 `index`。
    #   ⚠️ **是换靶子不是删判据**：它验的规矩（座舱页顶栏中间留空）是全站性的，
    #      只要还有座舱页就该验。index 是最典型的那一页（它是最先打开的）。
    ck(not (got["index"]["tbTitle"] or "").strip(),
       "index 顶栏中间是空的（那一页自己已有页面标题）", got["index"]["tbTitle"])

    # ★ 2026-09-24：这里原来是 **I 整段** —— 顶栏右上角那个「小瑞语音」状态标识
    #   的三条判据（有内容 / 不出现含糊的「在线」/ 带 tooltip）。
    #   用户「整块 env 全去掉，连语音标识也去」，那个标识和 `XQ.tts.paintTopbar()`
    #   一起删了，所以**这一段整段删掉**。
    #   ⚠️ **它当年想表达的那条规矩没有作废，只是没有落点了**：
    #      浏览器语音合成的"在线"至少混了三件事 —— supported（浏览器支不支持）、
    #      on（用户按没按静音）、voice.localService（本机合成还是云端神经音色）；
    #      其中 localService 为真的音色**断网也能出声**，标成「在线」正好把真相说反。
    #      所以那儿宁可写「本地」也不写「在线」。
    #   ⚠️ 这套逻辑在**左导航那张说明牌**上还活着（`XQ.tts.voiceDesc()` 的
    #      「（本地）/（在线）」+ `#voiceNote`），所以它没有失去全部覆盖 ——
    #      但本脚本**没有**为它补判据（那句话是"中文/本地/在线"拼起来的自由文本，
    #      硬判会很脆）。要验它得人眼看一眼左导航。

    # ★ 2026-09-24 晚：J 段原来验的是**手搭的那层天际线**（`.bg::after` 里引
    #   `skyline.svg` + 一层 blur）—— 第四次改版换 `背景.png` 之后那一整层
    #   **连 CSS 一起删了**（见 style.css「背景三层」那段：
    #   「原来那一大套……整块作废 —— 现在底下是一张真照片，再叠那些手画的楼
    #     就是两座城市打架」）。所以那三条恒假，量的对象已经不在库里了。
    #   换成现在真正该咬住的那条分界：**洗白层只有座舱内那几页有、封面没有**。
    #   两个方向都有话说：封面沾上洗白层 → 封面那张照片被洗成一片雾（封面要的
    #   就是照片本身）；座舱页丢了洗白层 → 白卡片直接压在城市的楼和路上，
    #   卡片边缘一圈花。**所以必须两边都验**，只验一边的话"洗白层整个没了"
    #   和"洗白层到处都在"这两种错各能躲过一半。
    print("\nJ. 浅色底图那层洗白：**只有座舱内那几页有，封面没有**")
    sky = got["cover"]["bgLayer"]
    ck(sky and sky["content"] in (None, "none"),
       "cover 没有洗白层（封面要的就是照片本身）", sky and sky["content"])
    inn = got["index"]["bgLayer"]
    ck(inn and inn["content"] not in (None, "none"),
       "index 有洗白层（白卡片压在照片上要靠它）", inn and inn["content"])
    ck(inn and "linear-gradient" in (inn["bg"] or ""),
       "index 那层是半透明白的渐变", (inn and inn["bg"] or "")[:60])

    # ★ 2026-09-24：这里原来是 **E 整段** —— 「天气 / 联网是**真值**」，
    #   本脚本唯一一条依赖外网的判据。顶栏那一组被用户要求去掉之后，
    #   它验的对象**不存在了**，所以整段删掉（连带 wait_wx / is_num_temp /
    #   4 个探针键 / WX_PAGES）。理由见文件头那段。
    #
    #   ⚠️ 这一段里有一条**比代码值钱的教训**，记在这儿别丢：
    #      「在线却报『取不到』= 探测逻辑坏了」这条判据当年抓到一个真 bug ——
    #      定位/取天气用了 Promise.race，HTTP 下 ip-api 被**混合内容**立刻拦掉，
    #      竞速当场带着 null 返回，于是"明明能上网却报离线 + 取不到"。
    #      以后任何"多源竞速取第一个 settle 的"写法都要记得：
    #      **settle 不等于成功**，被立刻拒绝的那一路会把成功路径一起带走。


    # ★ 2026-09-24：这里原来是 **F 整段**（约 50 行）—— nav.html 那张路线图的
    #   浅色配色判据，全部随 nav.html 一起删掉：
    #     · 「底图那几条路是墨蓝系（不是白）」
    #     · 「车标的芯 == --on-accent」「车标的环 == --accent」
    #     · 「终点 pin == --accent」「终点水滴的头 == --accent」
    #     · 「车标的环和芯不是同一个色」（兜底）
    #     · 「地图卡里没有近黑的 fill/stroke」（兜底扫描）
    #   连带删掉的还有这段里的两个局部函数 `rgb()` / `is_bluish()`
    #   —— 全库只有这一段在用它们（已 grep 确认），留着就是两个死函数。
    #
    #   ⚠️ **这一段没有替代物，别再去找。** 它验的是一张已经不在的图。
    #   ⚠️ 但当时从这段里得到的两条经验仍然值钱，记在这儿：
    #     1) 「点名判据 + 一条不点名的兜底扫描」这个组合抓到过一个真 bug：
    #        终点那个水滴头写死 `fill="#06202A"`，深色下是钉子、浅色下是一块黑斑，
    #        而所有**按类名点名**的判据一条都没碰到它（它当时连类名都没有）。
    #        以后再做"换主题"的活，兜底扫描不能省。
    #     2) 判据写"某个色值"不如写"颜色归属"：原来要求「车标的芯是墨蓝系」
    #        实测假红（车标的设计就是"强调色环 + 底色芯"，浅色下芯本该是白）。
    #        改成「芯 == --on-accent、环 == --accent」之后，验的是它跟谁走，
    #        换配色也不会误报。

    print("\nK. 四档色的**两份拷贝**真的落到采样格上了（★ 2026-09-24 晚新增）")
    # 背景：`--sev-*` 定义在 `:root`（A 段验的是它），但 design.html 那四格样本
    # 和 phone.html 那四台手机**各自又写了一遍字面量**（都在页内 <style> 里）。
    # A 段读 documentElement，**碰不到这两份拷贝** —— 改色改一半、抄错一个十六进制、
    # 漏抄一格，A 段全绿而页面上那一格是错的。所以这一段单独从容器上读 --accent。
    # ⚠️ 为什么它们非得各写一份、不能用 `var(--sev-*)`：见 phone.html 页内 <style>
    #    那段长注释（`<html data-theme="light">` 上那些变量会解析成**浅色**那一套，
    #    而手机屏是钉死的深色孤岛）。同理，design.html 那四格要的是**深色**那套，
    #    但它自己那一页恰好就是深色（没写 data-theme），所以理论上能引用 ——
    #    实际仍是字面量，理由写在 design.html 那段注释里。
    # ★ 2026-09-24 深夜：「只做疲劳」之后两处**都是四档、键名也相同**
    #   （`normal/mild/moderate/severe`）。原先只有 design 四格、phone 三格、
    #   而且 phone 那三格是"疲劳程度"那另一条轴 —— 那段注释连同那三条断言一起删了。
    #   现在两处**同键同值**，所以下面两段长得几乎一样，那不是复制粘贴没改。
    dsn = got["design"]["sevSamples"]
    # 四档一格都不能少：少一格 = 那一档的样本没有色（`--accent` 落回 :root 的值），
    # 页面上看着像"设计稿里就那一格是灰的"，很容易被当成有意为之。
    ck(set(dsn) == {"normal", "mild", "moderate", "severe"},
       "design 四格样本的 data-sev 是四档",
       "拿到 %s" % sorted(dsn))
    for k in ("normal", "mild", "moderate", "severe"):
        ck(dsn.get(k) == WANT_DARK["--sev-" + k],
           "design .sev-s[data-sev=%s] 的 --accent" % k,
           "%r（要 %r）" % (dsn.get(k), WANT_DARK["--sev-" + k]))
    # 四格互不相同 —— 上面那四条已经逐格比过值，这条是**兜底**：
    # 万一哪天有人把 WANT_DARK 也一起改错（比如四个都抄成同一个），
    # 逐格比会跟着一起绿。这里只问"它们是不是四个不同的色"。
    ck(len(set(dsn.values())) == 4, "design 四格是四个不同的色",
       " -> ".join("%s=%s" % (k, dsn.get(k)) for k in sorted(dsn)))

    ph = got["phone"]["phoneSamples"]
    # phone.html 现在是**四台手机**（补上中度那档），键名和 design 那四格一致。
    # ⚠️ 这里**不再有**"三格 / 另一条轴"的说法：那是 09-24 晚间两轴分立时的形态，
    #    深夜合轴之后作废。别照着旧记录把断言改回三键 —— 页面上真的是四台。
    ck(set(ph) == {"normal", "mild", "moderate", "severe"},
       "phone 四台手机的 data-sev 是四档",
       "拿到 %s" % sorted(ph))
    for k in ("normal", "mild", "moderate", "severe"):
        ck(ph.get(k) == WANT_DARK["--sev-" + k],
           "phone .phone[data-sev=%s] 的 --accent" % k,
           "%r（要 %r）" % (ph.get(k), WANT_DARK["--sev-" + k]))

    print("\nG. 控制台零报错")
    ck(not S.errs, "无 error / warning", S.errs[:4])

    print("\n" + "=" * 68)
    print("**%d 项不过，见上**" % len(fails) if fails
          else "**全绿**（截图仍要人眼看：亮色调对不对味、标志大小合不合适）")
    return fails


if __name__ == "__main__":
    # ⚠️ 退出码**必须**反映结果。这个脚本原先跑到最后一行就结束了，
    # 失败也是 exit 0 —— 和这个项目里 `_check_regression` 那条老毛病一样：
    # **退出码不可信的时候，只能靠人肉读输出行**，而人肉读是会漏的。
    # 现在改成：有不过的就 exit 1。但**读输出行的纪律不变**
    # （exit 0 只说明"没抓到已知问题"，不说明"这两页好看"）。
    _fails = asyncio.run(main())
    sys.exit(1 if _fails else 0)
