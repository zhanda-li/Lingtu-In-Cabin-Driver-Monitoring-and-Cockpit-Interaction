"""小瑞（10 动作 + 循环动图 + 品牌标志组）· 浏览器侧验收（headless Edge + CDP）。

    python _scratch/_check_mascot.py 8790     # 端口要和起着的那份服务一致

判据：
  0 **静帧就是动图的第 0 帧**（同一张图冻住）：`xiaorui_live_still.png` 与
    `xiaorui_live.webp` 的帧 0 比，三条一起满足才算过 —— ① alpha 通道逐字节相同
    （WebP 的 alpha 无损，它是真正定身份的那条）；② 预乘 RGB 的**平均**差 ≤4；
    ③ 帧 0 是 25 帧里**最接近**的那一帧。这条只有 Python 侧能做，但它撑着
    reduced-motion 那条"换过去看不出跳变"的说法 —— 不验就是空口说。
    ⚠️ 判据**不是**"RGB 最大差接近 0"，第一版那么写会误报 255，详见函数里的注释。
  A ★ 会动的槽拿到的是**循环动图**而不是偷偷退回 SVG/静态图；底图按槽分开：
      chat 8rem = xiaorui_live.webp · 对话栏 3.6rem = 方形头像版 ·
      封面立绘位 = xiaorui_hero.png（连 bind 都没调，只吃 CSS 呼吸）。
      ⚠️ **首页 6.6rem 的底图看不到** —— 它被档位表情（hold:0）永久占着，DOM 里
         读到的永远是 live（动图）/think/wow/heart（四档，见 SEV_ACT）。
      底图那半边改由 `check_bind_bases()` 读源码验。
  A2 ★ **动图真的是多帧的**，而且能解出第 1 帧：用 `ImageDecoder` 读
      `tracks.selectedTrack.frameCount`（比"换图"强，直接验到帧数）+ 真解一帧要
      拿到非零尺寸。判据用帧数不用"看起来在动"。
  B ★ 换姿态真的换了：`XQ.mascot.play('happy')` 之后 `img.src` 指向 happy、
      槽上挂着 `data-act="happy"`、`getComputedStyle` 的 animation-name 是 xqHappy。
  B2 ★ **10 个动作逐个验**：每个名字 `play()` 之后 src 和 data-act 都要对上那一张，
      而且算出来的动画名必须是这条动作自己的（不是 xqIdle）—— 名字拼错/图缺失/
      CSS 少一条 keyframe，三种错都在这条上现形。
  C ★ 同名重播会**从头再来**（live.js 那句 removeAttribute 三步）：连放两次 go，
      第二次的 `animationstart` 事件数必须 +1 —— 不加那三步点第二次没反应。
  D ★ **到点回底图**：等过 hold 之后 `data-act` 被摘掉、src 回到**动图**、
      animation-name 回到 xqIdle（待机呼吸）。
  E ★ 手点循环：连点 10 下，`data-act` 要**把十个动作都走一遍**（不是原地打转）。
  K ★ 状态表情不被事件类动作顶掉：`react('sev:mild')` 那档小瑞最后要停在 think
      而不是底图（TTS 回调几秒后才来的那次顶掉，是本轮修过的 bug 的最小复现）。
  F ★ 档位联动走**生效档位**：`?sev=` 四档各开一次，小瑞的图要和
      `document.body.dataset.sev` 一一对应。
      ⚠️ 原来这里还单跑一次 `?sev=mild` 验它"段名有、级别没有、落到 L0" ——
      「只做疲劳」之后 mild 是真档位了（轻度 = 支路二判的），那个特例连同
      那条断言一起删了。别照着旧记录加回来。
  G 静态槽：手机四格 4.6rem 指向头像版且真的加载成功；
      detail 3.4rem 那一格**已经改口**了 —— 它是 `bind()` 过的**会动槽**
      （底图 = 循环动图），不再是原来的 `#avaImg` 静态头像。见那段注释。
      ★ 2026-09-25 晚：nav 那一格**回来了**（`#navArtImg`，显式 `base:'head'`）——
         它是全站**唯一**能证明"显式传 base 就真的生效"的靶子
         （默认值是待机动图，两张图在 DOM 上分得开）。
         ⚠️ 09-24 那天 nav 整页删除，这条跟着没了、`check_bind_bases()` 只剩半边；
            两件事是**同一件事**，别再让它们分开走。
  H ★ 顶栏品牌那一格是**一张整 lockup**：`lingtu_lockup.png` 加载成功 +
      品牌名写在 `alt` 里（2026-09-24 晚那两行字进图了，DOM 上只剩 alt）、
      且 `.lingtu-txt` 计数为 0（没有谁把文字又排一遍）；
      封面 h1 的遮罩图 lingtu_wordmark_mask.png 照旧能加载。
  I ★ `prefers-reduced-motion` 命中时：① 所有 CSS 动画是 none；② 动图槽的**底图
      退回静态 PNG**；③ 整个页面**一次都没请求过那个 webp**。③ 是这条的重点 ——
      动画 WebP 是 `<img>` 自己的帧，CSS 关不掉，只能靠 JS 换图，所以"没请求"
      才是真的降级了，光看 animation-name 看不出来。
  J 全程零控制台报错/警告。

⚠️ 这条为什么在 **chat.html** 上验 B/C/D/E/B2，不在 index.html 上验：
   index 的 `render()` 每帧都可能推新档位进来触发 `react()`，会把正在演的动作
   排到后面 —— 那是对的（排队机制），但**测起来不确定**。chat 页只有用户交互
   才会触发动作，静止时那个槽是干净的。F 需要真数据，所以 F 留在 index。

⚠️ 这个脚本**证明不了**的（只有人眼说了算，别拿它冒充）：
  1. 循环动图**自不自然**、那个羽化椭圆的边在深色底上会不会显出「一个圆盘」；
  2. 10 个姿态在新尺寸（约 115x120 放大到 236px）下**一眼能不能分出来**；
  3. 品牌标志在顶栏近黑底上的冰蓝渐变够不够亮、认不认得出；
  4. 封面立绘位那版（新素材 137px 源放大 3x vs 旧的锐利但更老）哪版好看。
  这四条看 `_scratch/_shot_pages.py` 截的那几张图（`_scratch/_shots/`）。

⚠️ 它 `from _check_pages import Session`，那个文件是**在 import 时**用 sys.argv[1]
   算 BASE 的 —— 传进来的端口必须就是服务的端口。

⚠️ 起服务（摄像头别开 —— 这个脚本只用到 demo 源）：
   D:\\Anaconda3\\envs\\dms\\python.exe ui\\server.py --port 8790 --source demo
"""

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session, ck as _ck_raw   # noqa: E402

# 失败项台账（2026-09-24 晚加）。**为什么**：这套跑一次六十来行输出，2026-09-24
# 有一次退回码非零而失败行淹没在中段、只留了尾部 40 行的人（我）看不到是哪一条，
# 只能靠"两轮都绿"来猜 —— 猜是不可接受的。现在不管输出被怎么截，失败项都会
# 在**最后**重印一遍。⚠️ 只包装本脚本，不去动 `_check_pages.py` 里的原件：
# 别的套件共用它，改那里会连坐。
FAILED = []


