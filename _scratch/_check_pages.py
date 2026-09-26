"""验本次「把它做成一个真产品」那批改动，重点是**入口真的能点**。

判据：
  A 五个入口    —— `.ri` 恰好 5 项、五项都有 `data-target`，而且**逐项点过去真的换页**
                   （这是用户这次报的核心问题：「首页/驾驶监测/导航/多媒体/设置都点不了」——
                   ⚠️ 那句话里本来就有「导航」五项；2026-09-24 删到 4 项，2026-09-25
                   导航页接了真高德回来了，所以这里又数回 5）。
  B 作品索引    —— `.sheet` 计数为 **0**（用户要求彻底去掉左栏那十格）。
  C 封面流程    —— `/` 拿到的是封面（不是 index），右下角有「进入」，点它落到 index.html，
                   ★ 2026-09-25 起**这一条要闭环**：首页那颗「返回展示页」
                   （`.dash-cta`，用户「我有时候要返回展示页啊」+ 指定了位置
                   「在首页进入座舱那个位置 把进入座舱改成这个」）点一下必须回封面。
  D 座舱主界面  —— 左栏那块「小瑞语音」**整块没了**（2026-09-25）、
                   静音开关真的能开关（现在只剩设置页 `#ttsSw` 一个）、
                   对话栏**不在首页**（第五次改版搬去驾驶监测了，那边在 A 段
                   逐项点击里验它确实在）。
  E 两张新页    —— media / settings 打得开、控制台零报错、各自的"真在算"那件事成立
                   （media 真读出音频时长和波形、settings 真读到 hello）。

★ 2026-09-24 删掉的两组（不是失效，是**被删的功能本身没了**）：
  · 原来 D 段的「数据源兜底」—— 左栏那个「数据源」块和 settings 那张卡片同一天一起删了，
    全站没有切源入口，`.src-btn[data-spec]` 一个都不剩，"点了没反应"无从谈起。
  · 原来 E 段的 nav.html 整页判据 —— 用户「把导航页删了吧」，页和左导航那一项都没了。
  ⚠️ 连带说明三件事，免得下次有人当成漏写往回加：
    · 「换目的地真的重算折线」那条判据**随页一起没了**，不是丢了；
    · `[data-spec]` 那条限定规矩（喇叭按钮也带 `.src-btn`）在本脚本里**不再有断言**，
      它现在只活在 app.js 的注释里；
    · ★ 2026-09-25：**喇叭按钮本身也没了** —— 用户「小瑞语音 / 出声 /
      Microsoft Xiaoxiao Online (Natural) —— 左边栏不要出现这些」。所以 D 段那条
      "点喇叭真的能开关"改成"**左栏一个 `.src-btn` 都不剩**"，而"开关真的翻得动"
      挪到设置页的 `#ttsSw` 上验（判据**还在 D 段**，只是换了页、换了选择器）。
      别在 D 段往回加"点喇叭"那种断言 —— 那个元素已经不存在了。

    python _scratch/_check_pages.py 8790

⚠️ 这个脚本**证明不了**：音频好不好听、封面在 kiosk 全屏下好不好看。
   那些只有人眼/人耳说了算，别拿它冒充。

⚠️ 跑之前服务得先起着（本脚本不负责起服务，起服务的写法见 _check_tts_srv.py）：
   双层壳：D:\\Anaconda3\\envs\\dms\\python.exe ui\\server.py --port 8790 --source demo
   ⚠️ 这里写 `--source demo` 是**故意的**：`run_ui.bat` 的默认 09-24 已改成 `cam`，
      而本脚本验的是页面行为，不该去开摄像头，更不该和别的 `_check_*` 抢设备。
      手动起服务时**别照抄 run_ui.bat 的默认值**。
"""

import asyncio
import json
import subprocess
import sys
import tempfile
import time
import urllib.request

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
# 🔴 **`BASE` 是 import 这一刻用 `PORT` 拼死的**（就这一行）。所以外面写探针时
#    `import _check_pages as CP; CP.PORT = "8796"` **不够** —— `goto()` 里读的是模块
#    全局 `BASE`，还是往 8790 走，那儿没服务，浏览器给你一张错误页。
#    2026-09-26 就这么踩过一次，症状是 `$ is not a function`：看着像"这一页的内联
#    脚本编译不过"（`nav.html:1896-1910` 正好记着那种病），其实是**打错了端口**。
#    → 要么两个一起改（`CP.PORT = CP.BASE = ...`），要么干脆把端口写在 `sys.argv`
#      里（像 `_smoke_nav_loop.py` 那样**在 import 之前**塞 `sys.argv`）。
BASE = f"http://127.0.0.1:{PORT}"

# 和 _check_tts.py 里那两条一样：app.js 的 probeAssets() 靠"试着加载"判断可选资产
# 在不在（摄像头示意图/视频本来就没做）。这两个 404 不是错。
KNOWN_PROBE_404 = ("/assets/camera.jpg", "/assets/camera.mp4")

# 高德 JS SDK 自己发的**性能提示**，改不了（bundle 是高德的），实测原文：
#   Canvas2D: Multiple readback operations using getImageData are faster with the
#   willReadFrequently attribute set to true.
# ⚠️ 为什么不能整条"这一页不查控制台"过去：导航页最该咬住的错 —— **域名白名单没配**
#    （`INVALID_USER_DOMAIN`）—— 恰恰也是从高德那边报出来的。所以过滤要**窄到字样**，
#    而且滤掉的条数照样打出来（人不该习惯性忽略这一节的输出）。和 `_check_amap.py`
#    里的 `AMAP_NOISE` 是同一条。
SDK_NOISE = ("willReadFrequently",)


