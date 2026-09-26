"""验支路二那两条**独立告警**（持续闭眼 / 打哈欠）真的报得出来 —— 外加一条
更要紧的：**轻度疲劳那一格是支路二给的**。

    D:\\Anaconda3\\envs\\dms\\python.exe ui\\server.py --port 8790 --source demo
    python _scratch/_check_alarm.py 8790

## 为什么单独一个脚本

用户原话：**「轻度疲劳就是打哈欠啊 闭眼时间稍长啊 重度疲劳就是点头 低头」
「正常情况下也要有长时间闭眼和打哈欠的报警啊 我支路2就是做的这个训练啊」**
两条诉求，都只能在这儿验：

  1. **轻度疲劳 = 支路二**（打哈欠 / 闭眼变长），不是支路一。
     `?sev=mild` 那一段必须是 `data-sev=mild`（黄）、大标题「轻度疲劳」，
     **而支路一在那一段仍旧判「正常」**（两条概率条里 normal 仍是七成以上）。
     最后那半句才是这条诉求的判据 —— 只验前两样的话，"把支路一的某个类别
     也算成轻度"这种改法照样能过。→ E 段。**这一段是本次改动的核心，别删。**
  2. **打哈欠 / 长时间闭眼各报一条独立告警。** 这两件事在管线里会把级别
     顶起来（`src/fuse.py:635-638`，红线不许动），所以"报出来了"这件事
     本身证明不了界面做对了 —— 要验的是**归因**：横幅要说得出是"因为打哈欠"
     还是"因为持续闭眼"。→ B/C/D 段。
     ⚠️ 两条**顶到的档不一样**：哈欠是 **L1**，长闭眼是 **L2**
        （`src/fuse.py` 的 EYE_LEVEL）。所以 t≈65 上 banner 用的是
        `NOTE_FACE[2]`「检测到持续闭眼，**疲劳征兆**」那一句 —— 判据是
        "**属于闭眼规则那一族、且不是支路二那句**"，不是逐字等于 L1 那句。

★ 2026-09-24 深夜「只做疲劳」（第四批）：上一版这里验的是**分心不是疲劳**
  （`?sev=glance` → 黄格、大标题「注意」、疲劳程度「正常」）。那条诉求连同
  `glance` 这整个类别一起作废了（用户原话「phone 直接归为重度疲劳
  fatigue 依旧是疲劳 glance 删掉」），所以 E 段整段换成了上面第 1 条。
  ⚠️ **别把 E 段改回"分心"那一版** —— 那个键现在连页面都不认了。
  同日深夜「右侧面板改版」：卡片里「疲劳程度」那一行**并进了顶部**（文字和大标题
  同源、多余），`#rLevel` 元素整体删除 → E/F 两段的靶子从"那行字"换成
  **顶部那根条的宽度**（`#barLevel`，值取 `app.js` 的 `DEG_W`：12/45/66/88）。
  读条宽比读字硬：它顺手把"外观常量有没有被人动过"也一起验了。

## 两个桥段从哪来

演示数据里那两个桥段是 `ui/sources.py` 的 `DemoSource.YAWN_A/YAWN_B`（48~55 s）
和 `EYES_A/EYES_B`（62~68 s），**在轻度段里**（轻度段那个档本身要干净地是
"只有 severity 进 mild、支路一仍旧判正常"，所以两个桥段是唯一会把告警
顶起来的地方）。⚠️ 桥段挪了，这里的 SEEK 点要跟着挪 ——
`sources.py` 那两行注释里点了本文件的名字，就是为这个。

## 怎么把时钟拨到桥段上

`?sev=` 只能定位到五个段的**中段**（`ui/web/app.js` 的 `PIN_SEEK`），
拨不到桥段上。所以 B/C/D 段**不用 `?sev=`**：开一个干净的 `/index.html`，
再用**页面自己那条 WebSocket** 发一条 `{type:'seek', t:…}`（服务端
`ui/server.py:398` 支持这个 kind，只有 demo 源有时间轴）。

⚠️ 时钟是**真走**的：拨到 51 s 之后它一秒一秒往前。所以读之前要**轮询**，
不能睡死一个固定秒数 —— 哈欠那个窗口只有 [49.0, 54.0] 约 5 秒宽
（`yawn_sec ≥ alarm.yawn_min = 1.0` 的那段；`_blip` 在桥段外恒为 0），
睡过头就掉出去了，而掉出去的表现是"横幅自己收了"，看着像功能坏了。
⚠️ 2026-09-26：这段原来写的是「[50.0, 53.0] 约 3 秒宽（yawn_sec ≥ 2.0）」——
那是**改小之前**的阈值。阈值降到 1.0 之后窗口两头各宽了 1 秒，那两个数就
不再描述现实（`_check_demo_arc.py` 的 E 段也是踩的同一个 2.0）。

## 这个脚本**证明不了**的

  · 真人身上到底会不会报（那是 `--source cam` 的事，得人坐在镜头前打哈欠）；
  · 横幅**好不好看**、位置压没压住别的卡（只有人眼说了算，见 G 段的截图）；
  · 服务端 `alarms` 的**文案**对不对（这里是逐字比服务端给的字符串，
    两边一起错是验不出来的 —— 真正的出处在 `src/fuse.py:161-164`）。
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session, ck          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
CDP = 9441          # 和其它脚本错开：9429 是 _check_theme2 / 9411 是 _check_pages

# 桥段上的两个点（**取窗口靠前处，不取边界** —— 时钟只往前跑，所以宁可
# 留后手：拨早了还能往前走到阈值，拨晚了就直接掉出窗口）。
SEEK_YAWN = 50.5     # sources.py YAWN_A/B = 48.0~55.0；yawn_sec≥1.0 的窗口 [49.0, 54.0]
SEEK_EYES = 65.0     # sources.py EYES_A/B = 62.0~68.0，整段都是闭眼（6 s 宽）
SEEK_GAP = 58.5      # 两个桥段之间那 7 s：**两个告警都不该有**
SEEK_CLEAN = 32.0    # 清醒段后段（0~40）：**支路二已经热身完**（span 32 > 27），
                     # 但两个桥段都还没到 —— 所以这是"管线全开、判据干净"的那一点，
                     # 比拨到 14 s（支路二压根没数）更能说明"没判据就收横幅"。
# ★ 2026-09-25 新增：= `ui/web/app.js` 的 `PIN_SEEK.mild`。原来 E 段靠首页的
#   `?sev=mild` 定位就够，但概率条搬去监测详情页之后那一半得**在那一页上**读，
#   而 `?sev=` 只在首页生效（它走 app.js 的 onHello）—— 那一页要自己 seek。
#   ⚠️ 第八次改版把 E 段读的靶子页从 `/detail.html` 换成了 `/monitor.html`，
#      这个常数**没动**（45.0 是 demo 演出里的时刻，和哪一页无关）。
SEEK_MILD = 45.0     # 轻度段 40~80 的中前段，两个桥段（48~55 / 62~68）都在它后面

TXT_YAWN = "检测到打哈欠"          # = ui/state.py 的 NOTE_YAWN（抄自 src/fuse.py:162）
TXT_EYES = "检测到持续闭眼"        # **闭眼规则**那一族的前缀 = NOTE_FACE[1] / [2]
# ★ 2026-09-26：`ui/state.py` 把那句话按**来源**分成了两张表 —— 闭眼规则
#   （`src == "eye"`，它真在归一化 EAR 上数过"连续闭了多久"）说「检测到持续闭眼…」，
#   支路二（`l2`，量的是闭眼**占比**，没有"连续"这回事）说「闭眼时间变长…」。
#   用户报的正是后者冒充前者（「我只是眨眼，它凭什么说检测到持续闭眼」）。
#   所以 D 段（t≈65，`src == "eye"`）要**同时**验两件事：属于规则那一族
#   **且**不是支路二那句。⚠️ 只验前者是验不出配错的 —— 而这一条正是这次改动
#   唯一值得验的东西。字面量在这里**故意不 import**（见文件头：
#   "两边一起错是验不出来的"，独立抄一份才有意义）。
TXT_EYES_MODEL = ("闭眼时间变长", "闭眼时间明显变长")     # = NOTE_FACE_MODEL

# 页面上的取证探针：横幅在不在、写了什么、toast 有没有真的弹过。
#
# ⚠️ toast 必须**挂观察者**，不能"读一眼 #toast 的 class"：它 2.8 秒自毁
#    （style.css 的 #toast 那段），而我们的采样点落在它之后 —— 直接读会
#    把"弹过了、已经收了"读成"没弹"，也就是一个**恒假的判据**。
#    这里挂两条：`__flashLog`（XQ.flash 被调用了）和 `__toastLog`
#    （#toast 真的加上过 `on` 这个类）。两条都留是因为它们证明的事不一样 ——
#    前者证明走了那条代码路径，后者证明**屏幕上真的出现过**。
HOOK = r"""
(function () {
  if (window.__flashLog) return 'already';
  window.__flashLog = [];
  window.__toastLog = [];
  const f = XQ.flash;
  XQ.flash = function (txt) { window.__flashLog.push(String(txt)); return f.apply(this, arguments); };
  const el = document.getElementById('toast');
  if (el && window.MutationObserver) {
    new MutationObserver(() => {
      if (el.classList.contains('on') && el.textContent) window.__toastLog.push(el.textContent);
    }).observe(el, { attributes: true, attributeFilter: ['class'],
                     childList: true, characterData: true, subtree: true });
  }
  return 'hooked';
})()
"""

# 一次读全：横幅 + 大标题 + 疲劳程度条 + 头姿 + 两条概率 + 级别键 + 两句日志。
# ⚠️ `#alarms` 可能不存在（这一页没有告警位）—— 那种情况下 `miss: true`，
#    不是"隐藏"，别把两者混成一条判据。
# ⚠️ `rPose` / `vNormal` 这几个 id **只有首页有**（驾驶监测页叫 mPose / bvNormal），
#    在别的页上 `txt()` 返回 undefined、`JSON.stringify` 会把这个键整个丢掉 ——
#    所以读的人要 `(d.get('pose') or '')`，别直接下标。
PROBE = r"""
JSON.stringify((() => {
  const a = document.getElementById('alarms');
  const txt = (id) => (document.getElementById(id) || {}).textContent;
  const wd  = (id) => String((document.getElementById(id) || {style: {}}).style.width || '');
  return {
    hasHost: !!a,
    hidden: a ? a.hidden : null,
    items: a ? [...a.querySelectorAll('.alarm-item')].map(e => (e.textContent || '').trim()) : [],
    sev: document.body.dataset.sev,
    name: txt('sevName'),
    /* ★ 疲劳程度。**读条宽，不读字**：2026-09-24 深夜那一行文字并进了顶部
       （和大标题同源、多余），`#rLevel` 这个元素整个删了 —— 所以这条判据的
       靶子从"那行字"换成了 `#barLevel` 的宽度（`DEG_W[severity]`）。
       宽度比文字更硬：它连"档位对不对"之外还顺手验了外观常量有没有被人改。 */
    barl: wd('barLevel'),
    pose: txt('rPose'),
    /* ⚠️ 二类之后 `#vPhone` **不存在了**（那一行连同 `#pPhone` 一起删的）——
       `txt()` 会给 undefined，`JSON.stringify` 顺手把这个键整个丢掉，
       于是读的人拿到 `None` 而不是崩。别把 phone 键加回来：加了也只会拿到
       undefined，然后以"它 < 0.25 不成立"的形式红，看起来像概率没出数。
       ★ 2026-09-25：这一块**从首页搬走了**（`app.js` 头部注释：「概率条、
       支路二的原始量、底部对话栏整块搬去了驾驶监测页」），首页上连
       `#vNormal` 都没有了，id 变成 `bvNormal` / `bvFatigue`。
       ★★ 同日第八次改版它**又搬了一次**：驾驶监测页那五个页签整块搬去了新页
       `/monitor.html`（「监测详情」，`detail.html` 的「更多」跳过去的那一页），
       所以 `bvNormal` **现在在 monitor.html 上**。`_check_alarm.py` 这一段读
       它之前先 `goto("/monitor.html")`（见 E 段），别以为还在驾驶监测页上。
       这里**只读那一套** —— 留一个恒 undefined 的首页键只会让下一次
       读它的人以为"概率没出数"，而真凶是搬家。 */
    pb: { normal: txt('bvNormal'), fatigue: txt('bvFatigue') },
    flash: window.__flashLog || [],
    toast: window.__toastLog || [],
  };
})())
"""


def pct(s):
    """`vNormal` 那种 "77%" 文本 -> 0.77。读不到就 None（判据自己会报红）。"""
    try:
        return int(str(s).rstrip('%')) / 100.0
    except (TypeError, ValueError):
        return None


async def hook(S):
    """装上取证探针。**每换一次页面都要重新装** —— 导航会把 window 清掉。"""
    return await S.js(HOOK)


async def seek(S, t):
    """借页面自己那条 WS 拨时钟。

    为什么不用外开一条 Python 的 WS：页面里那条已经连着，多一条要处理握手、
    消息格式、以及"这条连接会不会影响页面"的问题；而 `send` 本来就是页面
    给外部世界用的入口（`ui/web/app.js:548` 那句 `send = link.send`）。
    找不到 send 时**明确报出来**，不要静默 —— 静默的表现是"时钟没动，
    告警没出现"，看的人会去查告警逻辑，而真凶是这里。
    """
    return await S.js(
        "(function(){ const f = (typeof send === 'function') ? send"
        " : ((typeof link !== 'undefined' && link) ? link.send : null);"
        " if (!f) return 'no-send';"
        " try { f({type:'seek', t:%s}); return 'ok'; }"
        " catch(e){ return 'ERR ' + e.message; } })()" % float(t))


async def wait_alarm(S, want_txt, timeout=4.0):
    """轮询到横幅里出现 want_txt 为止（时钟在走，不能睡死）。

    返回 (命中了吗, 最后一次的读数)。
    `want_txt=None` 表示**期望没有告警**（横幅收掉）—— 那时候命中条件是
    `hidden` 为真。⚠️ 这一支千万别写成 `not hidden`（那是它的反面），
    写反的后果是"横幅明明收掉了，判据却报红"，或者更坏：一直等到超时。
    """
    last = None
    for _ in range(max(1, int(timeout / 0.4))):
        last = await S.js(PROBE)
        if want_txt is None:
            if last["hidden"]:
                return True, last
        elif any(want_txt in x for x in last["items"]):
            return True, last
        await asyncio.sleep(0.4)
    return False, last


async def check_box(S, label):
    """横幅出现之后**不能被卡片裁掉** —— 这是布局判据，两个宿主都要过。

    `.status`（首页）和驾驶员卡（驾驶监测页）都带 `overflow:hidden`（见 style.css），
    而横幅是加在它们**里面**的 —— 内容一多就会被裁，而裁掉的表现是
    "横幅只露出一半"，截图上很容易被当成设计如此、没人会去查。
    ⚠️ 判据用**矩形关系**（横幅的上下边都在卡片的框内），不用"看着像"；
    留 1px 容差给亚像素取整。
    """
    box = await S.js(
        "JSON.stringify((() => {"
        " const a = document.getElementById('alarms');"
        " if (!a || a.hidden) return {skip: true};"
        " const card = a.closest('.card') || a.parentElement;"
        " const r = a.getBoundingClientRect(), c = card.getBoundingClientRect();"
        " return {skip: false, top: r.top - c.top, bottom: c.bottom - r.bottom,"
        "         h: r.height, cardH: c.height,"
        "         over: getComputedStyle(card).overflow};"
        "})())")
    # ⚠️ `box` 在 skip 时**没有** top/bottom 这两个键，所以 note 里不能
    #    直接 `:.1f` 格式化（会 TypeError 把整段打断）。
    note = ("横幅当时是收着的，这条只能记 skip" if box.get("skip") else
            "上留 %.1f / 下留 %.1f 高 %.1f 卡片高 %.1f overflow=%s"
            % (box["top"], box["bottom"], box["h"], box["cardH"], box["over"]))
    return ck("%s 横幅整个在卡片里（没被 overflow:hidden 裁掉）" % label,
              (not box.get("skip")) and box["top"] >= -1 and box["bottom"] >= -1
              and box["h"] > 0, note)


async def main():
    worst = 0

    async with Session(CDP) as S:
        print("\n" + "=" * 68)
        print("A. 清醒段上不该有告警（?sev=normal -> t=30，两个桥段都在它后面）")
        await S.goto("/index.html?sev=normal", 3.2)
        d = await S.js(PROBE)
        worst |= ck("有告警位 #alarms", d["hasHost"], d.get("hasHost"))
        worst |= ck("★ 它是 hidden（清醒段不该报）", d["hidden"] is True,
                    f"hidden={d['hidden']} items={d['items']}")
        worst |= ck("   这一档是「清醒」", d["sev"] == "normal" and d["name"] == "清醒",
                    f"data-sev={d['sev']} 标题={d['name']!r}")

        print("\n" + "=" * 68)
        print("B. 轻度段里的**打哈欠桥段**（t≈51）")
        await S.goto("/index.html", 2.6)      # 不用 ?sev=：桥段拨不到，只能自己 seek
        print("  取证探针:", await hook(S))
        r = await seek(S, SEEK_YAWN)
        worst |= ck("      页面真的发出了 seek", r == "ok", r)
        got, d = await wait_alarm(S, TXT_YAWN)
        worst |= ck("★ 横幅报出「%s」" % TXT_YAWN, got,
                    "items=%s hidden=%s" % (d["items"], d["hidden"]))
        worst |= ck("   toast 也弹过同一句（XQ.flash 被调用）",
                    any(TXT_YAWN in x for x in d["flash"]), d["flash"][-3:])
        worst |= ck("   toast 真的出现在屏幕上过（#toast 加上过 on）",
                    any(TXT_YAWN in x for x in d["toast"]), d["toast"][-3:])
        # ⚠️ 顺带记一条**如实**的事实，不判过不过：桥段期间**档位还是 mild**
        #    （打哈欠这一件事在口径里本来就归轻度疲劳，`src/fuse.py` 只会把
        #    L_fused 顶到 1，而 severity 在轻度段上本来就是 mild）——
        #    所以"整页是黄的"不是告警引起的，别把它当成重复报警去修。
        print(f"  (说明) 桥段期间 data-sev={d['sev']} 标题={d['name']!r} —— "
              f"哈欠在管线里会把 L_fused 顶到 1，而这一段的档位本来就是轻度")
        # 首页那张卡的布局：它是最常被截图的一页（答辩用），横幅把它自己的
        # 明细行顶出去就白改了 —— `.status` 是 overflow:hidden 的。
        worst |= await check_box(S, "index")

        print("\n" + "=" * 68)
        print("C. 两个桥段之间（t≈58）：判据没了，横幅要**立刻**收")
        r = await seek(S, SEEK_GAP)
        ok, d = await wait_alarm(S, None, timeout=2.0)
        worst |= ck("★ 横幅收掉了", ok, f"items={d['items']} hidden={d['hidden']}")
        # 去重：整场下来哈欠那句话**只该弹过一次**（上升沿）。时钟在桥段里
        # 走了一个多来回、探针也轮询了十来次，如果每次读到都在 flash，
        # 屏幕就是每 0.4 秒弹一次 —— 而 `held` 那张表正是为这个存在的。
        worst |= ck("★ 整场只弹过一次（上升沿去重，不是每拍都弹）",
                    sum(1 for x in d["flash"] if TXT_YAWN in x) == 1,
                    [x for x in d["flash"] if TXT_YAWN in x])

        print("\n" + "=" * 68)
        # ⚠️ 2026-09-26：这一段的档位是 **L2**（`l_eye = 2`，闭眼规则给的），
        #    不是 `l2 = 1` —— 支路二在此处只到 1，顶不上去。所以 banner 上是
        #    `NOTE_FACE[2]`「检测到持续闭眼，疲劳征兆」那一句。
        print("D. 轻度段里的**长时间闭眼桥段**（t≈65，闭眼规则顶到 L2、闸门开着）")
        r = await seek(S, SEEK_EYES)
        got, d = await wait_alarm(S, TXT_EYES)
        worst |= ck("★ 横幅报出「%s…」" % TXT_EYES, got,
                    "items=%s hidden=%s" % (d["items"], d["hidden"]))
        # ★ 而且必须是**闭眼规则**那句，不是支路二那句 —— 见文件头 ② 的出处。
        worst |= ck("★ 是闭眼规则那一句，不是支路二的「闭眼时间变长」",
                    not any(m in x for x in d["items"] for m in TXT_EYES_MODEL),
                    d["items"])
        worst |= ck("   换了一个 kind 就该再弹一次 toast",
                    any(TXT_EYES in x for x in d["flash"]), d["flash"][-3:])
        # 这一拍**只有闭眼**：两个桥段之间隔着 7 s（55 -> 62），
        # `yawn_sec` 在这个点上已经落回 0。所以横幅该是一行、内容是闭眼那句 ——
        # 两行都挂着的话说明 yawn 的判据没跟着 `yawn_sec` 一起落。
        worst |= ck("   t≈65 上只剩闭眼这一条（哈欠的判据已落回）",
                    len(d["items"]) == 1 and TXT_EYES in d["items"][0]
                    and not any(TXT_YAWN in x for x in d["items"]),
                    d["items"])

        print("\n" + "=" * 68)
        print("E. ★★ 本次改动的核心：轻度疲劳那一格**是支路二给的**")
        # `?sev=mild` -> PIN_SEEK = 45 s，落在轻度段（40~80）里、两个桥段之前。
        await S.goto("/index.html?sev=mild", 3.2)
        d = await S.js(PROBE)
        worst |= ck("★ 整页配色是 mild（黄）", d["sev"] == "mild", d["sev"])
        worst |= ck("★ 大标题是「轻度疲劳」", d["name"] == "轻度疲劳", repr(d["name"]))
        # ⚠️ 这一条的靶子是"**别**把疲劳程度接回 `level_name`（安全通道那条 L 编号）"：
        #    这一档的 `l1` 是 0，`level_name` 是「清醒」—— 谁把它接回去，
        #    屏幕就变成"大标题说轻度疲劳、顶部的条却只画一格"，而**只看大标题
        #    验不出来**。★ 2026-09-24 深夜：文字那行没了，靶子换成**条宽**
        #    （`DEG_W.mild = 0.45`）；接回 `level_name` 的话这里会读到 12%。
        worst |= ck("★ 顶部疲劳程度条 = 45%（轻度那一档的宽度）",
                    d["barl"] == "45%",
                    f"读到 {d['barl']!r} —— 条宽取的是 DEG_W[severity]"
                    f"（清醒 12 / 轻度 45 / 中度 66 / 重度 88）")
        # ★★ 归因（"这一档必须来自支路二、不是支路一"）**不在这里读** ——
        #    概率条整块搬走了，首页上 `#vNormal` 已经不存在。
        #    它接在这一节最后（`/monitor.html` 那一段），见下面 `SEEK_MILD` 那块。
        # ★ 头姿那一行**不再由概率驱动**了（2026-09-25 二类合并的后果：类别只剩
        #   两个，"低头 vs 点头"的区别归行为量）。所以这一条从"必须是正常"放宽成
        #   "不许是疲劳姿态"—— 屏上那一格现在的词面来自 `d_pitch`/`nod`
        #   （`ui/state.py` 的 attention → app.js 的 POSE_OF），demo 在 45 s 的
        #   d_pitch 是 6.4°（刚好过 `HEAD_RANGE*0.5 = 6`），所以是「略低头」，
        #   那是**如实**的：那一段的头确实比清醒段低 0.9°。
        #   ⚠️ 别为了让它读回「正常」去抬 `HEAD_RANGE` 的那条半值线 —— 那是拿参数
        #      去凑一句屏上的文案，不是拿判据去量它。
        worst |= ck("   头姿那一行不许是低头/点头（这一档没有疲劳姿态）",
                    d.get("pose") not in (None, "低头", "点头"),
                    f"读到 {d.get('pose')!r}")
        worst |= ck("   45 s 在两个桥段之前，这一段不该有告警",
                    d["hidden"] is True, f"hidden={d['hidden']} items={d['items']}")

        # ★★ 上面「归因」那条的正面那一半：**去监测详情页读概率**。
        #    判据是"支路一在这一档仍旧判正常" —— 二类概率条里 normal 仍占大头
        #    （demo 在 45 s 上给的是 0.77），P(疲劳) 压在 0.25 那条线附近。
        #    ⚠️ `0.25` 不是从哪个常量抄的，是留的余量（远低于 ENTER_TH 0.60）。
        #    ⚠️ `?sev=` 在那一页**不生效**（它走 `app.js` 的 onHello，那一页不加载
        #       app.js），所以借页面自己那条 WS 用 `seek()` 拨到同一刻
        #       —— 和 G 段拨 SEEK_CLEAN / SEEK_YAWN 是同一手法。
        #       首页和那一页各有各的那条演出连接，但 demo 的演出是**t 的函数**，
        #       所以同一刻读出来的数逐位相同。
        #    ★ 2026-09-25 第八次改版：`#bvNormal` 现在在**新页 `/monitor.html`**
        #       的「行为特征」那一节里（驾驶监测页那五个页签整块搬过去了，
        #       `detail.html` 的「更多」变成一条跳过去的链接）⇒ 靶子页换掉。
        #       那一节在新页上**不再是 hidden 的页签**，所以这里连"要不要先点开"
        #       都不用讨论了；读法仍用 `textContent`（不看可见性），和以前一样。
        #       ⚠️ `_check_grade.py` 的 C/D 段是同一天改的同一处，别只改一边。
        await S.goto("/monitor.html", 2.8)
        r = await seek(S, SEEK_MILD)
        worst |= ck("   监测详情页也发出了 seek", r == "ok", r)
        pn = pf = None
        for _ in range(8):                      # 拨完表要等下一拍才反映到屏上（8 Hz）
            await asyncio.sleep(0.4)
            dd = await S.js(PROBE)
            # ⚠️ `.get` 两级：`bvNormal` 读不到时 `JSON.stringify` 会把那个键整个
            #    丢掉，`dd["pb"]["normal"]` 是 **KeyError**，整个脚本当场崩 ——
            #    而崩掉的表现（一段 traceback）长得不像"指错页了"。
            #    `_check_grade.py` 的 D 段就在 2026-09-25 这么崩过一次。
            pb = dd.get("pb") or {}
            pn, pf = pct(pb.get("normal")), pct(pb.get("fatigue"))
            if pn is not None:
                break
        worst |= ck("★★ 但支路一在这一档仍旧判「正常」——所以这档只能是支路二给的",
                    pn is not None and pn >= 0.60 and pf is not None and pf < 0.25,
                    f"P(正常)={pn} P(疲劳)={pf}"
                    f" —— 这一条就是用户那句「轻度疲劳就是支路2的闭眼/打哈欠」的判据")

        print("\n" + "=" * 68)
        print("F. 重度疲劳的两段：低头（phone）和点头（fatigue）落**同一档**")
        # ⚠️ 二类合并**没有改这两个段名**（`?sev=phone` / `?sev=fatigue` 是演出
        #    对外的约定，改了就有一堆脚本以"页面锁不上"的形式红）。改的是**含义**：
        #    这两段在**类别**上已经是同一类（都判疲劳），只靠**行为量**区分 ——
        #    所以下面那行头姿才是这两段唯一的差别，它现在由 `d_pitch`/`nod` 给。
        for key, want_pose, want_alarm in (("phone", "低头", False),
                                           ("fatigue", "点头", True)):
            await S.goto("/index.html?sev=%s" % key, 3.2)
            d = await S.js(PROBE)
            worst |= ck("[%s] ★ 整页配色是 severe（红）" % key,
                        d["sev"] == "severe", d["sev"])
            worst |= ck("[%s]   大标题是「重度疲劳」" % key,
                        d["name"] == "重度疲劳", repr(d["name"]))
            # ⚠️ 这句里有 `%` 又有 `%s` 占位 —— 百分号要写成 `%%`，否则 Python
            #    当场 `not enough arguments for format string`（这个坑我踩过一次）。
            worst |= ck("[%s]   顶部疲劳程度条 = 88%%（重度那一档的宽度）" % key,
                        d["barl"] == "88%", repr(d["barl"]))
            # 低头 / 点头是**同一个档位、同一个类别下的两种行为**，区别只在这一行 ——
            # 它由**行为量**驱动（`ui/state.py` 的 attention：`d_pitch` 过 12 是低垂，
            # 再过 `nod >= 5` 是点头；app.js 的 POSE_OF 换成短词），所以这一条同时
            # 证明了"两段演的不是同一件事"。（两段的行为量不随时间变，
            # 所以段内任意时刻都远过那两条线：实测 d_pitch 18.5 / 23.0，nod 3.0 / 9.0。）
            worst |= ck("[%s]   头姿那一行是「%s」" % (key, want_pose),
                        d.get("pose") == want_pose, repr(d.get("pose")))
            # 低头那一段的支路二数字**故意留在正常档**（真实低头的人眼睛不疲劳），
            # 所以它**不该**有闭眼告警；点头那一段反过来（l2=2，眼睛也累了）。
            # ⚠️ 这一对是**两条独立判据**，别合并成一条"重度就有告警"。
            if want_alarm:
                worst |= ck("[%s]   支路二在这里也报了闭眼（l2=2）" % key,
                            any("闭眼" in x for x in d["items"]), d["items"])
                # ★ 2026-09-26：这一档的 `src` 是 **"head"**（低头规则把级别顶到 L3），
                #   不是 "eye" —— 所以这条闭眼只能是**支路二**报的，
                #   必须用支路二那句「闭眼时间…变长」，**不许**说「检测到持续闭眼」。
                #   这是 ② 的另一半：D 段验"规则不许说成模型那句"，这里验反过来。
                worst |= ck("[%s]   而且用的是支路二那句，不是「%s」" % (key, TXT_EYES),
                            not any(TXT_EYES in x for x in d["items"]), d["items"])
            else:
                worst |= ck("[%s]   低头段不该有闭眼告警（支路二数字仍在正常档）" % key,
                            not any("闭眼" in x for x in d["items"]), d["items"])

        print("\n" + "=" * 68)
        print("G. 04 驾驶监测页上也挂得起来（同一份 XQ.alarms 的第二个宿主）")
        await S.goto("/detail.html", 2.8)
        print("  取证探针:", await hook(S))
        d0 = await S.js(PROBE)
        worst |= ck("      detail 也有告警位", d0["hasHost"], d0.get("hasHost"))
        # ⚠️ **这里不断言"一开始是收着的"**（第一版就是那么写的，报红了）。
        #    驾驶监测页没有 `?sev=` 那套定位，它打开时演出时钟在哪儿完全取决于
        #    前一段测试把它留在哪 —— 上一次导航停在 L3（那一档 l2=2），
        #    所以驾驶监测页一打开横幅**本来就该是亮着的**。把"碰巧在干净段"
        #    写成判据，就是一个会随测试顺序变红的假判据。
        #    真正要验的是"判据没了它就收"—— 所以先拨到干净段，再拨到桥段。
        r = await seek(S, SEEK_CLEAN)
        worst |= ck("      页面真的发出了 seek", r == "ok", r)
        ok, d = await wait_alarm(S, None, timeout=3.0)
        worst |= ck("★ detail 上判据没了也会收（不是只会亮）", ok,
                    "items=%s hidden=%s" % (d["items"], d["hidden"]))
        r = await seek(S, SEEK_YAWN)
        got, d = await wait_alarm(S, TXT_YAWN)
        worst |= ck("★ detail 上的横幅也报出来了", got,
                    "items=%s hidden=%s" % (d["items"], d["hidden"]))

        # ★ 布局：驾驶监测页的驾驶员卡也是 overflow:hidden 的，同一条判据
        worst |= await check_box(S, "detail")

        print("\n" + "=" * 68)
        print("J. 控制台零报错")
        worst |= ck("无 error / warning", not S.errs, S.errs[:4])

    print("\n" + "=" * 68)
    print("**%d 项不过，见上**" % worst if worst
          else "**全绿**（截图仍要人眼看：横幅位置、黄警好不好看）")
    return worst


if __name__ == "__main__":
    # ⚠️ 退出码要反映结果（这个项目的老毛病：脚本跑最后一行就结束、失败也 exit 0）。
    #    但**读输出行的纪律不变** —— exit 0 只说明没抓到已知问题。
    sys.exit(1 if asyncio.run(main()) else 0)