def ck(name, ok, note=""):                     # noqa: F811
    if not ok:
        FAILED.append(f"{name.strip()}  {note}")
    return _ck_raw(name, ok, note)


EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
ASSETS = Path(__file__).parent.parent / "ui" / "web" / "assets"

# 档位 -> 动作图。**和 live.js 里那张 MAP 表是同一份口径**，故意在这里重写一遍：
# 从 MAP 里读的话，映射写错了这个脚本会跟着一起错（自证）。
# ★ 2026-09-24 深夜「只做疲劳」：键**回到四档档位名**（normal/mild/moderate/severe）。
#   上一版是支路一的类别名（normal/glance/phone/fatigue）—— 那一版是"安全级别"那条轴，
#   三类之后中间两档永远出不来，所以又跟着 severity 走了，见 live.js 的 MAP 段注释。
# ⚠️ 现在这四个键**既是档位名、也是 `?sev=` 的段名**里的四个（第 5 个段名是
#   `phone`，它的档位是 `severe`）—— 所以下面 F 段可以拿 `?sev=` 起页、
#   同时预期 `body[data-sev]`。别照着上一版"两个名字差一个 mild"的印象改。
SEV_ACT = {"normal": "live", "mild": "think", "moderate": "wow", "severe": "heart"}
# ★ 2026-09-24：`normal` 从 `happy` 改成 **`live`（待机循环动图）**。
#   理由：清醒档本来就是**待机**状态，四档都按住静止立绘的话（原来那样），
#   实测座舱首页 30 s 里 0% 时间是动的 —— 用户要「让小瑞动起来」。
#   轻度/中度/重度**仍然按住**对应表情（那三个是"有事发生"的状态）。
#   ⚠️ `live` 不是动作名、是**底图名**，所以它的文件名是 `xiaorui_live.webp`
#      而不是 `xiaorui_live.png` —— 凡是拼 `xiaorui_%s.png` 的地方都要走 sev_src()。


def sev_src(act):
    """档位动作名 -> 它在页面上该显示的那个文件名。

    ⚠️ 别到处手拼 `f"xiaorui_{act}.png"`：`live` 是**底图**，扩展名是 `.webp`
       （`XQ.mascot` 里 `src()` 那条 IDLE 分支），拼错了这条断言会一直红。
    """
    return "xiaorui_live.webp" if act == "live" else f"xiaorui_{act}.png"

# 10 个动作名。**顺序 = live.js 里 ACTS 的顺序**（手点循环就按这个走），
# 同样是故意重写一遍。live 不在里面：它待机底图，不是动作。
# ⚠️ 11.png「动态动作」那 6 格（wave/go/navi/cheer/celebrate/love）**不在**这里：
#    白底白身抠不干净，身体被掏成洞，**没采纳**。见 live.js 的 ACTS 那一段。
ACTS = ["happy", "wink", "wow", "shy", "angry", "think", "sad", "sleep",
        "like", "heart"]

# 每个动作名 -> 它该跑的那条 keyframe。**这张表是手写的映射，不是从 CSS 里推的** ——
# 推的话 CSS 里少一条、名字对不上都验不出来，那就白验了。
ACT_KF = {n: "xq" + n.capitalize() for n in ACTS}


def check_still_is_frame0(webp_name="xiaorui_live.webp", still_name="xiaorui_live_still.png"):
    """Python 侧：`*_still.png` 必须就是同名 `*.webp` 的第 0 帧。

    ★ 2026-09-24：**两对都要验**（`live` 那对给座舱、`hero` 那对给封面）。
      封面原来挂的是静态 `xiaorui_hero.png`，那天改成动图 `xiaorui_hero.webp`
      + reduced-motion 退回 `xiaorui_hero_still.png` —— 第二对是**新加的**，
      只验第一对的话，"封面那张静帧是不是帧 0"就没人看。

    这条是 I 那一项的前提。I 证明的是"命中 reduced-motion 时换成了静态图"，
    但**换成哪个静态图**才决定会不会跳变 —— 换一张别的静帧照样能过 I，却会在
    加载瞬间明显闪一下。所以这条单独拎出来用像素比，浏览器侧比不了。

    ⚠️ 判据是**三条一起**，而且**不是**"RGB 最大差 ≤ 4" —— 第一版就是这么写的，
       报 `最大像素差 = 255`，差点让我以为静帧取错了帧。实际上完全没问题，
       两处都是判据本身错了：
       1. **透明区的 RGB 是垃圾值**。图外面那 22248 个 alpha=0 的像素里，webp 帧 0
          的 RGB 均值 8.5、静帧是 0 —— 那 255 的差全来自这里，而它们**根本看不见**。
          所以要比就比**预乘 RGB**（RGB × alpha），alpha=0 的地方自然归零。
       2. **有损编码的差集中在低 alpha 的羽化边上**。WebP 的 RGB 是有损(YUV 4:2:0)、
          alpha 是无损(VP8L)，从预乘存储反解回直通 RGB 会放大舍入误差：alpha≈9 的
          像素上差 30 也不奇怪，但不透明度 3.5% 的地方肉眼是看不出来的。
          → 所以量**均值**不量最大值。
    真正定身份的是 **alpha 通道**：WebP 的 alpha 是无损的，帧 0 与静帧逐字节相同
    （最大差 0），而它在动的时候**别的帧 alpha 差 200 以上**（人物在移动）。
    所以最后的判据是「只取 alpha 与尺寸都一致 + 预乘 RGB 平均差很小 + 帧 0 是 25 帧
    里最接近的那一帧」，三条缺一不可 —— 尤其第三条，不验的话"随便挑了张差不多的
    静帧"也能过前两条。
    """
    import numpy as np
    from PIL import Image
    webp = ASSETS / webp_name
    still = ASSETS / still_name
    if not (webp.exists() and still.exists()):
        return False, "有一张不存在"
    a = Image.open(webp)
    n = getattr(a, "n_frames", 1)
    s = np.array(Image.open(still).convert("RGBA")).astype(np.float64)
    if Image.open(still).size != a.size:
        return False, f"尺寸不同 {a.size} vs {Image.open(still).size}"
    ps = s[:, :, :3] * s[:, :, 3:] / 255.0          # 预乘，看不见的地方不算数
    rows = []
    for i in range(n):
        a.seek(i)
        f = np.array(a.convert("RGBA")).astype(np.float64)
        d = np.abs(f[:, :, :3] * f[:, :, 3:] / 255.0 - ps).max(axis=2)
        rows.append((i, float(d.mean()), float(np.abs(f[:, :, 3] - s[:, :, 3]).max())))
    rank = sorted(rows, key=lambda r: r[1])
    best, runner = rank[0], rank[1]
    f0 = rows[0]
    ok = (best[0] == 0                 # 帧 0 是最接近的那一帧（不是"随便一张"）
          and f0[2] <= 1.0             # alpha 无损、逐字节相同
          and f0[1] <= 4.0)            # 预乘 RGB 平均差在编解码噪声内
    # 报**第二名**而不是"最接近的那帧"：第一名永远是 0 号，报它等于什么都没说；
    # 报第二名才看得出帧 0 是**独占**的（差距越大，结论越硬）。
    return ok, (f"帧0: 预乘均差={f0[1]:.2f} alpha最大差={f0[2]:.0f} | "
                f"第二名是帧{runner[0]}（均差={runner[1]:.2f}，"
                f"是帧0的{runner[1]/max(f0[1],1e-6):.1f}倍）| 共 {n} 帧"
                + ("" if ok else "  << 静帧不是帧 0，reduced-motion 下会闪一下"))