class Session:
    """一次浏览器 + 一条 CDP 连接，可以在里面反复 goto / 点 / 读。

    两个给子类留的口子（默认空 = 行为一字不变）：
      · `EXTRA_FLAGS` —— 追加给 Edge 的命令行开关。`_check_wake_browser.py` 用
        它装假麦克风（`--use-fake-device-for-media-stream` 那一组），免得为了
        几个开关把这段启动逻辑再抄一份出来。
      · `PRELOAD`    —— 每个新文档**开始执行之前**注入的脚本（CDP 的
        `addScriptToEvaluateOnNewDocument`）。要验"页面从来没碰过麦克风"这类
        **行为发生过没有**的判据，只能在这时候装桩 —— 页面脚本一跑起来，
        `XQ.*` 就把该接的都接上了，之后再装就是马后炮。
    """

    EXTRA_FLAGS: list = []
    PRELOAD: list = []

    def __init__(self, cdp):
        self.cdp = cdp
        self.proc = None
        self.ws = None
        self.cm = None
        self.n = 0
        self.errs = []
        self.noise = 0                # 滤掉的那几条（见 `note()` 里的 SDK_NOISE）

    @staticmethod
    def port_busy(port):
        """端口上有没有东西在听。"""
        import socket
        s = socket.socket()
        s.settimeout(0.4)
        try:
            s.connect(("127.0.0.1", port))
            return True
        except OSError:
            return False
        finally:
            s.close()

    async def __aenter__(self):
        import aiohttp
        # ⚠️ 「端口上有人」和「端口上有个能用的浏览器」是两件事。上一个脚本如果是
        # 在这个函数里崩的，`__aexit__` 就没机会跑，会留下一个**僵尸 Edge** 抱着
        # 这个端口：它既不服务 CDP，又让新起的 Edge 绑不上。表现是白等满 30 秒
        # （60 × 0.5s）然后报「连不上调试端口」—— 和真的启动失败长得一模一样，
        # 而真正的原因（上一次留下的垃圾）在这条报错里一个字都看不出来。
        # 这次排查就绕了三个来回，所以先探一下、说清楚，再谈启动。
        if self.port_busy(self.cdp):
            raise RuntimeError(
                f"调试端口 {self.cdp} 上已经有东西在听了（多半是上一次留下的僵尸 "
                f"Edge）。先把它清掉，或用别的端口再跑：\n"
                f"    taskkill /F /PID <那个 msedge.exe 的 PID>\n"
                f"    查法: Get-CimInstance Win32_Process -Filter \"Name='msedge.exe'\"")
        self.proc = subprocess.Popen(
            [EDGE, "--headless=new", "--disable-gpu", "--hide-scrollbars",
             f"--remote-debugging-port={self.cdp}", "--window-size=1672,940",
             # ⚠️ 没这个开关，`<audio>.play()` 会被自动播放策略拒掉 ——
             # CDP 的 `.click()` 是**脚本点击**，不算"用户手势"。不带它就验不了
             # media 页的播放，而且失败得很安静（`paused` 一直是 true、零报错）。
             # 它换来的是"播放这条代码路径通不通"，**换不来**"真人点一下能不能响"
             # —— 后者只有真浏览器里真点一下才算数（见文件头那句）。
             "--autoplay-policy=no-user-gesture-required",
             "--no-first-run", "--user-data-dir=" + tempfile.mkdtemp(),
             *self.EXTRA_FLAGS, "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        target = None
        try:
            for _ in range(60):
                try:
                    with urllib.request.urlopen(f"http://127.0.0.1:{self.cdp}/json/list",
                                                timeout=2) as r:
                        ps = [t for t in json.load(r) if t["type"] == "page"]
                    if ps:
                        target = ps[0]
                        break
                except Exception:
                    pass
                time.sleep(0.5)
            if not target:
                raise RuntimeError("连不上调试端口")
        except BaseException:
            # 这里失败也必须把 Edge 收掉 —— 不收就是**给下一次留坑**，
            # 而且坑的形态是上面那段注释里最难看的那种：下一次报的错和这一次
            # 完全无关，指向端口而不是指向真凶。BaseException 不是过度小心：
            # Ctrl+C 打断时抛的是 KeyboardInterrupt，它也走这条路。
            self.proc.terminate()
            raise
        self.cm = aiohttp.ClientSession()
        s = await self.cm.__aenter__()
        self.ws = await s.ws_connect(target["webSocketDebuggerUrl"], max_msg_size=0)
        await self.cmd("Runtime.enable")
        await self.cmd("Log.enable")
        await self.cmd("Page.enable")
        # 见类注释：要验"页面从来没做过某件事"，桩必须赶在文档脚本之前。
        for src in self.PRELOAD:
            await self.cmd("Page.addScriptToEvaluateOnNewDocument", {"source": src})
        return self

    async def __aexit__(self, *a):
        try:
            await self.cm.__aexit__(*a)
        except Exception:
            pass
        if self.proc:
            self.proc.terminate()

    def note(self, m):
        """收报错。控制台零报错是这个项目的老规矩，所以这里一点都不放过。

        ⚠️ 只有**一条**例外，而且是窄到字样的（`SDK_NOISE`）：那一条来自高德 SDK
           自己的 bundle，我们改不了，留着只会让人习惯性忽略这一节的输出。
           滤掉的**计数照样报出来**（不静默吞）—— 见 `main()` 的控制台那一节。
        """
        meth = m.get("method")
        if meth == "Runtime.exceptionThrown":
            d = m["params"]["exceptionDetails"]
            ex = (d.get("exception") or {}).get("description") or ""
            self.errs.append(("异常", (d.get("text", "") + " " + ex).strip()[:300]))
        elif meth == "Log.entryAdded":
            e = m["params"]["entry"]
            if e.get("level") in ("error", "warning"):
                url = e.get("url") or ""
                if any(k in url for k in KNOWN_PROBE_404):
                    return
                if any(k in (e.get("text") or "") for k in SDK_NOISE):
                    self.noise += 1
                    return
                self.errs.append((e.get("level"), ((e.get("text") or "") + " " + url)[:300]))
        elif meth == "Runtime.consoleAPICalled":
            if m["params"].get("type") in ("error", "warning"):
                vals = " ".join(str(a.get("value", a.get("description", "")))
                                for a in m["params"].get("args", []))
                self.errs.append((m["params"]["type"], vals[:300]))

    async def cmd(self, method, params=None):
        self.n += 1
        mid = self.n
        await self.ws.send_str(json.dumps({"id": mid, "method": method,
                                           "params": params or {}}))
        while True:
            m = json.loads(await self.ws.receive_str())
            if m.get("id") == mid:
                return m.get("result", {})
            self.note(m)

    async def js(self, expr):
        r = await self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True})
        res = r.get("result", {})
        if "value" not in res:
            return None
        v = res["value"]
        # 以 `[`/`{` 开头的字符串当成 JSON 解一下，方便在页面上直接 `JSON.stringify(...)`。
        # ⚠️ 必须用 `startswith`，**不能写 `v[:1] in "[{"`** —— 空串是任何字符串的子串，
        # `'' in "[{"` 是 True，于是读到空串时会拿 `json.loads('')` 炸掉整个脚本。
        return json.loads(v) if isinstance(v, str) and v.startswith(("[", "{")) else v

    async def goto(self, path, wait=1.6):
        await self.cmd("Page.navigate", {"url": BASE + path})
        await asyncio.sleep(wait)

    async def path(self):
        return await self.js("location.pathname")


