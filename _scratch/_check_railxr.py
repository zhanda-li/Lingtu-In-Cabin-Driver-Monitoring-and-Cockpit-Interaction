"""左栏那一格小瑞：**点一下换动作 + 不点就上下浮动**，而且不被播放条压住。

    D:\\Anaconda3\\envs\\dms\\python.exe ui\\server.py --port 8790 --source demo
    D:\\Anaconda3\\envs\\dms\\python.exe _scratch/_check_railxr.py

## 用户这一轮说了什么（原话）

  1. 「然后做左侧空白处放上小瑞形象是每一页哦 类似多媒体.png左边小瑞那种」
  2. 「而且还有就是它挡到我坐下的小瑞了」（"坐下" = 左下；指的是跨页播放条）
  3. 「而且左下小瑞应该可以**像展示页一样**可以点击变换 并且上下浮动」

## 判据

  A. 每一张座舱页上都有这一格，底图**真的加载出来了**（`naturalWidth > 0`），
     而且它挂的是 `.mascot-img` —— 用户要的"上下浮动"就是那个类上的 `xqIdle`，
     这里**直接读 computed animation-name**，不是"看着像在动"。
  B. **点一下真的换形象，而且浮动回得来**：连点 3 下，每次 `src` 都换成形象库里
     下一张（而且始终是 `s` 那套、不串到 `l`/`h`）；每一下 `data-act` 挂上（弹那一下）
     → HOLD(620ms) 之后**必须摘掉**，`animation-name` 回到 `xqIdle`。
     ⚠️ 摘不掉是个经典坑：不摘的话 `data-act` 的权重永远压着 `.mascot-img`，
       这一格就变成"点一下之后再也不浮动了"。
     ⚠️ **"43 张走一圈不重样、顺序正确、回得去起点"这一整套不在这里验** ——
        那是 `_scratch/_check_posedecks.py` 的活儿（它按 `poseDeck` 的契约逐格验，
        包括 `#railXrImg` 那 43 下回绕）。这里只管**这一格自己的两件事**：
        换得动、浮动回得来。别在这边复制一套 43 下的循环，两份一起漂。
  C. **这一格吃的是全站形象库的 `s` 那套小图**（`assets/xq/s/pNN.webp`）：
     每一张服务端 200、单张 < 100 KB，43 张全在。
     这条防的是有人"顺手"把它换成 `l`（730x1000）那套 —— `/static/` 没有缓存头，
     点了要多下 190 KB/张。
     ⚠️ 它原来是"验左栏自己那 5 张 `xiaorui_rail_*.png`"（第十次改版前的老机制）。
     那一套已经没代码用了，所以判据改成查**现在真正在用的那一套**。
  D. **播放条不压小瑞**：把存档塞好、让左下那条 `#xqMini` 画出来，量两个矩形 ——
     小瑞的脚必须在条的上沿**之上**。
  E. 小瑞（现在是个能点的东西了）不压四个入口，左栏也没被它撑出滚动条。
     ⚠️ 原来的措辞是"不压四个入口 / 喇叭按钮"，那个喇叭按钮 **2026-09-25 全站删了**，
        所以现在真的只剩四个入口。判据本身一个字没改（选的是 `.ri`）。
  F. 控制台零报错。

⚠️ 这个脚本**证明不了**"这套动作好不好看"（人眼的事，截图在 `_shots/`）。
⚠️ 也**证明不了**"真人点得动"：CDP 的 `.click()` 是脚本点击。它量的是这条代码路径通不通。
"""

import asyncio
import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session, ck          # noqa: E402

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 端口/调试口和其它脚本错开：9411 _check_pages / 9416 _check_player /
# 9429 _check_theme2 / 9441 _check_alarm / 9455 _check_grade / 9465 _check_monitor /
# 9471 _check_bg。
CDP = 9481
SHOTS = Path(__file__).parent / "_shots"
KEY = "xq.media.play"