def check_bind_bases():
    """谁传了 `base` 覆盖、谁没传 —— **读源码**，不在浏览器里看。

    ⚠️ 为什么要读源码而不是看 DOM：**首页那个槽的底图在 DOM 里观测不到**。
       `?sev=` 四档映射出来的表情都是 `hold:0`（一直保持在脸上），也就是说
       slot.state 一旦被设上就**再也不会回默认底图**，所以 index 上读到的永远是
       `xiaorui_live.webp / think / wow / heart` 这四个之一，永远不是"默认底图"。
       ⚠️ 但 `normal` 那档现在**就是** `live`（待机底图本身），所以这一格上
       "src 是不是底图"彻底看不出区别了 —— F 段改看 `data-act` 才补回来。
       第一版在这里断言"首页底图也是循环动图"，恒假 —— 那**不是**代码错，
       是这个判据没法成立（`_check_mascot.py` 第一次跑就报了这一条）。

    ★ **2026-09-25 晚：那半边回来了。** 这个函数靠 `nav.html` 那一格验
       "**显式写了 `base:'head'` 就真的生效**"：那页的槽既显式传了 `base`，
       又**不跑 DMS 的 render()**（没连档位事件、没有档位事件盖底图），
       所以它的底图在 DOM 里是**看得见**的 —— G 段那一条是硬证据。
       ⇒ `want` 现在是三行，`nav.html` 那行 `need_base=True` 是**唯一**验右半边的一条。

    ⚠️ 靶子必须同时满足两条：**显式传 base** 且 **不跑 render()**
       （跑了档位事件就把底图盖掉了，DOM 里看不到）。

    ⚠️⚠️ **2026-09-24 → 09-25 之间这个函数只剩一半**（当时 nav 整页删除，全站
       再没有页面显式传 `base:`，`want` 两行都是 `need_base=False`，只能验
       "不该写的没写"）。**别再把它删回去** —— 它就是靠 nav.html 那一页撑着的：
          · 那次删页之后记的候选 `media.html` **不是**能用的靶子，两条理由各自都够：
            ① 它连了 WebSocket（疲劳联动那件事，见 media.html 文件头），
               "没有档位事件"这一条不成立；
            ② 它的 bind 那一行压根没传 `base`，要拿它验"显式传 base 生效"，
               得先给它加一个 `base:`（那就动了产品代码，不是为了验而验）。
          · 所以 `nav.html` 上那个 `{base:'head', cycle:true}` **不许顺手删掉**：
            删了它，这个函数就**静默**退回只剩一半（绿，但什么也没验）。
    """
    WEB = ASSETS.parent
    want = [("app.js", "mascotImg", False),        # 首页 6.6rem：不传 base = 用动图
            ("chat.html", "tipImg", False),        # chat 8rem：同上
            # ★ 导航页：**显式传 base** 且不跑 render() —— 全站唯一的右半边靶子
            ("nav.html", "navArtImg", True)]
    bad = []
    for fn, imgid, need_base in want:
        txt = (WEB / fn).read_text(encoding="utf-8")
        line = next((l for l in txt.splitlines()
                     if "mascot.bind(" in l and f"'{imgid}'" in l), None)
        if line is None:
            bad.append(f"{fn}: 找不到 {imgid} 的 bind")
            continue
        has = "base:" in line
        if has != need_base:
            bad.append(f"{fn}/{imgid}: base 覆盖{'少了' if need_base else '多了'}")
    return not bad, ("；".join(bad) if bad else
                     "首页/chat 不传 base（吃动图）；nav 显式传 base:'head'"
                     "（两半都验了，见本函数注释）")


async def jsawait(S, expr):
    """`await` 一个返回 Promise 的表达式（S.js 不支持 awaitPromise）。"""
    r = await S.cmd("Runtime.evaluate",
                    {"expression": expr, "returnByValue": True, "awaitPromise": True})
    res = r.get("result", {})
    if "value" not in res:
        return None
    v = res["value"]
    return json.loads(v) if isinstance(v, str) and v.startswith(("[", "{")) else v


def imginfo(sel):
    """一段取"这个槽现在显示哪张图 / 挂的什么动作 / 跑什么动画"的表达式。"""
    return ("JSON.stringify((()=>{const e=document.querySelector(%r);"
            "if(!e) return null; return {src:(e.getAttribute('src')||'').split('/').pop(),"
            "nat:e.naturalWidth, act:e.dataset.act||null,"
            "clk:getComputedStyle(e).animationName,"
            "hostCursor:e.parentNode.style.cursor||null};})())" % sel)

async def imgat(S, sel):
    """`imginfo` 的 Python 侧包装：**元素不存在一律回 None**。

    ⚠️ 为什么不直接 `await S.js(imginfo(sel))` 当 dict 用 —— `imginfo` 里
       `JSON.stringify(null)` 出来的是字符串 `"null"`，而 `Session.js`
       **只在以 `[`/`{` 开头时**才 `json.loads`（见 _check_pages.py:177 那段注释），
       `"null"` 不满足，于是它原样返回那个 Python 字符串。此时 `d["src"]`
       报的是 **`TypeError: string indices must be integers`** —— 看着像脚本坏了，
       真相是"你查的那个元素已经不存在了"（2026-09-24 detail 的 `#avaImg`
       随那页改版消失，G 段就是这么崩的，查了半天才发现是选择器过期）。
    """
    v = await S.js(imginfo(sel))
    return v if isinstance(v, dict) else None


async def settle(S, sel, want, timeout=14.0, want_act=None):
    """等某个槽稳定在 `want` 这张图上（动作类的会自己回底图，所以要等它停）。

    ★ 2026-09-24：`normal` 档现在映射到 **`live`（待机底图本身）**，于是
      "src == want" 这一条**失去了鉴别力** —— 那一格的底图本来就是
      `xiaorui_live.webp`，就算 `sev:normal` 一次都没触发过，src 也照样对。
      所以再加一条 `want_act`：`data-act` 挂着 `live` 才证明那次 `play('live')`
      真的跑过（`playOne` 会 `dataset.act = name`，hold 0 又不摘，见 live.js:480）。
      另三档仍然只比 src —— 它们的动作图与底图不同，src 本身就够硬。

    ⚠️ 为什么要等而不是读一次：`render()` 是 8 Hz 的流，动作之间还会互相排队
    （`react()` 的 pending），中间**必然会**经过几个别动作的瞬间 —— 比如切数据源
    触发的那下「出发」（hold 2s）。读一次就断言等于断言"我读的那一瞬没在演别的"，
    那是测时序不是测行为。这里改成轮询到稳定，并且**把中间路过的都记下来**，
    失败时能看出它到底卡在哪儿。
    """
    seen, ok = [], False
    for _ in range(int(timeout / 0.5)):
        st = await imgat(S, sel)
        cur = st["src"] if st else None
        if not seen or seen[-1] != cur:
            seen.append(cur)
        ok = cur == want and (want_act is None or (st and st["act"] == want_act))
        if ok:
            return True, seen
        await asyncio.sleep(0.5)
    return False, seen