def ck(name, ok, note=""):
    print(f"  {'OK  ' if ok else '!!  '}{name:30s} {note}")
    return 0 if ok else 1


async def main():
    worst = 0
    async with Session(9411) as S:
        # ---------------------------------------------------------- A + B
        print("\n=== index.html · 五个入口 + 索引已删 ===")
        await S.goto("/index.html", 2.4)
        nav = await S.js("JSON.stringify([...document.querySelectorAll('.ri')].map(a => "
                         "({nav: a.dataset.nav, target: a.dataset.target, "
                         "href: a.getAttribute('href')})))")
        # ★ 2026-09-25：**4 → 5**（导航回来看见 `chrome.js` 的 NAV）。这个数当年就是
        #   从 5 改成 4 的，改回去不是"顺手"，是那一项真的又在了 —— 别在别处再写死 4。
        worst |= ck("恰好五个入口", len(nav) == 5, f"{len(nav)} 项")
        worst |= ck("五项都有 data-target",
                    all(x["target"] for x in nav),
                    " ".join(f"{x['nav']}->{x['target']}" for x in nav))
        worst |= ck("目标页互不相同", len({x["target"] for x in nav}) == 5, "")
        worst |= ck("★ 作品索引真的没了",
                    (await S.js("document.querySelectorAll('.sheet').length")) == 0,
                    "`.sheet` 计数为 0（原来是 10）")
        # ★ 这条判据**翻过两次面**，两回都是"对象没了，不是失败了"：
        #   ① 原来叫「数据源仍是四项」，数 `.src-btn[data-spec]` 恰好 4 个
        #      （演示 / 真人·均衡 / 真人·疲劳 / 摄像头·实时）。2026-09-24 数据源块
        #      删掉 → 带 `data-spec` 的一个不剩，守的东西翻成"别漏回来"。
        #      当时**故意保留**的是 `.src-btn` 总数 == 1（那 1 个是喇叭按钮，
        #      live.js 借 `.src-btn` 的样式），免得"喇叭按钮也一起没了"混过去。
        #   ② ★ 2026-09-25 喇叭按钮也删了（用户「左栏不要出现这些」）——
        #      现在**两个数都必须是 0**，而且"总数 == 1"那半截不能留着，
        #      留着就是恒红。
        # ⚠️ 断言从"**东西还在不在**"改成了"**不许回来**"，所以要两把尺子一起量：
        #    总量 0（两种选择器各量一次，`[data-spec]` 那条是子集，单量它会漏掉
        #    "一个不带 data-spec 的按钮漏回来"）、以及**左栏可见文字里不能再出现
        #    「小瑞语音 / 出声」**（下面那条）—— 只看计数的话，把文案换个 class 写
        #    回来是发现不了的，而用户抱怨的正是**看得见的那几个字**。
        nspec = await S.js("document.querySelectorAll('.src-btn[data-spec]').length")
        nall = await S.js("document.querySelectorAll('.src-btn').length")
        worst |= ck("★ 切源按钮和喇叭按钮都不剩",
                    nspec == 0 and nall == 0,
                    f"[data-spec]={nspec}（期望 0）；.src-btn 总数={nall}（期望 0）")
        # 左栏可见文字。（`#voiceNote` 和 `[data-voice-toggle]` 这两个落点也一起量 ——
        # 它们是 live.js 里被删掉的 render/bind 的靶子，哪天有个旧副本活过来，
        # 有落点却没内容 = 那个副本在裸奔。）
        railTxt = await S.js("JSON.stringify({"
                            " txt: (document.getElementById('rail')||document.body).innerText,"
                            " note: !!document.getElementById('voiceNote'),"
                            " tog: !!document.querySelector('[data-voice-toggle]')})")
        _rail_has = [w for w in ("小瑞语音", "出声", "Microsoft Xiaoxiao")
                     if w in railTxt["txt"]]
        worst |= ck("★ 左栏文字里没有「小瑞语音 / 出声 / 音色名」",
                    not _rail_has and not railTxt["note"] and not railTxt["tog"],
                    f"命中 {_rail_has}；#voiceNote={railTxt['note']} "
                    f"data-voice-toggle={railTxt['tog']}")
        # ★ 2026-09-25 这条**判据翻面了**，不是删掉 —— 和上面 `[data-spec]` 那条同一种情况。
        # 原来叫「有小段对话栏」，读的是**首页**的 `#sayInput`。对话栏第五次改版把它
        # 搬去驾驶监测了（现在只存在于 `detail.html` 与 `chat.html`，首页没有），
        # 于是原来那条在健康的页面上恒红。守的东西因此反过来：
        #   首页**不该**再有对话栏输入框（否则就是两处各留一半、行为分叉）。
        # 只验"首页没有"是不够的 —— 那样"对话栏整个删没了"也会通过。
        # 所以正面那一半放在下面逐项点击落到 `/detail.html` 时验（见 `key == "mon"`）。
        worst |= ck("★ 对话栏已不在首页", (await S.js(
            "!!document.getElementById('sayInput')")) is False,
            "首页无 #sayInput（第五次改版搬到驾驶监测）")

        # ★ 静音开关真的能开关 —— **2026-09-25 搬到设置页了**。
        # 这条原来叫「点喇叭真的能开关」，点的就是左栏那颗喇叭（`[data-voice-toggle]`）。
        # 那颗按钮连同 `XQ.tts.btnHTML/render/bind` 一起删了，所以：
        #   · `document.querySelector('[data-voice-toggle]')` 现在返 **null**，
        #     后面 `.click()` 当场 TypeError —— 这不是"断言失败"，是**整段脚本挂掉**，
        #     比删掉更难查（和上面 09-24 那三条同一个死法）。
        #   · 但"开关真的翻得动"这件事**本身没有消失**，只是换了个落点：
        #     `settings.html` 的 `#ttsSw` 调的是同一个 `XQ.tts.set()`、同一个
        #     localStorage 键 `xq.tts.on`。所以判据整体挪过去，不是删掉。
        # ⚠️ 判据仍旧用"开关真的翻转"，**不要去 tap `link.send`**：app.js 是
        # `send = link.send`，把函数本身存进了另一个变量，之后再包 `link.send`
        # 对它毫无影响 —— 包出来的账本是空的，于是断言会"通过"得毫无意义
        # （先前就写错过一次）。
        # ⚠️ 也别改回在首页点：首页上**没有**任何能改这个开关的东西了，
        #    那是这次改动的要点，不是缺失。
        await S.goto("/settings.html", 2.8)
        vb0 = await S.js("JSON.stringify({on: XQ.tts.on,"
                         " ls: localStorage.getItem('xq.tts.on'),"
                         " checked: document.getElementById('ttsSw').checked})")
        await S.js("document.getElementById('ttsSw').click()")
        await asyncio.sleep(0.9)
        vb1 = await S.js("JSON.stringify({on: XQ.tts.on,"
                         " ls: localStorage.getItem('xq.tts.on'),"
                         " checked: document.getElementById('ttsSw').checked,"
                         " note: (document.getElementById('rVoiceNote')||{})"
                         ".textContent})")
        # `note` 是设置页那张卡下面那行音色说明。它**不是**判据的必需项（音色名
        # 的长短取决于浏览器装了什么），只拿来印在报告里，方便下次有人一眼看出
        # "开关翻过去了、说明也重写了没有"。
        worst |= ck("★ 设置页那个静音开关真的能开关",
                    vb1["on"] != vb0["on"] and vb1["ls"] in ("0", "1")
                    and vb1["checked"] != vb0["checked"],
                    f"开→{vb0['on']} 关→{vb1['on']} checked="
                    f"{vb0['checked']}→{vb1['checked']} note={vb1['note']!r}")

        # ★ 2026-09-24 删：原来这里还有三条断言 ——
        #     「★ 点数据源服务端真的切了」「切回演示也生效」，以及再往下一段
        #     「★ 连不上时不再静默吞掉」（点 `.src-btn` 看有没有 toast）。
        #   左栏「数据源」块删掉之后 `.src-btn[data-spec]` 一个都不剩，
        #   `#srcNote` 这个 id 也不存在了 —— 这三条不是"失败了"，是**对象没了**。
        #   留着的话 `document.querySelector('.src-btn')` 会返 null 然后
        #   `.click()` 当场 TypeError，整段脚本挂掉，比删掉更难查。

        # 逐项点过去，看是不是真的换了页
        print("\n--- 逐项点击（核心验收点） ---")
        for key in ["mon", "navi", "media", "set"]:
            await S.goto("/index.html", 1.8)
            await S.js(f"document.querySelector('.ri[data-nav={key}]').click()")
            await asyncio.sleep(1.6)
            p = await S.path()
            want = {"mon": "/detail.html", "navi": "/nav.html",
                    "media": "/media.html", "set": "/settings.html"}[key]
            worst |= ck(f"点「{key}」真的跳了", p == want, f"-> {p}（期望 {want}）")
            if key == "mon":
                # ★ 上面「对话栏已不在首页」那条的**正面那一半**：它得真的在
                #   搬去的那一页上，否则"搬走了"和"删没了"在这个脚本里长得一样。
                worst |= ck("★ 对话栏真的在驾驶监测页", (await S.js(
                    "!!document.getElementById('sayInput')")) is True,
                    "#sayInput 在 /detail.html")
        # 「首页」要从别的页点，因为在首页上点它本来就不该动
        await S.goto("/media.html", 1.8)
        await S.js("document.querySelector('.ri[data-nav=home]').click()")
        await asyncio.sleep(1.6)
        p = await S.path()
        worst |= ck("点「home」真的跳了", p == "/index.html", f"-> {p}（期望 /index.html）")

        # ---------------------------------------------------------- D
        # ★ 2026-09-24：「数据源点了没反应」整段删了，见上面那条说明。
        #   那一条验的是"点 `.src-btn` 而链路没连上时要出 toast"，
        #   而当时 `.src-btn` 在页面上只剩喇叭按钮一颗（它不切源，也就没有 link.online
        #   那条路）。★ 2026-09-25 连那一颗也没了，全站 `.src-btn` 归零。
        #   ⚠️ 同一类兜底在**对话栏**上仍然活着也仍然值得验（`还没连上座舱服务，
        #      这句话没发出去`）—— 但那是另一条断言，这里没有顺手补一条，
        #      因为本次没动那段代码，补了属于"顺手加验"，不是本次验收范围。

        # ---------------------------------------------------------- C
        print("\n=== 封面流程 ===")
        # ⚠️ `?intro=0`：封面 2026-09-25 起有一层 `z-index:9999` 的**全屏不透明
        #    品牌片头**，它盖着「进入座舱」。不关掉的话下面那次点 15 s 之内
        #    会点在盖子上 —— **静默失败**，报出来像"按钮点了没反应"。
        await S.goto("/?intro=0", 2.2)
        title = await S.js("document.title")
        worst |= ck("`/` 拿到的是封面", "封面" in str(title), f"title={title!r}")
        worst |= ck("有「进入」按钮且是纯 <a>", await S.js(
            "!!(document.getElementById('goBtn') && "
            "document.getElementById('goBtn').tagName === 'A')"), "")
        worst |= ck("封面上左导航是藏着的", await S.js(
            "getComputedStyle(document.getElementById('rail')).display === 'none'"), "")
        await S.js("document.getElementById('goBtn').click()")
        await asyncio.sleep(1.8)
        p = await S.path()
        worst |= ck("点「进入」落到座舱主界面", p == "/index.html", f"-> {p}")

        # ---- 回程：首页那条 `.dash-strip` 里那颗「返回展示页」---------------
        # ★ 2026-09-25 用户点名加的（「搞一个返回展示页的按钮吧 我有时候要返回
        #   展示页啊」），并当场指定了**位置**：
        #     「返回展示页在首页进入座舱那个位置 把进入座舱改成这个」
        #   —— 所以它就在 `.dash-strip` 里原来那颗「进入座舱」的位置上
        #      （`.dash-cta`，原来是 `href="detail.html"`，现在 `href="cover.html"`）。
        #   ⚠️ **别把选择器改回 `.tb-back`**：那是我先加在顶栏的一版，用户当场
        #      要求改到首页来，顶栏那颗连同样式一起撤了（记录在 style.css 的
        #      「❌ 已否」一段）。全站回程口**只有这一处**。
        # 这一段上面那条只验了"进得去"，进来的路一直是**单向**的 ——
        # 现在补上回路，就在这儿验一遍闭环。
        # ⚠️ 验的是**真的点它**，不是"元素在不在"：href 写成空串、写成 `#`、
        #    写成 `javascript:history.back()`，元素都在、上面那条也照样绿。
        #     **href 的落点也一起验**（下面那条 `-> /cover.html`），因为
        #    "还指着 detail.html"正是这一改最可能漏的地方。
        # ⚠️ 点击那行带 `|| {click: …}` 兜底：按钮真没了的话，第一条判据会
        #    红，第二条不该跟着**抛异常把整个脚本打断**（那样后面所有页的判据
        #    一条都跑不到，报出来的形态是"脚本崩了"，看不出真正的原因）。
        back = await S.js("!!document.querySelector('.dash-cta')")
        worst |= ck("★ 首页有那颗「返回展示页」（.dash-cta）", bool(back), "")
        worst |= ck("★ 它写的是「返回展示页」四个字（不是「进入座舱」）",
                    "返回展示页" in str(await S.js(
                        "(document.querySelector('.dash-cta')||{}).textContent")),
                    "")
        await S.js("(document.querySelector('.dash-cta') "
                   "|| {click: function(){}}).click()")
        await asyncio.sleep(1.8)
        p2 = await S.path()
        t2 = await S.js("document.title")
        worst |= ck("★★ 点它真的回到展示封面（闭环）",
                    p2 == "/cover.html" and "封面" in str(t2),
                    f"-> {p2}  title={t2!r}")

        # ---------------------------------------------------------- E
        # ★ 2026-09-24：这里原来是 nav.html 的整段判据（4 条），随页一起删了 ——
        #     「打得开」「五入口都在」「不再挂『没接地图服务』的说明」
        #     「★ 换目的地真的重算了路线」「★ 开始导航后真的在走」。
        #   ⚠️ 有两条**不是"不重要了"而是"没有对象了"**，当时记的就是"别当成漏写往回加"：
        #     · 「五入口都在」这条是所有页共用的一条，它验的是 `.ri` 的条数（原值 5），
        #       它已经在 A0/A 段改成了 4 —— **2026-09-25 又改回 5 了**（导航页回来了，
        #       见上面那条注释）。
        #     · 「不再挂『没接地图服务』的说明」是一条**反面判据**，对象就是 nav.html。
        #
        # ★★ 2026-09-25 晚：**导航页建回来了，但下面这四条原样复活是不对的** ——
        #   新页和旧页不是一回事（旧的是页内算几何的自制路线动画，新的是真高德
        #   地图 + 真服务区数据），所以这里**不是**把旧断言抄回来，而是按新页该守的
        #   东西重写。别照着 09-24 之前的历史版本往回贴。
        #   ⚠️ 旧页那两条「换目的地真的重算了路线」「开始导航后真的在走」**没有**
        #     对应物：新页没有"目的地"也没有"开始导航"（见 nav.html 文件头）。
        print("\n=== nav.html · 导航（真高德） ===")
        await S.goto("/nav.html", 3.0)
        nb = await S.js("JSON.stringify({"
                        "title: document.title,"
                        "rail: document.querySelectorAll('.ri').length,"
                        # ⚠️ 高亮那个类名是 `active`，不是 `on`（chrome.js:364）。
                        #    写错了 querySelector 返回 null → 判据恒红，且看不出来为什么。
                        "active: (document.querySelector('.ri.active')||{dataset:{}})"
                        "        .dataset.nav || '',"
                        "map: !!document.getElementById('map'),"
                        # 角标/说明里必须明写"高德" —— 这是当初删掉整页的理由
                        "cred: (document.querySelector('.mapcred')||{textContent:''})"
                        "      .textContent,"
                        "note: (document.querySelector('.card-h .note')||{textContent:''})"
                        "      .textContent,"
                        # ★ 2026-09-26：`#orgSel` 是老导航页那个 `<select>`，新页没有它
                        #   —— 预设点位改成挂在起点框上的 `<datalist id="orgPresets">`
                        #   （`nav.html` 的 `PRESETS.forEach` 往里塞 option）。
                        #   原来这里读 `#orgSel` 恒得 0，判据**恒红**（改版之后没再跑过）。
                        "ask:  document.querySelectorAll('#orgPresets option').length,"
                        # ⚠️ 只能验"挂上去了几条"，**验不了浏览器会不会把它弹出来** ——
                        #   那是原生的下拉，DOM 里看不见（真按一下的行为在
                        #   `_check_amap.py` C4/D/E 里：往框里打预设名 + 回车，真出数）。
                        "conn: (document.getElementById('connPill')||{textContent:''})"
                        "      .textContent})")
        worst |= ck("导航页打得开（不是 404 白页）",
                    nb["title"].startswith("导航"), f"title={nb['title']!r}")
        worst |= ck("★ 左导航这一页点亮的是「导航」那一项",
                    nb["active"] == "navi", f"active={nb['active']!r}")
        worst |= ck("★ 页面上明写「高德地图」（当初删页的理由就是这下答不上来）",
                    "高德" in (nb["cred"] + nb["note"]),
                    f"角标={nb['cred']!r} 卡头={nb['note']!r}")
        worst |= ck("起点下拉里有预设点位（定位拿不到时人要能自己选）",
                    nb["ask"] >= 3, f"{nb['ask']} 个 option")
        # ⚠️ 这条**不再断言"页面上有地图容器就画出来了"** —— 地图是 WebGL，
        #    headless 里有没有画出来是另一件事，真判据在 `_check_amap.py` D 段
        #    （它拿 `/amap/nearby` 的返回值跟屏上的数对）。这里只验容器在。
        worst |= ck("地图容器在（画没画出来由 _check_amap.py 验）",
                    nb["map"] is True, f"#map 存在={nb['map']}")

        print("\n=== media.html · 多媒体 ===")
        await S.goto("/media.html", 3.0)
        mt = await S.js("JSON.stringify({rows: document.querySelectorAll('.tracks li').length,"
                        " durs: [...document.querySelectorAll('.tracks .dur')]"
                        ".map(e => e.textContent),"
                        " bars: document.getElementById('wave').children.length,"
                        " note: document.getElementById('listNote').textContent})")
        # ★ 2026-09-25 第八次改版：这一页放的不再是 `ui/make_audio.py` 合成的那三段
        #   WAV，而是**用户自己机器上的歌**（`ui/config.json` 的 `media.dir`，
        #   默认 D:\CloudMusic，155 首）。所以下面这几条的**判据形式**跟着改了：
        #     · 「三首都在」→「行数 = 服务端 /music.json 报的条数」
        #       （数量写死就成了"用户的曲库一变这条就假"，所以现读服务端）
        #     · 「每首时长都有」→「过半数的行读出了真时长」：155 首是**顺序**读的
        #       （见 media.html 的 probeDurations），页面加载完再给它几秒。
        #   ⚠️ 更细的那一版（波形是不是真解码、位置量没量对、整页要不要滚）
        #      在 `_scratch/_check_media_lib.py`，这边只留一条"没被打死"的底线。
        with urllib.request.urlopen(f"{BASE}/music.json", timeout=5) as _r:
            _lib = json.load(_r)
        _n = len(_lib["tracks"])
        worst |= ck("★ 曲库里的歌都在（条数 = 服务端说的）", mt["rows"] == _n,
                    f"{mt['rows']} 行 / 服务端 {_n} 首（{_lib['dir']}）")
        _bars = mt["bars"]        # 刷新循环只重读时长，这一格得先存下来
        for _ in range(20):
            if sum(1 for d in mt["durs"] if ":" in d) >= _n * 0.5:
                break
            await asyncio.sleep(0.75)
            mt = await S.js("JSON.stringify({"
                            " durs: [...document.querySelectorAll('.tracks .dur')]"
                            ".map(e => e.textContent),"
                            " note: document.getElementById('listNote').textContent})")
        worst |= ck("★ 时长是文件真给的（不是写死的）",
                    sum(1 for d in mt["durs"] if ":" in d) >= _n * 0.5,
                    f"{sum(1 for d in mt['durs'] if ':' in d)}/{_n} 行有时长"
                    f"（{mt['note']}）")
        worst |= ck("★ 波形是按真实峰值画的", _bars == 150, f"{_bars} 根柱子")
        # 用户点名的「把那些常用应用栏目去掉」——反面钉子：那六格不许回来。
        worst |= ck("★ 常用应用那六格已经不在了",
                    await S.js("!document.getElementById('appGrid') &&"
                               " document.querySelectorAll('.app-tile').length === 0 &&"
                               " document.body.innerText.indexOf('常用应用') < 0"), "")
        # ⚠️ 2026-09-24：原来这里有两条判据，守的是 media 页那段「如实说明」里的
        #    「没有接任何在线曲库」「没有控制通道」两句。用户要求把成段说明文字
        #    从页面上删掉，那段整块没了，所以这两条**判据一并摘掉**（不是改判据、
        #    是判据的靶子不存在了）。同两条也在 _check_media_lib.py 的 J 段。
        #    ⚠️ 那段话原来还"搬"去了顶栏那枚小牌（「曲库 · N 首 · 内置 M」）——
        #       那枚牌子 2026-09-25 也被用户点名删了。这一页现在**完全不提**曲库
        #       是怎么来的；唯一还会提的是"目录没找到"那种故障，由小瑞那行状态说
        #       （`libWarn()`，判据在 `_check_media_lib.py` 的 L 段）。
        # 播放：进度和播放态要真的动（靠启动参数里的 --autoplay-policy，见 Session）
        await S.js("document.getElementById('ppBtn').click()")
        await asyncio.sleep(1.8)
        pb = await S.js("JSON.stringify({cur: document.getElementById('tCur').textContent,"
                        " state: document.getElementById('stateNote').textContent,"
                        " done: document.querySelectorAll('.mp-wave i.done').length,"
                        " ct: au.currentTime, paused: au.paused})")
        worst |= ck("★ 播放键真的放起来了",
                    pb["ct"] > 0 and pb["paused"] is False,
                    f"已播={pb['cur']}（currentTime={pb['ct']:.2f}s）"
                    f" 状态={pb['state']} 染色柱子={pb['done']}")
        # 切歌：换一首真的换 src、时长跟着换、列表高亮跟着走
        t0 = await S.js("JSON.stringify({src: au.currentSrc,"
                        " cur: document.getElementById('tName').textContent,"
                        " on: document.querySelectorAll('.tracks li.on').length})")
        await S.js("document.querySelectorAll('.tracks li')[1].click()")
        await asyncio.sleep(1.8)
        t1 = await S.js("JSON.stringify({src: au.currentSrc,"
                        " cur: document.getElementById('tName').textContent,"
                        " on: document.querySelectorAll('.tracks li.on').length})")
        worst |= ck("★ 换一首真的换了文件",
                    t0["src"] != t1["src"] and t0["cur"] != t1["cur"] and t1["on"] == 1,
                    f"{t0['cur']!r} -> {t1['cur']!r}，高亮 {t1['on']} 行")

        # ★ 放不出来时得说人话。把 play() 换成"一定被拒"，**先 pause 再点播放键**
        # （`ppBtn` 是播放/暂停二合一，正在放的时候点它是暂停，走不到 play 那条路）
        # —— 这条守的是用户报的那一类「点了没反应」：`ppBtn` 和 `playTrack` 两条
        # 路上的失败提示都不能悄悄消失（media.html 里 `tryPlay` 那段注释）。
        await S.js("au.pause(); au.play = function () {"
                   " return Promise.reject(new DOMException('x', 'NotAllowedError')); }; 1")
        await asyncio.sleep(0.3)
        old = await S.js("document.getElementById('toast').textContent")
        await S.js("document.getElementById('ppBtn').click()")
        await asyncio.sleep(1.0)
        msg = await S.js("document.getElementById('toast').textContent")
        worst |= ck("★ 放不出来时说人话，不是静默",
                    bool(msg) and msg != old and "播放" in str(msg), f"toast={msg!r}")

        print("\n=== settings.html · 设置 ===")
        await S.goto("/settings.html", 2.6)
        # ★ 2026-09-25：那张只读表搬进了「关于我们」的 `<details>` 里（整页照
        #   `设置.png` 重做，参考图这个位置就是一行带箭头的条目）。
        #   ⚠️ **先展开再读**：闭合的 `<details>` 里 `innerText` 是**空字符串**
        #      （`innerText` 只给"渲染出来的字"），不展开的话下面那条
        #      「key 是脱敏的」会读到 "" 然后**报红**，而页面其实是好的。
        #      所以这里不是"顺手改个选择器"，是"这条断言必须模拟用户那一下点击"。
        await S.js("document.getElementById('aboutBox').open = true")
        await asyncio.sleep(0.3)
        ro = await S.js("JSON.stringify({pill: document.getElementById('connPill').textContent,"
                        " rows: document.querySelectorAll('.ro > div').length,"
                        " text: document.getElementById('ro').innerText,"
                        " hasSw: !!document.getElementById('ttsSw'),"
                        " srcBtns: document.querySelectorAll('.src-btn[data-spec]')"
                        ".length})")
        worst |= ck("连上并读到 hello", ro["pill"] == "已连接" and ro["rows"] >= 6,
                    f"{ro['pill']} · {ro['rows']} 行")
        worst |= ck("★ key 是脱敏的",
                    "sk-****" in ro["text"] and "95e04fb2" not in ro["text"],
                    "")
        # ★ 2026-09-24 这条**判据翻面了**：原来叫「有语音开关、有数据源」，
        # 要求 settings 页上恰好 4 颗 `.src-btn[data-spec]`。那张「数据源」卡片
        # 当天删了，所以现在要**恰好 0 颗** —— 它守的从"四个都在"变成"别漏回来"。
        # ⚠️ 语音开关那一半不变（`#ttsSw` 还在）。但 2026-09-25 之后它**不再是**
        #    "本页唯一还能改的东西" —— 旁边多了「疲劳横幅」「提示条」两个开关
        #    （住 `XQ.prefs`，真的会改全站行为）。本条只验这个键，别顺手扩成
        #    三条，那三条的判据在下面另立。
        worst |= ck("有语音开关、切源按钮一个都不剩",
                    ro["hasSw"] and ro["srcBtns"] == 0,
                    f"ttsSw={ro['hasSw']} srcBtns={ro['srcBtns']}（期望 0）")
        # 语音开关真的写进 localStorage（键是 `xq.tts.on` —— ★ 2026-09-25 之前
        # 左栏那个喇叭按钮用的是**同一个键**，那句"和左栏那个是同一个键"现在没有
        # 第二方了，键名本身没变）
        # ⚠️ 两次 `Runtime.evaluate` 共享同一个全局词法作用域，所以**不能两次都写
        # `const s=…`** —— 第二次会抛 "Identifier 's' has already been declared"，
        # 而 Runtime.evaluate 的异常是走**返回值**里的 exceptionDetails，走不到
        # `note()` 那个事件通道，于是报错被吞掉、断言只是"没生效"，看着像产品坏了。
        # 用 IIFE 包起来，作用域各归各。
        TTS_SW = ("(function (v) { var e = document.getElementById('ttsSw');"
                  " e.checked = v; e.dispatchEvent(new Event('change')); return 1; })(%s)")
        await S.js(TTS_SW % "false")
        await asyncio.sleep(0.5)
        st1 = await S.js("JSON.stringify({ls: localStorage.getItem('xq.tts.on'),"
                         " on: XQ.tts.on})")
        await S.js(TTS_SW % "true")
        await asyncio.sleep(0.5)
        st2 = await S.js("JSON.stringify({ls: localStorage.getItem('xq.tts.on'),"
                          " on: XQ.tts.on})")
        worst |= ck("★ 语音开关真的落到同一个键",
                    st1["ls"] == "0" and st1["on"] is False
                    and st2["ls"] == "1" and st2["on"] is True,
                    f"关 -> {st1}  开 -> {st2}")

        # ---------------------------------------------------------- 控制台
        print("\n=== 控制台 ===")
        if S.errs:
            for lvl, txt in S.errs[:20]:
                print(f"  !!  {lvl}：{txt}")
            worst |= 1
        else:
            print("  OK  全程零报错零警告")
        if S.noise:
            print("  --  另滤掉高德 SDK 自己发的性能提示 %d 条（%s）"
                  % (S.noise, "、".join(SDK_NOISE)))

    print()
    return worst


# ⚠️ 这个 `if` 不能省：`_probe_*.py` 那类一次性探针要 `from _check_pages import Session`
# 复用这里的 CDP 管道，少了守卫，import 会**把整套检查跑一遍再 exit**。
if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
