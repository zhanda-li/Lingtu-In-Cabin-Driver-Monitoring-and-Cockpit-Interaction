"""验「只做疲劳」之后，**四个档位在真 DOM 上真的成立** —— 以及「分心」确实没了。

    D:\\Anaconda3\\envs\\dms\\python.exe ui\\server.py --port 8790 --source demo
    python _scratch/_check_grade.py 8790

## 为什么单独一个脚本

这次改动的口号是「后端只做疲劳」，落到屏幕上就是**四档**：
清醒 / 轻度疲劳 / 中度疲劳 / 重度疲劳。四档的名字同时出现在**服务端**
（`ui/state.py` 的 `SEVERITY_NAMES`）、**页面**（大标题 `#sevName`、
**顶部那根疲劳程度条** `#barLevel`）、**配色**（`--accent` / `data-sev`）、
**小瑞的表情**（`live.js` 的 MAP）和**语音**（`ui/xiaorui.py` 的 SCRIPT）五处。
五处里任何一处少一档、或者还留着上一版的键名，屏上就会是
"大标题说中度、配色还是橙的上一套"这种东西 ——
**它不报错、不崩、控制台一个字都没有**，只有人眼看着别扭。

⚠️ 和另外三个脚本的分工（别在它们之间重复断言，也别以为这里没写就是没人验）：
  · 四档**颜色**（`--sev-*` 的值、浅色/深色两套）→ `_check_theme2.py` 的 A/K 段；
  · 四档**表情**（小瑞换成哪张图）→ `_check_mascot.py` 的 F 段；
  · 两条**独立告警**的报与收 → `_check_alarm.py` 的 B/C/D 段；
  · 四档**档位本身**（下面 A 段）+ 全站**再没有"分心"**（B 段）→ 本脚本。
    另外 D 段把"轻度必须来自支路二"这件事在屏幕上钉一次（`_check_alarm.py`
    的 E 段验的是同一件事的另一半：那一档上支路一的概率条）。

## 判据

  A. 六个 `?sev=` 写法 -> `data-sev` + 大标题 + 头姿 + **疲劳程度条的宽度**。
     其中 `phone` / `fatigue` / `severe` **三个都该是重度疲劳**
     （头部持续低垂 / 疲劳点头 / 别名）。
  B. 12 页的**可见文字**里都没有「分心」。
     ★ 2026-09-25：这里原来有一条豁免 —— flow.html 末尾那节引的模块 3 原文
     （「YOLOv8n 分心物体检测」）按 `ALLOW` 白名单抠掉再扫。那一节被用户删了
     （「把这个去了」），**豁免连同 ALLOW 一起撤掉**：现在 12 页上「分心」一处
     都不许有，没有例外了。
  C. **监测详情页**上支路一概率条**恰好两行**、加起来 ≈100%（漏一类的话和就
     不是 100），而且**旧标签「低头看手机」不许再当类别名用**。
     ★ 2026-09-25：原来这里留了一个例外（"只许出现在右栏「系统公告」那条改版史
     里"），**例外随那张卡一起没了**（用户把那整块开发日志删了，见 C 段注释）。
     现在判据是硬的：**首页一处都不许出现**。
  D. 轻度那一格的来源：支路一在那档仍判「正常」（在监测详情页上拨时钟量），
     而首页拨到哈欠桥段时横幅确实报「检测到打哈欠」、档位**还是**轻度疲劳。
  F. （2026-09-25 重写）支路二那一块：**一个真数** `#fPFat` + 一条 `#fPFatBar`，
     条宽和文字是同一个数；热身没完时是「—」不是 0%；
     以及**首页那张卡在 1920x1080 下装得下**（没被裁）。
  E. 全程零控制台报错。（写在文件最后 —— 它读的是整场攒下来的报错。）

⚠️ 这个脚本**证明不了**：配色好不好看、语音念得好不好听（人眼人耳的事）。

★ 2026-09-24 深夜改过什么（不是脚本坏了，是**屏幕上的东西变了**）：
  · `#rLevel`（卡片里「疲劳程度」那一行）**元素已经不存在** —— 那一行并进了顶部
    （文字和大标题同源、多余；条留在 `#barLevel`）。原来那条"别接回 level_name"
    的钉子**换了靶子**：现在读**条的宽度**（`DEG_W[severity]`），比读那行字更硬。
  · 两块概率条（`#p4` 支路一 / `#p5` 支路二）**共用 `.p4-row`** —— 所以取行
    不能光写 `.p4-row`（那时会拿到 4 行，C 段的"恰好两行"会红）。
    ⚠️ 当时加的是 `#p4` 前缀，**那两个 id 现在都没有了**（见文件末尾那段），
       现役写法是 `[data-tab="behav"] .p4 .p4-row`。
  · 支路一的行数和标签都变了（正常头部姿态 / 疲劳（低头·点头））
    —— 所以 C 段按**类别 id** 取数，不按行号。

★ 2026-09-25 二类改过什么：
  · 支路一从三类并成**二类**（`phone` 的 26 段并进 `fatigue`，见 `config.py`
    那段注释与 `tools/build_dataset.py` 的 `DIR_CLASS`）：`#pPhone` 那一行
    **从 index.html 整行删掉了**，所以 `pb` 只剩两键、C 段只剩两行。
  · 「头姿」这一列**换算法了**：它原来读支路一的概率（`P(phone)` → 低头、
    `P(fatigue)` → 点头），现在**只读行为量**（`ui/state.py` 的 `attention`：
    `d_pitch` = 窗内 pitch 的 p95−p5，`nod` = 窗口里低头片段数）。
    ⚠️ EXPECT 第 4 列那六个词是 `#rPose` 的**屏上字面**
    （`app.js:322` 的 `POSE_OF`：疲劳点头→点头、头部持续低垂→低头、
    略有低头→略低头），**不是** `attention` 自己的四个词
    （专注/略有低头/头部持续低垂/疲劳点头）。这条链子是
    `attention` → `POSE_OF` → 屏上，所以改 `HEAD_RANGE` / `NOD_BUSY`
    会改这一列，改 `POSE_OF` 也会 —— 这正是这条钉子要咬的地方。

★ 2026-09-25 第六次改版之后改过什么（同样是**屏幕变了**，不是脚本坏了）：
  · 支路一/二的概率条**从首页搬去了驾驶监测页**（`index.html` 顶部那段注释），
    那一页还拆成了页签。所以 C 段的靶子从 `/index.html` 换成 `/detail.html`、
    选择器从 `#p4 .p4-row` 换成 `[data-tab="behav"] .p4 .p4-row`
    （**没有 `#p4` 这个 id 了**），`pb` 从 `pNormal/pFatigue`（条的宽度）
    换成 `bvNormal/bvFatigue`（旁边那格文字）。
  · 支路二那一块从 `#p5` 的**两根条**换成「疲劳分析」页签里的一张卡：
    `#fPFat` + `#fPFatBar` + `#fGate` + `#fWarm`。F 段整段重写；
    旧那两条判据（两根条、和为 100%）**随元素退场**，不是被放宽。
  · D 段的支路一那一条**从首页挪到了驾驶监测页**：`?sev=` 只有首页认
    （`app.js` 的 onHello），那一页上得用页内 WS 拨时钟（45 s，和
    `_check_alarm.py` 的 E 段同一个时刻、同一个数）。

★ 2026-09-25 第八次改版之后改过什么（**屏幕变了**，不是脚本坏了）：
  · 驾驶监测页上那五个页签**整块搬去了新页 `monitor.html`**（「监测详情」，
    `detail.html` 的「更多」现在是一条跳过去的链接）⇒ C / D / F 三段的靶子页
    从 `/detail.html` 换成 `/monitor.html`，选择器一个字没改（`data-tab="behav"`
    那些属性在新页上原样留着，正是为了让选择器不用改）。
  · F 段里盯 `#fWarm` 那两条判据**退场**（那条说明 2026-09-24 就被删了，
    恒 `undefined` ⇒ 恒红，红的是历史）。同一段那两条判据的原文和理由在
    F 段中间，别把它们当成"被放宽了"。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session, ck          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

CDP = 9455          # 和其它脚本错开：9411 _check_pages / 9429 _check_theme2 / 9441 _check_alarm

# 12 页（`ui/web/*.html`）。**这不是"展示用的清单"，B 段要逐页打开** ——
# 少一页 = 那一页里的「分心」没人管。
# ★ 2026-09-25「第八次改版」加了 `monitor`（`detail.html` 的「更多」跳过去的
#   「监测详情」页）。B 段是逐页打开扫可见文字的，漏掉它 = 这一页没人管。
PAGES = ("cover", "index", "detail", "monitor", "chat", "link", "flow",
         "phone", "design", "media", "settings", "voice")

# (键, 期望 data-sev, 期望大标题, 期望头姿, 期望疲劳程度条宽度 %)
# ⚠️ `severe` 是 `fatigue` 的**别名**（见 ui/web/app.js 的 PIN_ALIAS），
#    两个写法都指向"点头"那一段，所以后三行的档位和头姿都一样 —— **不是抄错**。
# ⚠️ 第 4 列是**两层词面**之后的最终结果，写的是**屏上那个短词**：
#      服务端 `ui/state.py` 的 `attention`（长词：专注 / 略有低头 / 头部持续
#      低垂 / 疲劳点头）→ 前端 `ui/web/app.js:372` 的 `POSE_OF`（短词：正常 /
#      略低头 / 低头 / 点头）。这一列钉的是短词，所以**改 `POSE_OF` 或改
#      `HEAD_RANGE`/`NOD_BUSY` 都会让它红** —— 两种红都是对的。
#    ⚠️ 那几个值**不是从概率推的**：`?sev=` 各档落在 demo 的哪个时刻由 app.js 的
#      `PIN_SEEK` 定（30/45/95/125/155），那几个时刻的 d_pitch 实测
#      5.5 / 6.4 / 9.0 / 18.5 / 23.0，对着 `HEAD_RANGE(12)` 和它的半值(6) 一读
#      就是这一列（`nod` 只在 125/155 两点上分叉：3.0 与 9.0，跨过 `NOD_BUSY(5)`）。
#    ⚠️ 于是 `mild` / `moderate` 从旧表的「正常」变成了「略低头」—— 这不是抄错：
#      旧表那一列读的是**概率**（那两档支路一确实判正常，P(疲劳)=0.23/0.29），
#      现在读的是**测出来的头动**（6.4°/9.0°，真的大过半值 6）。
# ⚠️ 最后一列**是从 app.js 的 `DEG_W` 抄过来的**（12/45/66/88）。抄一份是为了
#    能被它逮住：谁改了 `DEG_W` 而没改这里的期望值，A 段会红 —— 那次红**是对的**
#    （说明外观常量动了，得有人看一眼）。别为了"消红"把这里改成动态取值，
#    那就变成自己验自己了。
EXPECT = [
    ("normal",   "normal",   "清醒",     "正常",   12),
    ("mild",     "mild",     "轻度疲劳", "略低头", 45),
    ("moderate", "moderate", "中度疲劳", "略低头", 66),
    ("phone",    "severe",   "重度疲劳", "低头",   88),
    ("fatigue",  "severe",   "重度疲劳", "点头",   88),
    ("severe",   "severe",   "重度疲劳", "点头",   88),
]

# ★ 2026-09-25：这里原来有一份 `ALLOW` 白名单，只为一处豁免 —— flow.html 末尾
# 那一节把方案里未实现的模块 3 原文（「YOLOv8n 分心物体检测」/「识别手机、水杯
# → 判定驾驶分心」，出处 runs/_spec_579.txt:24/27）画在虚线上，B 段扫可见文字时
# 先按白名单把那两句抠掉。
# **那一节已被用户删掉（原话「把这个去了」），白名单跟着撤销** —— 现在没有例外：
# 12 页的可见文字里出现「分心」一律报红。这正是 B 段原本的用意（用户口径里没有
# 这个概念），只是以前为了让引文上屏留了一个口子。
# ⚠️ 哪天有人把那段引文加回去，**豁免也要一起加回来**，否则 B 段会在 flow.html
#    上红 —— 那次红是**对的**（说明出现了没被豁免的引文），别直接把 B 段放宽。

PROBE = r"""
JSON.stringify((() => {
  const txt = (id) => (document.getElementById(id) || {}).textContent;
  const wd  = (id) => String((document.getElementById(id) || {style: {}}).style.width || '');
  const a = document.getElementById('alarms');
  /* ★ 2026-09-25：这两行原来找的是 `#p4` / `#p5` —— **两个 id 现在全站都不存在**。
     第五次改版把概率条整块搬去驾驶监测页（`index.html` 顶部那段注释、
     `app.js` 开头那段），第六次改版又把那一页拆成页签：支路一那两根条挪进了
     「行为特征」页签的无 id 方块 `.p4` 里，支路二换成了「疲劳分析」页签里的
     `#fPFat` + `#fPFatBar`（一个真数 + 一条条）。
     ⚠️ 用 `.p4` 这个**类**而不是 `#p4` 这个 id，就是因为搬过去之后没有 id 了。
     ⚠️ 那个页签是 `hidden` 的，但 `querySelectorAll` 照样找得到、`style.width`
        也照样读得到 —— 量的是"渲染出来的数"，不需要先把它点开。 */
  const rows = [...document.querySelectorAll('[data-tab="behav"] .p4 .p4-row')];
  const wid = (r) => {
    const i = r.querySelector('.bar i');
    return i ? parseFloat(i.style.width || '0') : null;
  };
  /* 卡片的**自然内容高度** = 各子块高度和 + 缝 + 上下内边距。
     ⚠️ 不能只看 `scrollHeight`：`.status` 是 `overflow:hidden` 的固定高度卡片，
        内容装不下时它顶多报到 clientHeight，而 flex 子项还会**先被压扁**
        （压扁了 scrollHeight 反而"正常"）。所以两个数都要：
        `nat` 说明要不要裁，`scroll` 说明有没有真的溢出。 */
  const st = document.querySelector('.status');
  let nat = null;
  if (st) {
    const cs = getComputedStyle(st);
    const kids = [...st.children].filter((e) => !e.hidden);
    nat = kids.reduce((s, e) => s + e.getBoundingClientRect().height, 0)
        + Math.max(0, kids.length - 1) * parseFloat(cs.rowGap)
        + parseFloat(cs.paddingTop) + parseFloat(cs.paddingBottom);
  }
  return {
    sev: document.body.dataset.sev,
    name: txt('sevName'),
    /* 疲劳程度那根条。★ 原来这里读的是 `#rLevel` 那行字（2026-09-24 深夜
       那行并进了顶部、元素删了），所以钉子换成**条的宽度** —— 见 A 段。 */
    barl: wd('barLevel'),
    pose: txt('rPose'),
    alarmHidden: a ? a.hidden : null,
    alarmItems: a ? [...a.querySelectorAll('.alarm-item')].map(e => (e.textContent || '').trim()) : [],
    /* 支路一那两条：按**行**取（C 段要和 = 100%），另外按**类别 id** 取一份
       （D 段要指名道姓，行序变了也不受影响 —— 行序真的变过）。
       ⚠️ 二类之后 `#pPhone` 这个元素**不存在了**，`wd()` 会拿到 `''` ——
          别再往里塞 phone 键：D 段会拿到 `pct('')` = None，然后以
          "`pp is not None` 不成立"的形式红，而那种红看起来像概率没出数。 */
    bars: rows.map(wid),
    barText: rows.map(r => (r.textContent || '').replace(/\s+/g, ' ').trim()),
    /* 支路一那两个数，**按类别的格子取**（`bv*` 是文字那一格）。
       ⚠️ 不能按行的位置取：行序真的变过，按位置解包会把两类的数对调，
          而这条判据两侧都是"够大/够小"，对调了照样绿（那种绿是假的）。 */
    pb: { normal: txt('bvNormal'), fatigue: txt('bvFatigue') },
    /* 支路二：**一个真数 + 一条条**（第六次改版那张卡，在「疲劳分析」页签里）。
       ⚠️ 别把 `pAlert` / `vAlert` / `pDrowsy` / `vDrowsy` 塞回来：那四个 id
          全站一个元素都没有（`app.js:374-375` 那两句 `setN` 是**守卫住的空操作**），
          读它们恒为 None，然后会以"热身时不是「—」"的形式红 ——
          而那种红看起来像页面坏了，其实是这里指错了地方。 */
    fpf: txt('fPFat'),
    fpw: wd('fPFatBar'),
    fgate: txt('fGate'),
    fnote: txt('b2Note'),
    /* ★ 2026-09-25：`fwarmHidden`（读 `#fWarm`）**删掉了**，不是漏了。
       那个元素 2026-09-24 已被删（见 F 段那两处退场说明），`ui/web/` 下任何
       一张活页上都没有它 —— 留着这个键只会恒 `undefined`，下一次读它的人
       会以为"页面坏了"，而真凶是搬家。 */
    bPhone: !!document.getElementById('bPhone'),
    /* ★ 2026-09-25：`nvText`（读右栏「系统公告」那四条）**删掉了**，不是漏了。
       那张卡当天被用户整卡删除（「这个是内部开发笔记！绝对不能留在参赛演示
       页面」），`ui/web/` 下 `.nv` 一个元素都没有了 —— 留着这个键只会恒空串，
       而 C 段还会以为自己有一份"合法出现"的名单。见 C 段那段注释。 */
    geo: st ? {client: st.clientHeight, scroll: st.scrollHeight,
               nat: Math.round(nat)} : null,
    body: (document.body.innerText || ''),
  };
})())
"""


def pct(s):
    """`"45%"` -> 0.45。读不到（元素不在这一页）就 None —— 判据自己会报红。

    ⚠️ 只吃**带百分号**的那种写法（概率条旁边那格 `bvNormal` 是 `"87%"`）。
       `#fPFat` 印的是**概率本身**（`"0.39"`），拿这个函数去解会把它当成
       0.39% 再除以 100，得到 0.0039 —— 然后"条宽和文字一致"那条会红，
       而红出来的两个数（39.0564 vs 0.39）看起来像页面算错了。那条要用 `num()`。
    """
    try:
        return float(str(s).rstrip("%")) / 100.0
    except (TypeError, ValueError):
        return None


def num(s):
    """`"0.39"` -> 0.39。同上，读不到就 None。"""
    try:
        return float(str(s))
    except (TypeError, ValueError):
        return None


async def seek(S, t):
    """借页面自己那条 WS 把演出时钟拨到 t 秒（只有 demo 源有时间轴）。"""
    return await S.js(
        "(function(){ const f = (typeof send === 'function') ? send"
        " : ((typeof link !== 'undefined' && link) ? link.send : null);"
        " if (!f) return 'no-send';"
        " try { f({type:'seek', t:%s}); return 'ok'; }"
        " catch(e){ return 'ERR ' + e.message; } })()" % float(t))


async def wait_alarm(S, want, timeout=4.0):
    """轮询到横幅出现 want 那句为止（时钟在走，不能睡死一个固定秒数）。"""
    last = None
    for _ in range(max(1, int(timeout / 0.4))):
        last = await S.js(PROBE)
        if any(want in x for x in last["alarmItems"]):
            return True, last
        await asyncio.sleep(0.4)
    return False, last


async def main():
    worst = 0
    async with Session(CDP) as S:

        # ---------------------------------------------------------- A
        print("\n=== A. 四个档位 + 三个 `?sev=` 写法 ===")
        for key, want_sev, want_name, want_pose, want_bar in EXPECT:
            await S.goto(f"/index.html?sev={key}", 3.0)
            d = await S.js(PROBE)
            worst |= ck(f"?sev={key:8s} data-sev={want_sev}", d["sev"] == want_sev,
                        f"拿到 {d['sev']!r}")
            worst |= ck("      大标题 = " + want_name, d["name"] == want_name,
                        f"拿到 {d['name']!r}")
            # 疲劳程度条：它跟的是 `DEG_W[severity]`（档位），**不是**安全通道那条
            # L 编号。这一条替掉了原来读 `#rLevel` 那行字的老钉子（那行已经并进
            # 顶部、元素删了）—— 轻度那一档的 `l1` 还是 0，谁把外观接回 level_name，
            # 这条会变成 12%（清醒那格），而**只看大标题是验不出来的**。
            worst |= ck("      疲劳程度条 = %d%%" % want_bar,
                        d["barl"] == "%d%%" % want_bar, f"拿到 {d['barl']!r}")
            worst |= ck("      头姿 = " + want_pose, d["pose"] == want_pose,
                        f"拿到 {d['pose']!r}")

        # ---------------------------------------------------------- B
        print("\n=== B. 全站可见文字里不再有「分心」/「视线偏移」 ===")
        # ⚠️ 只扫**可见文字**（`innerText`），不扫源码：源码里的注释还留着改版史
        #    （那些是给下一个人看的，删掉才是错的）。屏幕上出现才算漏改。
        # ⚠️ 这里禁的只是**上一版那个档位说法**「视线偏移」和「分心」这个概念本身。
        #    「低头看手机」不在此列 —— 它有自己的钉子，在下面 C 段（首页一处都不许留），
        #    而全站扫它会连带 detail.html 一起红，那不是这一段的职责。
        for page in PAGES:
            # ⚠️ 封面那一页 2026-09-25 起有一层**全屏不透明的品牌片头**。
            #    这一段扫的是 `innerText`（只含**渲染出来**的文字），片头自己
            #    那个「跳过片头 ›」会跟着进来 —— 它不含本段禁的两个词，不会假红，
            #    但还是关掉更干净：省一次 15 s 等待，判据也不受"片头播没播"影响。
            await S.goto(f"/{page}.html" + ("?intro=0" if page == "cover" else ""), 2.0)
            d = await S.js(PROBE)
            text = d["body"] or ""
            hit = [ln.strip() for ln in text.splitlines()
                   if ("分心" in ln) or ("视线偏移" in ln)]
            worst |= ck(f"{page}.html", not hit, " -> ".join(hit[:2]))

        # ---------------------------------------------------------- C
        # ★ 2026-09-25：这一段原来打在 `/index.html` 上，**已改指 `/detail.html`**
        #   —— 第五次改版把支路一/二的概率条整块搬去了驾驶监测页（见 `index.html`
        #   顶部那段注释、`app.js` 开头那段）。搬完之后首页上这两块一个元素都没有，
        #   于是老写法拿到的 `bars` 是 `[]`，红出来的三句话（"两行"、"合计 0%"、
        #   "标签"）**看起来像概率条坏了，其实是打错了页**。
        #   ⚠️ 这一页上 `?sev=` **不生效**（走的是页内 WS，见 D 段那段注释），
        #      所以这里不要 `?sev=` 后缀；要拨时钟用 `seek()`。
        # ★ 2026-09-25 第八次改版：那两个页签**整块搬去了 monitor.html**
        #   （`detail.html` 的「更多」现在是一条跳过去的链接，见那一页的文件头）。
        #   于是这一段和 D 段、F 段的靶子页都换成 `/monitor.html`。
        #   ⚠️ `data-tab="behav"` 这些属性**在新页上原样留着**，就是为了让选择器
        #     不用改 —— 它们在新页上也不再 `hidden` 了（新页不再有页签）。
        print("\n=== C. 支路一概率条恰好两行、加起来 100%（在监测详情页）===")
        await S.goto("/monitor.html", 3.2)
        d = await S.js(PROBE)
        worst |= ck("支路一概率条两行", len(d["bars"]) == 2, str(len(d["bars"])))
        # 二类是 softmax 出来的，和必然是 1。**漏掉一类自然和就不是 100%** ——
        # 这正是这条判据的价值：它证明"屏上这两行就是全部"，而不是"只画了两行"。
        # ⚠️ 每一条都 `toFixed(0)` 取整过，所以留 ±2 的容差（99%/101% 都可能）。
        tot = sum(x for x in d["bars"] if x is not None)
        worst |= ck("两条加起来 100%（取整容差 ±2）", abs(tot - 100) <= 2,
                    f"合计 {tot}%  {d['bars']}")
        # ★ 两个标签按用户原话（2026-09-25：「点头这个 直接 疲劳瞌睡点头和头部
        #   持续低头变成一路吧」→ phone 与 fatigue 合成一类，所以是「低头·点头」）。
        # ★ 两个标签按用户原话（2026-09-25：「点头这个 直接 疲劳瞌睡点头和头部
        #   持续低头变成一路吧」→ phone 与 fatigue 合成一类，所以是「低头·点头」）。
        #   ⚠️ 这一页上第一行只写「正常」（首页那一版写的是「正常头部姿态」）——
        #      别按记忆里的旧文案断言，去 `detail.html:307-308` 看一眼那两行。
        names = " ".join(d["barText"])
        worst |= ck("两行标签是 正常/疲劳（低头·点头）",
                    all(k in names for k in ("正常", "疲劳（低头·点头）")), str(d["barText"]))
        # ★ 第三根条**必须是删掉、不是隐藏**：留着它不会报错，但写入方按
        #   `Object.keys(probs)` 拼 id，少一个键就少一次写入，`if (e)` 那句
        #   会安静跳过 —— 屏上就是一根永远 0% 的死条。这条钉子专门盯它。
        #   ⚠️ 两个前缀都查：首页那套是 `p*`（`app.js`），这一页是 `b*`
        #      （`detail.html:762-767`）。改名的时候只改一边，就会留下一个
        #      "定义在 HTML 里、谁都不写"的死元素。
        worst |= ck("★ 没有残留的 #pPhone / #bPhone 死条",
                    d["bPhone"] is False
                    and not await S.js("!!document.getElementById('pPhone')"),
                    f"bPhone={d['bPhone']}")

        # ★★ 用户原话：「删除原来的旧标签"低头看手机"！」—— 它**不许再当作类别名用**：
        #    概率条那一行没有、底部那行小字也没有（两处叫两个名字的话，同一张卡
        #    里会自己打自己的脸）。
        #    ⚠️ 2026-09-25 起**这条判据比原来严了**，原因不是"想严一点"，是**例外
        #       没了**：原来右栏「系统公告」那条改版史是唯一豁免（它是改版史，写的
        #       就是"这一类并进疲劳类了"，不点名说不出改了什么），判据是"只在公告里
        #       出现"。**那张卡当天被用户整卡删掉**（「这个是内部开发笔记！绝对不能
        #       留在参赛演示页面 —— 评委点开主页第一眼就会看到开发记录」），而全站
        #       唯一那处合法出现就在它第一条里（「支路一的「低头看手机」与…」）。
        #       所以现在是：**首页一处都不许出现**。
        #    ⚠️ 别把这条改回"允许出现在某处" —— 没有任何一处可以放了。
        await S.goto("/index.html", 3.0)
        d0 = await S.js(PROBE)
        # 报错时要说清"是哪一句" —— 逐行列出来，而不是只报个数。
        hit = [s.strip() for s in (d0["body"] or "").splitlines()
               if "低头看手机" in s]
        worst |= ck("★★ 首页一处都没有「低头看手机」", not hit,
                    "整页 %d 处：%s" % (len(hit), hit[:2]))

        # ---------------------------------------------------------- D
        print("\n=== D. 轻度那一格**是支路二给的**（屏幕上再钉一次）===")
        # ① 支路一在这一档仍旧判正常 —— 但这条**得在驾驶监测页上看**：
        #    第五次改版之后首页上已经没有概率条了，而 `?sev=` 只在首页生效
        #    （走 `app.js` 的 onHello），所以到了这一页就得用页内 WS 拨时钟。
        #    45 s 落在 demo 那一轮轻度桥段里（和 `_check_alarm.py` 的 E 段同一个
        #    时刻、同一个数，两处对不上说明有一处指错了）。
        #    ★ 2026-09-25 第八次改版：概率条搬去了 `/monitor.html`，靶子页跟着换
        #      （`_check_alarm.py` 的 E 段也是同一天改的这一处，别只改一边）。
        await S.goto("/monitor.html", 3.2)
        r = await seek(S, 45.0)
        worst |= ck("   页面真的发出了 seek", r == "ok", r)
        # 支一在这一档仍判正常：P(正常) ≥ 0.60，P(疲劳) 实测 0.23。
        # 所以这一档**不可能**是支一给的 —— 升级是逐类判 `ema[k] > ENTER_TH(0.60)`
        # （`src/live.py:117`），0.23 离 0.60 差得远，这一档只剩支路二能给。
        # ⚠️ 按**类别 id** 取（`d["pb"]`），不按行的位置 —— 行序真的变过，
        #    按位置解包会把两类的数对调，而这条判据两侧都是"够大/够小"，
        #    对调了照样绿（那种绿是假的）。
        # ⚠️ `0.25` 不是从哪个常量抄的，是**留出来的余量**（远低于 ENTER_TH 0.60）：
        #    它要咬的是"这一档的概率条根本没往疲劳那边倒"。
        # ⚠️ 时钟在走，不能睡一个固定秒数就下结论 —— 轮询到出数为止。
        pn = pf = None
        for _ in range(10):
            await asyncio.sleep(0.4)
            # ⚠️ `.get` 两级：`bvNormal` 读不到时 `JSON.stringify` 会把那个键整个
            #    丢掉，`pb["normal"]` 是 **KeyError**，整个脚本当场崩 —— 2026-09-25
            #    第八次改版第一次跑就是这么崩的（当时靶子页还没改）。
            #    崩掉的样子（一段 traceback）和"判据红"完全是两回事，很难一眼看出
            #    真凶是"指错页了"。
            pb = (await S.js(PROBE)).get("pb") or {}
            pn, pf = pct(pb.get("normal")), pct(pb.get("fatigue"))
            if pn is not None:
                break
        worst |= ck("★ 支路一在这一档仍判「正常」", pn is not None and pn >= 0.60
                    and pf is not None and pf < 0.25,
                    f"P(正常)={pn} P(疲劳)={pf}")
        # ② 档位与横幅那两条仍在首页上（`?sev=` 只有那一页认）。
        await S.goto("/index.html?sev=mild", 3.0)
        d = await S.js(PROBE)
        worst |= ck("   这一档的档位是轻度疲劳（不是清醒）", d["name"] == "轻度疲劳",
                    repr(d["name"]))
        # 拨到哈欠桥段（sources.py YAWN_A/B = 48~55，yawn_sec≥2.0 的窗口 [50,53]）：
        # 档位**不该变**（打哈欠就是轻度），而横幅要报出来。
        r = await seek(S, 50.5)
        worst |= ck("   页面真的发出了 seek", r == "ok", r)
        got, d2 = await wait_alarm(S, "检测到打哈欠")
        worst |= ck("★ 拨到桥段后横幅报「检测到打哈欠」", got,
                    "items=%s hidden=%s" % (d2["alarmItems"], d2["alarmHidden"]))
        worst |= ck("   而档位**还是**轻度疲劳（哈欠不改变档位）",
                    d2["name"] == "轻度疲劳" and d2["sev"] == "mild",
                    f"sev={d2['sev']!r} 大标题={d2['name']!r}")

        # ---------------------------------------------------------- F
        # ★ 2026-09-25 重写。这一段原来守的是首页那个 `#p5` 方块：**两根**条
        #   （alert / 疲劳）、加起来 100%。第六次改版之后 `#p5` 全站一个元素都
        #   没有，支路二那一块换成了 `/detail.html`「疲劳分析」页签里的一张卡：
        #   **一个真数** `#fPFat`（P(fat)）+ 一条 `#fPFatBar`，旁边是闸门那格。
        #   于是判据跟着换成"这一个数和这条条是同一个数给的、热身时是「—」
        #   不是 0%"。那两条旧判据（两根条、和为 100%）**随元素一起退场** ——
        #   它们没有可咬的对象了，硬留着写成的"两根条"只会在每次跑的时候红，
        #   而红的理由是"屏上没有那两根条"，看着像回归、其实是历史。
        #   ⚠️ `app.js:374-375` 那两句 `setN('pAlert'…)` 现在也是空操作
        #      （守卫住的），别拿它当"这一块还在"的证据。
        print("\n=== F. 支路二那一块：一个真数、「—」不是 0% ===")
        # ★ 2026-09-25 第八次改版：这一块（`#fPFat` / `#fPFatBar` / `#fGate` /
        #   `#b2Note`）现在在 `/monitor.html` 的「疲劳分析」那一节里，靶子页换了。
        await S.goto("/monitor.html", 3.2)
        # 6 s：统计量可能刚出（ROLL_WIN 10 s），模型判决一定还没出（WARMUP 27 s）。
        # ⚠️ 从"刚打开的 3 秒"拨过去，而不是先拨到后面再拨回来 —— 页内那些
        #    滚动缓冲是按帧攒的，往回拨不会把已经攒满的缓冲清空。
        #    （`_check_alarm.py` 的 E 段拨 45 s 是同一件事的反面用法。）
        r = await seek(S, 6.0)
        worst |= ck("   页面真的发出了 seek", r == "ok", r)
        d = None
        for _ in range(10):
            await asyncio.sleep(0.4)
            d = await S.js(PROBE)
            if d["fpf"] is not None:
                break
        # **不能是 0%** —— "0% 疲劳"是一个判决，"还没有这个数"是另一件事，
        # 而这个区别正是这套界面一直在守的东西（PERCLOS 那格也一样）。
        worst |= ck("★ 支路二还没热身完时那一格是「—」、不是 0%",
                    d["fpf"] == "—" and d["fpw"] == "0%",
                    f"文字 {d['fpf']!r} 宽 {d['fpw']!r}")
        worst |= ck("   闸门那一格同样是「—」（不是「关」）",
                    d["fgate"] == "—", repr(d["fgate"]))
        # ★★ 这里原来有两条判据盯着 `#fWarm`（「两道门槛 10s / 27s」那段说明：
        #    热身时露出来、出判决后收起来）。**那条说明 2026-09-24 已被删掉**
        #    （第七次改版把「热身中 / 统计量已出 · 待判决」并进了 `#b2Note` 那一格，
        #    那段静态小字是重复的），`ui/web/` 下任何一张活页上都没有 `#fWarm` 了。
        #    ⇒ `PROBE` 里那个 `fwarmHidden` 恒为 `undefined`，两条判据恒红 ——
        #    那是**历史**，不是回归。所以它们**随元素一起退场**（不是放宽、
        #    也不是换个靶子接着写：那个信息现在只有 `#b2Note` 一处，下面这条
        #    已经是它的判据了，再写一条就是同一个数断言两遍）。
        #    ⚠️ 别为了"消红"把 `#fWarm` 建回来 —— 用户那一版的版面上没有它。
        worst |= ck("   状态那格说的是「热身中」或「统计量已出 · 待判决」",
                    d["fnote"] in ("热身中", "统计量已出 · 待判决"), repr(d["fnote"]))

        # 热身完了之后：文字是概率，条的宽度就是**那个数** ×100 —— 同一个人给的。
        r = await seek(S, 45.0)
        worst |= ck("   页面真的发出了 seek", r == "ok", r)
        for _ in range(12):
            await asyncio.sleep(0.4)
            d = await S.js(PROBE)
            if num(d["fpf"]) is not None:
                break
        # ⚠️ `#fPFat` 印的是**概率**（`toFixed(2)`，例如 "0.39"），不是百分数 ——
        #    这里必须用 `num()`，用 `pct()` 会解成 0.0039（见 `pct()` 那段注释）。
        v = num(d["fpf"])
        # ⚠️ 这一页的宽度不是 `toFixed(0)` 出来的（`detail.html:423` 的 `W()`
        #    直接 `数字 + '%'`），所以**不能字符串比** —— 77.00000000000001%
        #    这种值是正常的，拿 `==` 比会红。留半格容差。
        fw = None
        try:
            fw = float(str(d["fpw"]).rstrip("%"))
        except (TypeError, ValueError):
            pass
        worst |= ck("★ P(fat) 出数之后，条的宽度和文字是同一个数",
                    v is not None and fw is not None and abs(fw - v * 100) <= 0.51,
                    f"文字 {d['fpf']!r} 宽 {d['fpw']!r}")
        # （「两级门槛那段说明这时收起来」那条同上一处，随 `#fWarm` 一起退场。）
        worst |= ck("   闸门那格这时说的是 开/关",
                    ("开" in (d["fgate"] or "")) or ("关" in (d["fgate"] or "")),
                    repr(d["fgate"]))

        # ---- 卡片高度：**在目标分辨率上量**（现场投影 1920x1080）。
        # ⚠️ 检查用的窗口是 1672x940（`_check_pages.py` 起的 Edge），比目标小
        #    一大圈；在那个尺寸上这张卡**本来就装不下**（2026-09-24 深夜量到：
        #    改动前重度那一档溢出 30px，改动后溢出降到 0 以内但小窗口仍然紧）。
        #    所以判据必须**把视口改成 1080p 再量**，否则验的是"小窗口"而不是
        #    "现场会不会被裁"。小窗口的数只印出来看，不计入失败。
        # ⚠️ 这一张卡在**首页**（`.status`）。F 段刚把页面留在 `/detail.html` 上，
        #    那一页没有 `.status`，`geo` 是 None —— 所以量之前必须先回首页，
        #    否则下面那句 `small["geo"]["nat"]` 是 `None[...]`，当场 TypeError。
        #    （「脚本崩了」和「卡片被裁了」长得完全不一样，但都很容易被当成后者。）
        print("\n--- 卡片高度（判据在 1920x1080 上量；小窗口只印数）---")
        await S.goto("/index.html?sev=normal", 3.0)
        small = await S.js(PROBE)
        print("    1638x843（检查窗口）?sev=normal：内容 %s / 卡 %s"
              % (small["geo"]["nat"], small["geo"]["client"]))
        await S.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": 1920, "height": 1080, "deviceScaleFactor": 1,
                     "mobile": False})
        for key in ("normal", "fatigue"):
            await S.goto(f"/index.html?sev={key}", 3.2)
            g = (await S.js(PROBE))["geo"]
            worst |= ck("[%s] ★ 1920x1080 下卡片装得下（底部日志没被裁）" % key,
                        g["nat"] <= g["client"] + 1 and g["scroll"] <= g["client"] + 1,
                        "内容 %d / 卡 %d / scroll %d（负数=裁掉了）"
                        % (g["nat"], g["client"], g["scroll"]))
        await S.cmd("Emulation.clearDeviceMetricsOverride")

        # ---------------------------------------------------------- E
        print("\n=== E. 控制台零报错 ===")
        worst |= ck("无 error / warning", not S.errs, S.errs[:4])

    print("\n" + "=" * 68)
    print("**%d 项不过，见上**" % worst if worst
          else "**全绿**（配色/语音仍要人眼看：四档的观感、念出来的语气）")
    return worst


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