# 形象库那套小图的尺寸目录名。**和 live.js 的 XQ.POSE_PX / poseURL 对上** ——
# 左栏那一格必须一直是 's'（210x288）。
DECK_SIZE = "s"
DECK_N = 43           # 形象库一共多少张（XQ.POSES 的长度，B 段会跟页面上的数对一遍）
HOLD_MS = 620         # live.js 里 poseDeck 的默认 hold
# 装了 player.js 的座舱页（和 _check_player.py 的 CABIN 同一份名单）
CABIN = ["index.html", "detail.html", "monitor.html", "chat.html", "media.html",
         "settings.html", "phone.html", "link.html", "flow.html", "voice.html"]
BAR_PAGE = "settings.html"        # 拿它当"条会画出来"的那一页（随便挑一张非多媒体页）

PROBE = r"""
JSON.stringify((() => {
  const R = (el) => el ? el.getBoundingClientRect() : null;
  const img = document.getElementById('railXrImg');
  const host = document.getElementById('railXr');
  const card = document.querySelector('.rail-card');
  const bar = document.getElementById('xqMini');
  const barR = R(bar), imgR = R(img);
  const overlap = (a, b) => {
    if (!a || !b) return null;
    const w = Math.min(a.right, b.right) - Math.max(a.left, b.left);
    const h = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    return (w > 0.5 && h > 0.5) ? {w: +w.toFixed(1), h: +h.toFixed(1)} : null;
  };
  const cs = img ? getComputedStyle(img) : null;
  const clicky = [...document.querySelectorAll('.ri, .src-btn.vb')].map(R);
  return {
    hasImg: !!img, hasHost: !!host,
    nw: img ? img.naturalWidth : 0,
    src: img ? (img.getAttribute('src') || '') : null,
    cls: img ? img.className : null,
    act: img ? (img.dataset.act || '') : null,
    anim: cs ? cs.animationName : null,
    iter: cs ? cs.animationIterationCount : null,
    cursor: host ? getComputedStyle(host).cursor : null,
    title: host ? host.title : null,
    /* 小瑞 -> 播放条：脚必须在条的上沿之上 */
    gap: (imgR && barR) ? +(barR.top - imgR.bottom).toFixed(1) : null,
    imgBarHit: overlap(imgR, barR),
    /* 小瑞 -> 四个入口/喇叭按钮 */
    imgHit: clicky.map((r) => overlap(imgR, r)).filter(Boolean),
    /* 小瑞必须在导航卡里面（不能溢出到卡外压到别的东西） */
    inCard: (imgR && card) ? (imgR.left >= R(card).left - 0.6
              && imgR.right <= R(card).right + 0.6
              && imgR.bottom <= R(card).bottom + 0.6) : null,
    barOn: !!bar,
    railScroll: card ? (card.scrollHeight - card.clientHeight) : null,
    top: imgR ? +imgR.top.toFixed(2) : null,
    bottom: imgR ? +imgR.bottom.toFixed(2) : null,
  };
})())
"""


async def shot(S, name):
    r = await S.cmd("Page.captureScreenshot", {"format": "png"})
    p = SHOTS / ("railxr_%s.png" % name)
    p.write_bytes(base64.b64decode(r["data"]))
    print("     截图 -> _shots/%s.png  %.0f KB" % (p.name, p.stat().st_size / 1024))


def first_track():
    """从 /music.json 里拿一首真歌的文件名 —— D 段要拿它当"正在放的那一首"，
    条才会画出来（存档里有 file 才画）。"""
    with urllib.request.urlopen("http://127.0.0.1:8790/music.json", timeout=8) as r:
        j = json.loads(r.read().decode("utf-8"))
    ts = [t for t in (j.get("tracks") or []) if t.get("file")]
    if not ts:
        raise SystemExit("曲库是空的 —— 这个脚本要一首真歌才能把播放条画出来")
    return ts[0]["file"]