async def main():
    worst = 0

    # ================================================== 0 · 静帧 = 动图帧 0
    print("\n=== 0 静帧就是动图的第 0 帧（Python 侧像素比）===")
    # ⚠️ 这里原来还有一对「封面立绘」（`xiaorui_hero.webp` / `xiaorui_hero_still.png`）。
    #   ★ 2026-09-25：封面**不用循环动图了**，改成静止立绘 + 点一下换姿势
    #   （见 A3 段），那两个文件**没有任何页面再引用**。留着这一对等于
    #   "验一个死文件" —— 它绿不绿和用户屏幕上是什么已经无关了。所以删掉。
    #   ⚠️ 那两个文件**还在盘上**（`ui/web/assets/`），是上一轮比心片段的产物；
    #      真要清理得连 `_mk_xiaorui_heart.py` 一起决定（见那个脚本的文件头）。
    for wn, sn, lbl in (("xiaorui_live.webp", "xiaorui_live_still.png", "座舱待机"),):
        ok, note = check_still_is_frame0(wn, sn)
        worst |= ck(f"★ 静帧与动图帧 0 是同一张（{lbl} {wn}）", ok, note)

    async with Session(9421) as S:
        # ================================================== A · chat 8rem
        print("\n=== A 会动的槽拿到的是循环动图 ===")
        await S.goto("/chat.html", 2.6)
        tip = await imgat(S, "#tipImg")
        worst |= ck("chat 8rem 真图加载成功",
                    bool(tip) and tip["nat"] > 0, f"naturalWidth={tip['nat']}")
        worst |= ck("真图来了就把内置 SVG 藏了",
                    (await S.js("document.querySelector('#tipHost').hidden")) is True,
                    "不藏的话真图和 SVG 会叠在一起")
        # ⚠️ 这两条**都必须等那次"认领挥手"演完再读**：认领槽的时候会先播一次
        #    一个动作（hold 2000），2.6s 那次读正好卡在它里面 —— 那时
        #    `data-clk` 是动作动画名、`src` 是动作那张一次性 PNG。
        #    ★ 2026-09-25 修：原来**只**给下面那条 clk 断言加了等待，src 那条
        #    直接断言第一个读到的值，于是它随机报红（撞到一次 `xiaorui_happy.png`）。
        #    它红的理由是"正好读在挥手那一帧"，和它真正要守的东西（**底图被换成
        #    静态图**）毫无关系 —— 典型的假红，会被人当成"动图挂了"去查。
        #    现在两条共用同一个"等到真待机"的循环，各自仍然咬各自的：
        #      · src  == xiaorui_live.webp  → 待机底图被换掉就红；
        #      · clk  == xqIdle 且无动作   → 待机动作名/状态机坏了就红。
        tip = None
        for _ in range(12):
            tip = await imgat(S, "#tipImg")
            if tip and tip["act"] is None and tip["clk"] == "xqIdle":
                break
            await asyncio.sleep(0.5)
        tip = tip or {"src": None, "clk": None, "act": None}
        worst |= ck("★ chat 底图 = 循环动图（不是静态图）",
                    tip["src"] == "xiaorui_live.webp", tip["src"])
        worst |= ck("开场演完后回到待机呼吸 xqIdle",
                    tip["clk"] == "xqIdle" and tip["act"] is None,
                    f"{tip['clk']} / data-act={tip['act']}")

        # ================================================== A2 · 真的多帧
        print("\n=== A2 动图真的是多帧的，而且解得出画面 ===")
        dec = await jsawait(S, """(async () => {
          if (typeof ImageDecoder === 'undefined') return JSON.stringify({err:'no ImageDecoder'});
          try {
            const r = await fetch('/static/assets/xiaorui_live.webp');
            const buf = await r.arrayBuffer();
            const d = new ImageDecoder({data: buf, type: 'image/webp'});
            await d.tracks.ready;
            const t = d.tracks.selectedTrack;
            const {image} = await d.decode({frameIndex: 1});   // 真解一帧出来
            /* ⚠️ 每个值都过一遍 String()。`t.animation` / `t.repetitionCount`
               在 Edge 上**可能整个属性就不存在**，而 `JSON.stringify` 对
               `undefined` 的处理是**把这个键直接丢掉**，不是写成 null ——
               第一版没包 String()，Python 侧读 `dec['anim']` 就 KeyError 崩了，
               表现像"脚本坏了"，其实是"这个浏览器不给这个属性"。 */
            return JSON.stringify({
              frames: t.frameCount,
              anim: String(t.animation),
              rep: String(t.repetitionCount),
              hasAnim: ('animation' in t),
              w: image.displayWidth || image.codedWidth || 0,
              h: image.displayHeight || image.codedHeight || 0,
              kb: Math.round(buf.byteLength / 1024)});
          } catch (e) { return JSON.stringify({err: String(e)}); }
        })()""")
        if not dec or dec.get("err"):
            worst |= ck("★ 动图帧数 > 1", False,
                        f"读不到帧数：{dec.get('err') if dec else None}")
        else:
            # 帧数才是判据；animation/repetitionCount 只是**顺带**看看（Edge 不一定给）。
            worst |= ck("★ 动图帧数 > 1（不是一张静图）", dec.get("frames", 0) > 1,
                        f"frameCount={dec.get('frames')} · {dec.get('kb')} KB · "
                        f"animation={dec.get('anim')}(有属性={dec.get('hasAnim')}) · "
                        f"循环={dec.get('rep')}")
            worst |= ck("   解得出第 1 帧的画面",
                        dec.get("w", 0) > 0 and dec.get("h", 0) > 0,
                        f"{dec.get('w')}x{dec.get('h')}")

        # ================================================== A3 · 封面立绘位
        # ★ 2026-09-25：封面**不再是循环动图**，改成「一张静止立绘 + CSS 上下浮动
        #   （`xqIdle`），点一下换下一个姿势」。用户原话：「不要这个了 展示页变成
        #   **可点击小瑞然后换动作 从我图片里换**」。
        #
        # ★★ 2026-09-26：这一段原来咬的是**当时的**素材名 —— 「挂的是
        #   `xiaorui_pose_happy.png`」「点一下换到 `xiaorui_pose_wink.png`」
        #   「`data-act` 挂成 `wink`」。**那套对象没有了**：
        #   形象系统后来换成了 `XQ.poseDeck()` + `XQ.POSES`（`pNN.webp`，43 张，
        #   `live.js:480-590`），封面走的是同一个 deck（`cover.html:564`）；
        #   点击是「**换形象**」，`data-act` 恒为 `swap` —— 那是**弹一下**那个
        #   keyframe 的名字，不是动作名（`live.js:537` 写着为什么必须是它）。
        #   ⚠️ 所以「点了真换 / 换完挂上 / 到点摘掉 / 按 POSES 顺序走」这几条
        #   **不是"不重要了"，是搬到别处了**：`_check_posedecks.py` 在
        #   **cover.html 这一格上**（它的 `SLOTS["cover.html"]` 第一项就是
        #   `#coverMascotImg`）逐条量，而且量得比这里细（等 `onload` 再读
        #   `data-act`、按尺寸对、连点顺序、43 下回绕）。**别在这儿往回加** ——
        #   加回去就是同一件事两处各验一半，改一次要改两个地方。
        #   这里只留这一页**独有**的三条：真图加载成功（不是 404 后留着的内置
        #   SVG）、内置 SVG 被藏住、底图一开始没有 `data-act`。
        # ⚠️ 这一格**不能**用 `settle()`：封面那页没有 DMS 事件源，槽是干净的，
        #   而且它走的是 `cover.html` 自己那段 handler。
        # ⚠️ `getAttribute('src').split('/').pop()` 取的是基名。
        print("\n=== A3 封面立绘位：静止立绘 + CSS 浮动（换形象那一套在 posedecks 里）===")
        # ⚠️ `?intro=0`：封面 2026-09-25 起有一层 `z-index:9999` 的**全屏不透明
        #    品牌片头**，它会把这一段的 `.click()` **静默吃掉**（点在盖子上，
        #    页面上什么都没发生、控制台也干干净净）—— 表现会像"点一下不换姿势"。
        await S.goto("/?intro=0", 3.0)
        cv = await imgat(S, "#coverMascotImg")
        worst |= ck("   真图加载成功且没被内置 SVG 顶着",
                    bool(cv) and cv["nat"] > 0
                    and (await S.js("document.querySelector('#coverMascotSvg').hidden")) is True,
                    f"naturalWidth={cv['nat'] if cv else None}")
        # 光标是 `onReady` 里跟着 click 一起挂的，所以它同时证明"handler 真的绑上了"。
        # 少了这条，"点了没反应"和"根本没绑"长得一模一样。
        worst |= ck("   那格已经挂上 click（cursor:pointer 是 onReady 里设的）",
                    bool(cv) and cv["hostCursor"] == "pointer",
                    f"cursor={cv['hostCursor'] if cv else None}")
        worst |= ck("   底图**没有** data-act（浮动才回得来）",
                    bool(cv) and cv["act"] is None,
                    f"data-act={cv['act'] if cv else None}")
        await S.goto("/chat.html", 2.6)      # B 段要在 chat 上跑，换回来

        # ⚠️ B/C/D/E/B2 是**把一个动作单独按住、看它自己怎么走完**，所以要把页面自己
        # 的事件源掐掉：chat 页连上服务端后会「念」一句开场白，而念白的
        # `react('speak')` 是**等 TTS 合成完才来的**（几百 ms 到几秒，不定），
        # 正好会插进 D 那几秒的窗口里 —— 第一版就是这么误报的（读到 happy，
        # 因为那一刻小瑞真的在说话，而不是"没回底图"）。K 那一段专门验它，
        # 所以这里可以放心地屏蔽掉，验完再还回去。
        await S.js("window.__xqReact = XQ.mascot.react; XQ.mascot.react = () => false;")

        # ================================================== B · 换姿态
        print("\n=== B 换姿态 ===")
        await S.js("XQ.mascot.play('happy', {hold: 3000})")
        await asyncio.sleep(0.35)
        mid = await imgat(S, "#tipImg")
        worst |= ck("★ play('happy') 换了图",
                    mid["src"] == "xiaorui_happy.png", mid["src"])
        worst |= ck("★ 槽上挂了 data-act", mid["act"] == "happy", f"data-act={mid['act']}")
        worst |= ck("★ 跑的是 xqHappy 关键帧", mid["clk"] == "xqHappy", mid["clk"])

        # ================================================== C · 同名重播
        # ⚠️ 判据用 `animationstart` **事件数**，不用 `currentTime`：xqHappy 只有
        # 0.8s，等它播完（下面 D 那一步必须等）之后那条动画已经不在 `getAnimations()`
        # 里了 —— 第一次这么写就踩了这个坑，量到的是 `undefined`。
        # 而且这条**先拿换名播放做对照**：不先证明计数器数得到事件的话，
        # "没重启"和"探测器没接上"长得一模一样。
        print("\n=== C 同名重播从头开始（测 live.js 那句 removeAttribute 三步）===")
        await S.js("""(function(){
          window.__xqN = {};
          document.querySelector('#tipImg').addEventListener('animationstart',
            (e) => { window.__xqN[e.animationName] = (window.__xqN[e.animationName]||0)+1; });
        })()""")
        await S.js("XQ.mascot.play('sad', {hold: 3000})")     # 换名，做对照
        await asyncio.sleep(0.3)
        n_go = await S.js("window.__xqN.xqSad || 0")
        worst |= ck("对照：换名播放数得到一次", n_go == 1,
                    f"xqSad 的 animationstart = {n_go}（必须为 1，否则下面的结论作废）")
        await asyncio.sleep(1.6)                              # xqSad 1.3s，等它播完
        await S.js("XQ.mascot.play('sad', {hold: 3000})")      # 同名重播
        await asyncio.sleep(0.3)
        n_go2 = await S.js("window.__xqN.xqSad || 0")
        worst |= ck("★ 同名重播又数到一次（= 真的重启）", n_go2 == n_go + 1,
                    f"xqSad {n_go} -> {n_go2}"
                    + ("" if n_go2 > n_go else "  << 又没重启，回到 _probe_replay.py 查"))

        # ================================================== B2 · 10 个逐个验
        print("\n=== B2 10 个动作逐个验（src / data-act / keyframe 三样都要对）===")
        bad_src, bad_act, bad_kf, missing = [], [], [], []
        for name in ACTS:
            await S.js(f"XQ.mascot.play('{name}', {{hold: 600}})")
            await asyncio.sleep(0.16)
            got = await imgat(S, "#tipImg")
            if got["src"] != f"xiaorui_{name}.png":
                bad_src.append(f"{name}->{got['src']}")
            if got["act"] != name:
                bad_act.append(f"{name}->{got['act']}")
            if got["clk"] != ACT_KF[name]:
                bad_kf.append(f"{name}->{got['clk']}")
            if not (ASSETS / f"xiaorui_{name}.png").exists():
                missing.append(name)
        worst |= ck(f"★ {len(ACTS)} 个动作的图都在盘上", not missing, str(missing))
        worst |= ck("★ 10 个都换到了自己那张图", not bad_src, " ".join(bad_src))
        worst |= ck("★ 10 个都挂上了自己的 data-act", not bad_act, " ".join(bad_act))
        # ⚠️ 这条是**唯一**能验出「CSS 里少写了一条 keyframe」的判据：少一条的话
        # animation-name 会落空、报 none，而 src/act 全都是对的 —— 表现就是
        # "图换了但一动不动"，光看图名看不出来。
        worst |= ck("★ 10 个都跑着自己的关键帧", not bad_kf,
                    " ".join(bad_kf) + ("（落空的会报 none）" if bad_kf else ""))

        # ================================================== D · 到点回底图
        print("\n=== D 到点回底图 ===")
        await asyncio.sleep(1.2)                              # 最后一个 hold 600ms
        after = await imgat(S, "#tipImg")
        worst |= ck("★ data-act 到点被摘掉", after["act"] is None, f"data-act={after['act']}")
        worst |= ck("★ 图回到这个槽的底图（循环动图）",
                    after["src"] == "xiaorui_live.webp", after["src"])
        worst |= ck("★ 回到待机呼吸", after["clk"] == "xqIdle", after["clk"])

        # ================================================== E · 手点循环
        # ★★ 2026-09-26：这一段原来咬「连点 10 下，`data-act` 把十个动作走一遍」。
        #   **对象没有了**：`.tip-mascot` / `#tipImg` 这一格现在也是 `XQ.poseDeck()`
        #   （`live.js:642`，chat.html 那张 `气泡头像(bind)` 就是它），点击 =
        #   **换形象**（`data-act` 恒为 `swap`，那是弹一下的 keyframe 名）；
        #   而 `ACTS` 那十个动作是 `play()` 驱动、**不由点击走**（上面 B2 段刚逐条
        #   验过：src / data-act / keyframe 三样都对）。
        #   ⚠️ 「点击真的按 POSES 顺序换」现在归 `_check_posedecks.py`（它有
        #   `chat.html` 那一格的 click / 顺序 / 回绕判据）。**别往回加**。
        print("\n=== E 手点循环（已搬到 _check_posedecks.py，见上面那条说明）===")

        # ================================================== K · 状态表情不被事件顶掉
        # 这一段是 F 那次失败的**最小复现**：档位表情那档小瑞最后停在底图
        # 而不是档位表情，根因就是开场台词的 TTS 回调（几秒后才来）放了个「开心」，
        # 演完把**底图**放回来了 —— 档位表情被事件类动作顶掉、而且回不来。
        # 这里不用等 TTS，直接按那次的时间顺序手动播一遍。
        print("\n=== K 状态表情不被事件类动作顶掉（F 那次失败的最小复现）===")
        print("  还原事件源:", await S.js(
            "(function(){ XQ.mascot.react = window.__xqReact;"
            " return typeof XQ.mascot.react; })()"))
        # 记一本 react 调用台账（2026-09-24 加）。这一段红过一次，原因是
        # **TTS 的 onstart 晚到又调了一次 react('speak')**，把采样点盖住了 ——
        # 但那件事在报错行里一个字都看不出来。把台账打进 note 里，
        # 下次再有"看着像没还回去"的，一眼就能分清是还回逻辑坏了、
        # 还是窗口里多插了一次事件。
        print("  台账开工:", await S.js(
            "(function(){ window.__kT0 = Date.now(); window.__kLog = [];"
            " const w = XQ.mascot.react; XQ.mascot.react = function(ev){"
            "  window.__kLog.push((Date.now() - window.__kT0) + 'ms ' + ev);"
            "  return w.apply(this, arguments); }; return 'ok'; })()"))
        await S.js("XQ.mascot.play('happy', {hold: 800})")      # 事件类：演一会儿
        print("  react('sev:mild') 返回:", await S.js("XQ.mascot.react('sev:mild')"))
        # ★ 2026-09-24：这条**原来写的是"睡 1.3s 之后读一次，必须等于 think"**，
        #   第三次跑就假红了：台账里 816ms / 1309ms 各来了一次 `speak`
        #   （开场台词的 TTS 回调，到达时刻不定），读的那一瞬正在 happy ——
        #   **那是对的行为**（事件类动作按设计要盖住状态表情 2.2 s）。
        #   ⚠️ 也不能改成"采样期间必须抓到过 think"：那次 think 的窗口只有
        #      800→816ms 共 16ms，0.25s 采一次**必然漏掉**，还是假红。
        #   所以这条只咬**F 那个 bug 的签名 —— 掉回底图**：
        #   "最后到底落在哪个表情上"归下面那条（它会轮询到还回为止）。
        seen_k = []
        for _ in range(6):                       # ~1.5 s
            st = await imgat(S, "#tipImg")
            if st and (not seen_k or seen_k[-1] != st["src"]):
                seen_k.append(st["src"])
            await asyncio.sleep(0.25)
        worst |= ck("★ 档位表情设上后**没掉回底图**",
                    "xiaorui_live.webp" not in seen_k,
                    f"路过 {' -> '.join(str(x) for x in seen_k)}"
                    f"  —— 出现 xiaorui_live.webp 就是 F 那个 bug")
        await S.js("XQ.mascot.react('speak')")                  # 事件类又插进来
        await asyncio.sleep(0.3)
        mid = await imgat(S, "#tipImg")
        worst |= ck("   事件类动作确实盖住了它", mid["src"] == "xiaorui_happy.png", mid["src"])

        # ★ 2026-09-24 改：**不再睡死 2.4 秒后只看一眼，改成轮询到还回表情为止。**
        #
        # 为什么改 —— 它红过一次，而**代码是对的**。那天拿到的是 happy，
        # 看着像"没还回去"，其实是**采样点撞上了另一次 happy**：
        # `react('speak')` 的 hold 是 2200ms，而 TTS 的 `u.onstart` **晚到**
        # （headless 下要等合成），它又会调一次 `react('speak')`，
        # 于是 happy 又续了 2200ms，正好把 2.4 秒那个采样点盖住。
        # 用 `_scratch/_probe_speak.py` 把 react 包一层记时刻，看到的是：
        # 只调了两次（sev:mild / speak），**T+3.6 就自己还回 think 了** ——
        # 还回逻辑没问题，有问题的是"只在一个瞬间看一眼"这个判据形状。
        #
        # ⚠️ 轮询**不是放松判据，是收紧**：原来只验"2.4 秒那一刻是不是 think"，
        #    现在是"4 秒之内必须自己还回 think"，还回得晚也算过、**永不还回就红**。
        #    原来那种写法反而会给"还回得慢"发绿灯。
        # ⚠️ 别改成"睡更长一点"：那只是把撞车概率挪走，下次撞在别处又是一场排查。
        end, waited, ledger = None, 0.0, None
        for _ in range(16):
            end = await imgat(S, "#tipImg")
            if end["src"] == "xiaorui_think.png":
                break
            await asyncio.sleep(0.25)
            waited += 0.25
        ledger = await S.js("JSON.stringify(window.__kLog || null)")
        worst |= ck("★ 事件演完**还回表情**（不是还回底图）",
                    end["src"] == "xiaorui_think.png" and end["clk"] == "xqThink",
                    f"{end['src']} / {end['clk']}  等了 {waited:.2f}s；"
                    f"react 调用台账={ledger}  —— 回动图就是 F 那个 bug")

        print("\n=== chat 页控制台 ===")
        if S.errs:
            for lvl, txt in S.errs[:20]:
                print(f"  !!  {lvl}：{txt}")
            worst |= 1
        else:
            print("  OK  零报错零警告")

        # ================================================== F · 档位联动
        print("\n=== F 档位联动（比的是生效档位，不是 s.severity）===")
        S.errs.clear()
        await S.goto("/index.html", 3.0)
        for sev in SEV_ACT:                                  # 四档，顺序即表里的顺序
            await S.goto(f"/index.html?sev={sev}", 3.0)   # 等切源 + seek + 稳定
            want = sev_src(SEV_ACT[sev])
            # `live` 那档要连 `data-act` 一起要（src 与底图同名，单看 src 验不出来）
            got, seen = await settle(S, "#mascotImg", want,
                                     want_act=SEV_ACT[sev] if SEV_ACT[sev] == "live" else None)
            get = await S.js("JSON.stringify({body:document.body.dataset.sev,"
                             "xq:document.body.dataset.xqSev})")
            worst |= ck(f"?sev={sev} -> 小瑞落到 {SEV_ACT[sev]}", got,
                        f"路过 {' -> '.join(str(x) for x in seen)}  "
                        f"(生效 body.data-sev={get['body']}, xqSev={get['xq']})")
            worst |= ck("   它跟的是**生效**档位",
                        get["body"] == sev and get["xq"] == sev,
                        "PIN_ON 那条覆盖也进去了")
        # `?sev=phone` 那一段：**段名不是档位名**（段名有五个、档位只有四个），
        # 它的档位是 severe（低头看手机 = 重度疲劳）。
        # ⚠️ 上一版这里走的是 `?sev=mild`（"段名有、级别没有、落到 L0"）——
        #    轻度现在**是真档位**，所以那一版作废了；但"段名与档位名不是一一对应"
        #    这件事仍然要验一次，靶子换成 phone 这一对（mild 已经进上面那个循环了）。
        await S.goto("/index.html?sev=phone", 3.0)
        # ★ 2026-09-24 深夜：卡片里「疲劳程度」那一行并进了顶部（`#rLevel` 删了），
        #   所以这里改读**顶部那根条**的宽度（`DEG_W.severe = 88`）。
        gm = await S.js("JSON.stringify({body:document.body.dataset.sev,"
                        "xq:document.body.dataset.xqSev,"
                        "sev:String((document.getElementById('barLevel')||{style:{}})"
                        ".style.width||'')})")
        worst |= ck("?sev=phone（段名）落到 severe 档，顶部疲劳程度条是 88%",
                    gm["body"] == "severe" and gm["xq"] == "severe"
                    and gm["sev"] == "88%",
                    f"body={gm['body']} xqSev={gm['xq']} 疲劳程度条={gm['sev']!r}")
        # 首页 6.6rem 拿到的是**档位那一档的东西**。四档映射都是 hold:0，state 一旦
        # 设上就不回"默认"底图，所以这里读到的就该是 SEV_ACT 那四个之一，读到别的
        # 反倒是 bug。
        # ★ 2026-09-24：`normal` 那一档本身就是**待机动图**（`live`），所以这里
        #   允许 webp 出现在名单里 —— 不是"回了默认底图"，而是"清醒档就该是动图"。
        #   另三档仍然必须停在**静止立绘**上（它们没有对应的动图素材）。
        await S.goto("/index.html", 3.0)
        i0 = await imgat(S, "#mascotImg")
        worst |= ck("首页 6.6rem 拿到了真图", bool(i0) and i0["nat"] > 0,
                    f"{i0['src'] if i0 else None} nat={i0['nat'] if i0 else None}")
        worst |= ck("★ 首页停在档位那一档上（normal=动图，其余三档=静止表情）",
                    bool(i0) and i0["src"] in [sev_src(n) for n in SEV_ACT.values()],
                    f"{i0['src'] if i0 else None}（四档 = "
                    + "/".join(sev_src(n) for n in SEV_ACT.values()) + "）")
        ok_b, note_b = check_bind_bases()
        worst |= ck("★ bind 的 base 覆盖写得对（读源码）", ok_b, note_b)
        if S.errs:
            for lvl, txt in S.errs[:10]:
                print(f"  !!  {lvl}：{txt}")
            worst |= 1
        else:
            print("  OK  四档都零报错")

        # ================================================== G · 静态槽
        print("\n=== G 静态槽都用头像版 ===")
        S.errs.clear()
        await S.goto("/detail.html", 2.2)
        # ★ 2026-09-24：detail 这一格**不再是静态方形头像**了 —— 它是 `bind()` 过的
        #   会动槽（detail.html:843），底图和首页一样是**循环动图**。
        #   原来这里查的 `#avaImg` 在这页已经不存在：`imgat` 回 None，
        #   断言会**如实报红**（而不是像以前那样抛 `string indices must be integers`
        #   把 G 段整个打断、后面的检查一条都跑不到）。
        #   ⚠️ 判据**不能**写成"它停在动图 live.webp 上" —— 这页也接了 DMS 的
        #      render()（detail.html:664），而 demo 源是**按墙钟走的 170 s 演出**，
        #      导航到这一页时正好落到哪一段是随机的（第一次跑就撞在 heart 那段上，
        #      报了一条假红）。所以判据取"**它拿到了四档里的一张真图**"：
        #      既不依赖落在哪一段，又能咬住"这一格还在走槽的管线、没退回内置 SVG"。
        want4 = [sev_src(n) for n in SEV_ACT.values()]
        d, seen_d = None, []
        for _ in range(20):
            d = await imgat(S, "#mascotImg")
            if d and d["src"] in want4 and d["nat"] > 0:
                break
            if not seen_d or seen_d[-1] != (d or {}).get("src"):
                seen_d.append((d or {}).get("src"))
            await asyncio.sleep(0.5)
        worst |= ck("detail 3.4rem 有真图、受档位驱动",
                    bool(d) and d["src"] in want4 and d["nat"] > 0,
                    f"{d['src'] if d else None} nat={d['nat'] if d else None}"
                    f"（四档 = {'/'.join(want4)}）"
                    f" 路过 {' -> '.join(str(x) for x in seen_d)}")

        # ★★ 2026-09-26：这里原来还有两条 —— 「detail 对话栏 3.6rem 指头像版
        #   （`xiaorui_head.png`）」和「手机四格 4.6rem 指头像版」。**对象没有了**：
        #   这两个（以及 `phone.html` 的四格）已经**从 `mascot.bind` 挪到
        #   `XQ.poseDeck()`**，走 `XQ.POSES` 那套 `pNN.webp`、尺寸 `h`（192px）。
        #   所以它们现在在 `_check_posedecks.py` 的 SLOTS 里逐格验
        #   （detail 的「驾驶监测对话头像」、phone 的「手机 hero 0~3」，
        #   四条判据 + 连点顺序，比这里一条"名字对不对"细得多）。
        #   ⚠️ 别往回加。要验的是"这一格挂没挂上真图"，那件事在 posedecks 里；
        #      这里再加一条只会让同一个槽有两处各验一半。
        #   （`#navArtImg` 下面那条**不在此列**：导航页那一格到今天仍然是
        #    `XQ.mascot.bind(..., {base:'head'})`，吃的是命名的 `xiaorui_head.png`，
        #    而且它是"显式 base 真的生效"的唯一视觉证据 —— 那条留着。）

        # ★ 2026-09-25 晚：**这一条建回来了**（09-24 随 nav.html 删过一天）。
        #   ⚠️ 它**不只是**一格槽的计数 —— 它同时是 `check_bind_bases()` 那半边
        #     "显式传 base 真的生效"的**唯一视觉证据**（见那个函数的长注释）：
        #     全站只有导航页这一格显式传了 `base:'head'`，而"没传"的默认值是
        #     **待机动图**（`xiaorui_live.webp`），两张图在 DOM 上分得开。
        #   ⚠️ 为什么要 `settle` 而不是读一次：认领时那下「打招呼」是 `happy`
        #     （hold 2000），读一次多半正撞在它上面 —— 那会报一条**假红**
        #     （图是对的，只是还没演完）。settle 会轮询到它回到底图。
        await S.goto("/nav.html", 3.2)
        ok_n, seen_n = await settle(S, "#navArtImg", "xiaorui_head.png", timeout=10.0)
        worst |= ck("★ nav 那一格拿到了**头像版**真图"
                    "（显式 base:'head' 生效，不是默认的待机动图）",
                    ok_n, "路过：" + " -> ".join(str(x) for x in seen_n))
        nv = await imgat(S, "#navArtImg")
        svg_hidden = await S.js("!!document.getElementById('navArtSvg').hidden")
        worst |= ck("★ 真图落地后内置 SVG 那格被藏掉了（不是两层叠着）",
                    bool(nv) and nv["nat"] > 0 and svg_hidden is True,
                    f"nat={nv['nat'] if nv else None} svg藏={svg_hidden}")
        # ⚠️ G 段上面那两格（手机四格、detail）验的都是**默认值**；
        #    只有这一格验的是"覆盖生效"。**别顺手把这一格删掉** ——
        #    删了之后 `check_bind_bases()` 就静默退回只剩一半（绿，但没验东西）。

        if S.errs:
            for lvl, txt in S.errs[:10]:
                print(f"  !!  {lvl}：{txt}")
            worst |= 1
        else:
            print("  OK  detail / phone 两页零报错")

        # ================================================== H · 品牌标志组
        # ⚠️ 这条判据这条**改过两次**，量的对象一路在变（别再往回改）：
        #    ① 2026-09-23 之前是"顶栏字样高度 = 2.82rem"（`.brand-wordmark` 艺术字图）；
        #    ② 09-23 艺术字图删了 → 变成"标志图 + HTML 文字"；
        #    ③ ★ 09-24 晚**并成一张整 lockup**（用户：「直接整张图替换所有左上角
        #       出现灵途智行标的部分」）。所以「品牌名是真文字」那条**必须废掉** ——
        #       它现在恒假，而假红会被人当成"顶栏坏了"去查一个不存在的问题。
        #       换成量 alt：那两行字在图里，DOM 上只剩 alt 还写着它们。
        print("\n=== H 顶栏品牌标志组（2026-09-24 晚：整张 lockup 一张图）===")
        brand = await jsawait(S, """(async () => {
          const out = {};
          const mark = document.querySelector('.lingtu-lockup');
          out.hasMark = !!mark;
          out.markSrc = mark ? (mark.getAttribute('src')||'').split('/').pop() : null;
          out.markNat = mark ? mark.naturalWidth : 0;
          out.markH = mark ? Math.round(mark.getBoundingClientRect().height) : 0;
          out.alt = mark ? (mark.getAttribute('alt')||'') : null;
          /* 并组之后 `.lingtu-txt` 整个没了 —— 这两项**现在应该是 0**，
             留着当"别哪天又有谁把文字排回来"的靶子（排回来的话顶上就是
             "灵途智行"写两遍，而只看图是看不出来的）。 */
          out.txtLeft = document.querySelectorAll('.lingtu-txt').length;
          out.oldWordmark = document.querySelectorAll('.brand-wordmark').length;
          const r2 = await new Promise(res => {
            const i = new Image();
            i.onload  = () => res([i.naturalWidth, i.naturalHeight]);
            i.onerror = () => res([0, 0]);
            i.src = '/static/assets/lingtu_wordmark_mask.png';
          });
          out.mask = r2;
          return JSON.stringify(out);
        })()""")
        worst |= ck("★ 顶栏品牌图 lingtu_lockup.png 加载成功",
                    brand["hasMark"] and brand["markNat"] > 0,
                    f"{brand['markSrc']} nat={brand['markNat']} 渲染高 {brand['markH']}px")
        # ⚠️ 拿"灵途智行"四个字当判据，**不是**"alt 非空"：后者对"图被换成
        #    院徽/别的图"照样绿。换错素材才会红。
        worst |= ck("★ 品牌名在 alt 里（字已经进图片了）",
                    brand["alt"] == "灵途智行 · 与你同行", repr(brand["alt"]))
        worst |= ck("   并组之后没有把文字再排一遍（.lingtu-txt 应为 0）",
                    brand["txtLeft"] == 0, f".lingtu-txt × {brand['txtLeft']}")
        worst |= ck("   旧的艺术字 <img> 已经不在 DOM 里",
                    brand["oldWordmark"] == 0, f".brand-wordmark × {brand['oldWordmark']}")
        worst |= ck("封面 h1 的遮罩图照旧",
                    brand["mask"][0] > 0, f"{brand['mask'][0]}x{brand['mask'][1]}")

        # ================================================== I · 减少动态效果
        print("\n=== I prefers-reduced-motion ===")
        await S.cmd("Emulation.setEmulatedMedia",
                    {"features": [{"name": "prefers-reduced-motion", "value": "reduce"}]})
        await S.goto("/chat.html", 2.6)      # goto 会清掉 resource timing，下面数得准
        rm = await S.js("JSON.stringify([...document.querySelectorAll('.mascot-img')]"
                        ".map(e => getComputedStyle(e).animationName))")
        worst |= ck("★ 动效全关（连待机呼吸也关）",
                    len(rm) > 0 and all(x == "none" for x in rm), str(rm))
        rim = await imgat(S, "#tipImg")
        worst |= ck("★ 底图退回静态 PNG（不是动图）",
                    rim["src"] == "xiaorui_live_still.png", rim["src"])
        # ⚠️ 这条才是重点：动画 WebP 是 <img> 自己的帧，CSS 的 animation:none
        # 管不着 —— 光看 animation-name 是 none 会以为降级成功了，其实那张动图
        # 还在自顾自地播。唯一作准的判据是**它压根没被请求过**。
        res = await S.js("JSON.stringify(performance.getEntriesByType('resource')"
                         ".map(e => e.name.split('/').pop()))")
        worst |= ck("★★ 整个页面一次都没请求过那张动图",
                    "xiaorui_live.webp" not in res,
                    "请求了这些："
                    + " ".join(x for x in res if "xiaorui_live" in x or "webp" in x))
        worst |= ck("   换用的是那张静帧（是它在上）",
                    "xiaorui_live_still.png" in res,
                    f"resource 共 {len(res)} 条")
        await S.cmd("Emulation.setEmulatedMedia", {"features": []})

        # ================================================== J
        print("\n=== J 全程控制台 ===")
        if S.errs:
            for lvl, txt in S.errs[:20]:
                print(f"  !!  {lvl}：{txt}")
            worst |= 1
        else:
            print("  OK  一路零报错零警告")

    print()
    if FAILED:
        print(f"✗ 共 {len(FAILED)} 条失败（重印一遍，免得被输出截断埋掉）：")
        for f in FAILED:
            print(f"   · {f}")
    elif worst:
        print("✗ 没有 ck 失败项，但退回码非零 —— 那是控制台报错那一类（S.errs），"
              "往上面 J 段找")
    else:
        print("✓ 全绿（小瑞那几张图仍要人眼看：动作对不对味、有没有抠干净）")
    return worst


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