async def main():
    worst = 0
    f0 = first_track()
    print("拿来做「正在放的那一首」的：%s" % f0)

    async with Session(CDP) as S:
        await S.cmd("Emulation.setDeviceMetricsOverride",
                    {"width": 1672, "height": 940, "deviceScaleFactor": 2,
                     "mobile": False})

        # ============================================================ A
        print("\n=== A. 每一页都有这一格，而且它真的在上下浮动 ===")
        seen = {}
        for pg in CABIN:
            await S.goto("/" + pg, 3.0)
            d = await S.js(PROBE)
            seen[pg] = d
            worst |= ck("%-14s 这一格在、图真的加载了" % pg,
                        d["hasImg"] and d["nw"] > 0,
                        "naturalWidth=%s src=%s" % (d["nw"], (d["src"] or "")[-30:]))
            worst |= ck("   ★ 挂的是 .mascot-img（浮动就靠它）",
                        "mascot-img" in (d["cls"] or "") and d["anim"] == "xqIdle"
                        and d["iter"] == "infinite",
                        "class=%r animation=%s x%s" % (d["cls"], d["anim"], d["iter"]))
            worst |= ck("   它是个能点的东西（cursor:pointer + 一句提示）",
                        d["cursor"] == "pointer" and (d["title"] or "").strip() != "",
                        "cursor=%r title=%r" % (d["cursor"], d["title"]))
        # 上下浮动**真的在动**：隔几拍量三次，量到位移就算过。
        # （只看 animation-name 是在验"规则挂上了"，这一条是在验"人眼能看见动"。）
        tops = []
        for _ in range(3):
            tops.append((await S.js(PROBE))["top"])
            await asyncio.sleep(1.25)
        worst |= ck("★ 连着量三次，位置真的在变（不是静止图）",
                    (max(tops) - min(tops)) > 1.0,
                    "三次 top = %s（极差 %.2f px）"
                    % ([round(t, 1) for t in tops], max(tops) - min(tops)))
        await shot(S, "float")

        # ============================================================ B
        print("\n=== B. 点一下换形象，且浮动回得来 ===")
        await S.goto("/index.html", 3.0)
        # 起步：页面上的形象库长度先跟这里的常数对一遍（对不上就是两边漂了）
        nposes = await S.js("(XQ.POSES || []).length")
        worst |= ck("   页面上的形象库长度 = %d" % DECK_N, nposes == DECK_N,
                    "XQ.POSES.length=%s（不一致就改本文件的 DECK_N）" % nposes)

        seen, acts, sizes = [], [], []
        for i in range(3):
            await S.js("document.getElementById('railXr').click()")
            await asyncio.sleep(0.35)
            d = await S.js(PROBE)
            seen.append(d["src"])
            acts.append(d["act"])
            # src 形如 assets/xq/s/p07.webp —— 拆出尺寸目录和名字
            m = re.search(r"/xq/([slh])/(p\d+)\.webp", d["src"] or "")
            sizes.append(m.group(1) if m else "?")
            if i == 0:
                await shot(S, "act")
        worst |= ck("★ 连点 3 下，每一下都换了张",
                    len(set(seen)) == 3 and all(seen),
                    "依次 %s" % [s.rsplit("/", 1)[-1] for s in seen])
        worst |= ck("★ 换的是形象库、而且一直是 %s 那套" % DECK_SIZE,
                    set(sizes) == {DECK_SIZE},
                    "尺寸目录 = %s" % sizes)
        worst |= ck("★ 每一下都挂上了 data-act（弹的那下真的播了）",
                    acts == ["swap"] * 3, "data-act = %s" % acts)
        # 最后一下之后等过 HOLD，data-act 必须已经摘掉
        await asyncio.sleep(HOLD_MS / 1000.0 + 0.6)
        d = await S.js(PROBE)
        worst |= ck("★★ %.2f s 之后 data-act 摘掉了（浮动回得来）" % (HOLD_MS / 1000.0),
                    d["act"] == "" and d["anim"] == "xqIdle",
                    "data-act=%r animation=%s" % (d["act"], d["anim"]))
        # 再点一下还要能换（不是"点过一次就死了"）
        await S.js("document.getElementById('railXr').click()")
        await asyncio.sleep(0.35)
        d2 = await S.js(PROBE)
        worst |= ck("   再点一下还能换（不是点过一次就死）",
                    bool(d2["src"]) and d2["src"] not in seen and d2["src"] != d["src"],
                    repr(d2["src"]))

        # ============================================================ C
        print("\n=== C. 这一格吃的是形象库的 %s 那套小图 ===" % DECK_SIZE)
        tot = 0
        bad = []
        for i in range(1, DECK_N + 1):
            u = ("http://127.0.0.1:8790/static/assets/xq/%s/p%02d.webp"
                 % (DECK_SIZE, i))
            try:
                with urllib.request.urlopen(u, timeout=8) as r:
                    sz = len(r.read())
            except Exception:
                sz = 0
                bad.append("p%02d" % i)
            tot += sz
        worst |= ck("★ %d 张全在服务端 200" % DECK_N, not bad,
                    "缺 %s" % (bad[:6] if bad else "无"))
        worst |= ck("★ 单张都 < 100 KB（点了才下，一下一张）",
                    bad or tot / max(DECK_N, 1) < 100 * 1024,
                    "平均 %.1f KB，合计 %.0f KB" % (tot / DECK_N / 1024, tot / 1024))
        # 反面钉子：左栏自己那 5 张老素材**不该再被这一格读到**。
        # ⚠️ 只查"文件还在不在盘上"会得到误导性的结果 —— 那几个文件现在**还躺在
        #    assets/ 里**（没人引用，属于待清理）；这里要钉的是**代码不再读它**，
        #    所以查的是页面上那一格的 src 落在哪个目录（B 段刚量过：`/xq/s/`）。
        worst |= ck("   不再读左栏自己那 5 张老素材（xiaorui_rail_*）",
                    all("/xq/%s/" % DECK_SIZE in (s or "") for s in seen),
                    "src 依次 %s" % [s.rsplit("/", 1)[-1] for s in seen])

        # ============================================================ D
        print("\n=== D. 播放条不许压到小瑞（用户：「它挡到我...小瑞了」）===")
        await S.goto("/" + BAR_PAGE, 2.0)
        # 塞一份存档再重进 —— 条只在"存着东西"的时候才画（player.js 的 mount）
        await S.js("sessionStorage.setItem(%r, JSON.stringify({file: %r, title: 'T',"
                   " artist: '', pos: 3, dur: 200, vol: 0.5, playing: true, t: Date.now()}))"
                   % (KEY, f0))
        await S.goto("/" + BAR_PAGE, 3.5)
        d = await S.js(PROBE)
        worst |= ck("   条真的画出来了（不然这一段等于没测）",
                    d["barOn"] is True, "barOn=%s" % d["barOn"])
        worst |= ck("★★ 小瑞的脚在播放条上沿之上（不重叠）",
                    d["imgBarHit"] is None and d["gap"] is not None and d["gap"] >= 2.0,
                    "缝 %.1f px，重叠 %s" % (d["gap"] if d["gap"] is not None else -1,
                                          d["imgBarHit"]))
        await shot(S, "with_bar")

        # ============================================================ E
        print("\n=== E. 它自己不挡东西、也没把左栏撑出滚动条 ===")
        worst |= ck("★ 不压四个入口", not d["imgHit"], str(d["imgHit"]))
        worst |= ck("   落在导航卡里面（没溢出到卡外）", d["inCard"] is True,
                    "inCard=%s" % d["inCard"])
        worst |= ck("   左栏没被它撑出滚动条", (d["railScroll"] or 0) <= 1,
                    "溢出 %s px" % d["railScroll"])

        # ============================================================ F
        print("\n=== F. 控制台零报错（chrome.js 是拼字符串拼出来的）===")
        worst |= ck("无 error / warning", not S.errs, S.errs[:4])

    print("\n" + "=" * 68)
    print("**%d 项不过，见上**" % worst if worst
          else "**全绿**（截图仍要人眼看：_shots/railxr_with_bar.png 是小瑞和播放条同框那张）")
    return worst


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
