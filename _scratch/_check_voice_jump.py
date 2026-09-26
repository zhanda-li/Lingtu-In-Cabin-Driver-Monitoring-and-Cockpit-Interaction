# -*- coding: utf-8 -*-
"""语音说「打开某一页 / 导航」→ **真页面上真的跳过去了**（headless Edge + 假麦克风 + CDP）。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_check_voice_jump.py

用户原话：「它可以对这个网页所有东西进行操控 比如我让它导航它肯定真导航啊 直接跳转
这些啊 我让它干嘛肯定干嘛啊 它肯定要拥有这些网页的操控权啊」。这一份验的就是
**"真页面上真的跳了"**那半句 —— `location.pathname` 真的变没变。

和另外两份**必须一起看，缺一份就不算**：

  · `_check_voice_do.py`（纯 Python 扮演页面）—— 服务端**发没发** `do`（`go:media` /
    `rest_stop`）、`do` 带没带 `seq`、按回执挑的**是哪句话**。它**验不到跳转**：
    那一侧的"页面"是 Python，没有 `location.href`。
  · 这一份 —— **真浏览器**里收到 `do` 之后，`location.pathname` 真的变了没有、
    已经在那一页上时**有没有白重载**、回执里 `same`/`here` 有没有真的发出去。
  · `_probe_nav_jump.py` —— 那三颗**按钮**跳过去之后，目的页上**真有数据**。

判据：
  A ★ **语音说「打开多媒体」→ 这一页真的开到 `/media.html`**（端到端：假麦克风放音频
    → KWS 唤醒 → whisper 出文字 → 服务端 `detect_action` 判成 `go:media` → 发 `do`
    → `wake.js` 收到 → `location.href`）。这一条**只有真浏览器里跑得出来**。
  B ★ 已经在那一页上时（在 `detail.html` 上喊「打开驾驶监测」）→ 回执里 **`same:true`
    真的发出去了**，而且**不许白重载**（`location.pathname` 一动不动）——
    重载会把这一页的现场全丢掉。
  C ★ 喊「导航」→ `location.pathname` 变 `/nav.html` 且 `search` 是
    **`?ask=rest_stop`** —— 用户拍板的是「跳过去 + 问一句」，所以跳过去**只问**、
    不直接查（那一问由 nav.html 定完起点之后发 `{"type":"ask"}` 要，见 `ui/server.py`
    的 `voice_ask`）。⚠️ 这个参数 2026-09-26 从 `?do=nearby` 改过来的：
    `?do=nearby` 是**页面上那三颗按钮**走的路（人点的，没有"要不要我导"这一问），
    两条路都还在，别把旧的当过期删掉。
  D 浏览器里那两个小函数（`navTarget` / `samePage`）对五个键、五个页名逐一算对 ——
    它们和 `xiaorui.PAGES` 是**两份手抄的表**，抄错了跳到白页，而白页看起来像没做。
  E `detail.html` 那一段控制台零报错。

⚠️ **A 段为什么起在 `detail.html` 而不是首页**：`wake.js` 只挂在
   `detail.html` / `monitor.html` / `nav.html` 这三张上（首页和 media 页**没有耳朵**，
   这是 design，不是漏了）。所以"说话了 → 真跳过去"这件事只能在有耳朵的页面上演，
   而落点挑 `media.html` 正合适 —— 它**故意没有 wake.js**，一跳过去这一页的耳朵就
   跟着页面一起没了，不会又录第二轮。
⚠️ **它证明不了**：真人在车里喊，唤醒/识别准不准（假麦克风放的是合成 wav）；
   延迟数字（headless 时序不是真机）；跳到 `nav.html` 之后**高德那边有没有数据**
   （那是 `_probe_nav_jump.py` / `_check_amap.py` 的账）；**`nav.html` 的控制台**
   （它要加载高德 SDK，`INVALID_USER_DOMAIN` 那类错归 `_check_pages.py` 管 ——
   在这儿一起断言的话，高德那一侧的毛病会把这颗跳转的判据染红，两件事分不开）。
⚠️ 假麦克风的循环体是**样本 + 10.5 s 静音**：断句判据现在是 10 s（用户拍板
   「语音结束的标志是我中途 10s 没有发出声音」）。补静音短于 10 s 的话这一轮
   **永远收不了口**，表现是"叫醒了、什么都对、就是没有答复" —— 那是道具的毛病。
   （`_check_wake_browser.py` 里那个 `PAD_S = 6.0` 就是改 10 s 之前的数，别照抄。）
⚠️ 服务自己起自己收（`--source demo`，不抢摄像头）。两份会话各用一个 CDP 端口。
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parent
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(ROOT / "ui"))
# ⚠️ 端口必须**在 import 之前**塞进 argv：`_check_pages.BASE` 是 import 那一刻用
#    `PORT` 拼死的，import 之后再改 `CP.PORT` 不管用（那边第 58-64 行记了这个坑）。
PORT = "8805"
sys.argv = [sys.argv[0], PORT]
# ⚠️ C: 盘满的时候 `tempfile.mkdtemp()` 是**静默失败**的（见 memory 那条），而
#    `_check_pages.Session` 拿它当 `--user-data-dir`。所以临时目录先挪到 D:。
#    必须在 `tempfile` 第一次用之前设 —— 它在 `_check_pages` import 之后才用，
#    但那次用的就是这一刻的环境变量。
_TMP = ROOT / "runs" / "_tmp_jump"
_TMP.mkdir(parents=True, exist_ok=True)
for _k in ("TEMP", "TMP", "TMPDIR"):
    os.environ[_k] = str(_TMP)
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import _check_pages as CP                                  # noqa: E402
from _check_pages import Session                           # noqa: E402
import xiaorui                                             # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
SAMPLES = ROOT / "runs" / "wake_samples"
LOG = ROOT / "runs" / "_check_voice_jump_srv.log"
PAD_S = 10.5                      # 见文件头：断句判据 10 s + 一片余量
JUMP_MS = 180                     # `wake.js` 先回执、再跳，中间那一段（见那边的注释）
SAMPLE_S = 3.8                    # 样本本身大约多长（只用来打一行人看的字）
BAD = []
# 和 `_check_wake_browser.py` 同一条：`ScriptProcessorNode` 被标了 deprecated，
# 那是**明知故犯**的（理由写在那个文件的 KNOWN_WARNINGS 里），不是这一页的毛病。
KNOWN_WARNINGS = ("ScriptProcessorNode is deprecated",)


def ok(cond, what, extra=""):
    print("  %s %-52s %s" % ("OK  " if cond else "!!  ", what, extra))
    if not cond:
        BAD.append(what)
    return cond


def real_errs(errs):
    """滤掉已知且接受的那几条（`Session.note()` 已经滤过 404 和高德那一条）。"""
    return [e for e in errs if not any(k in e[1] for k in KNOWN_WARNINGS)]


def mic_wav(name: str, src: Path | None) -> Path:
    """拼一份假麦克风的循环体：`src` 的音频 + `PAD_S` 秒数字静音（`src=None` 全静音）。

    ⚠️ 采样率照抄源文件、**不重采样**：`--use-file-for-fake-audio-capture` 交上来的是
       设备流，浏览器自己会重采样到页面的 16000（`_check_wake_browser.py` 试过）。
    """
    out = _HERE / name
    # ⚠️ 顺序别抄错：`nch, width, sr` —— `getframerate()` 是**采样率**不是位宽。
    #    写成 `getnchannels, getsampwidth, getframerate` 赋给 `sr, nch, width` 的话，
    #    `setsampwidth(22050)` 会当场报 `bad sample width`（2026-09-26 就这么写的）。
    sr, nch, width = 22050, 1, 2
    raw = b""
    if src is not None:
        with wave.open(str(src), "rb") as w:
            nch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
            raw = w.readframes(w.getnframes())
    with wave.open(str(out), "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(width)
        w.setframerate(sr)
        w.writeframes(raw + b"\x00" * (int(PAD_S * sr) * nch * width))
    return out


# ★ 把页面**发出去**的 `do_result` 记下来（存 sessionStorage，翻页也带得走）。
#
# ⚠️ 为什么挂在 `WebSocket.prototype.send` 上而不是 `XQ.wake.link.send`：
#    `link.send` 是页面脚本建好之后才有的，而这个桩必须在**任何页面脚本之前**装好
#    （CDP 的 addScriptToEvaluateOnNewDocument），那时候 `XQ` 还不存在。
#    底下那个 `send` 确实走的是 `ws.send(JSON.stringify(o))`（live.js:1980），
#    所以挂在原型上抓得到 —— 而且**只记不光转发**（原样 `call` 下去）。
# ⚠️ 为什么非要"发出去的那一份"而不是只看屏幕：**验送达，别只验后果**。
#    `location.pathname` 变了是后果；这一份记录才是"页面到底回了什么"。
#    两者缺一，`same:true` 有没有真的发出去这件事就查不出来 —— 而这个项目有过
#    一模一样的先例：`_check_wake_browser.py` 第一版就是服务端全绿、页面全哑，
#    因为没有这条记录，"没叫醒 / 叫醒了没显示 / 显示了没画出来"三件事长得一样。
HOOK_SENT = """
(function () {
  var O = WebSocket.prototype.send;
  WebSocket.prototype.send = function (d) {
    try {
      var m = JSON.parse(d);
      if (m && m.type === 'do_result') {
        var a = [];
        try { a = JSON.parse(sessionStorage.getItem('xq.sent') || '[]'); } catch (e) {}
        a.push(m);
        sessionStorage.setItem('xq.sent', JSON.stringify(a.slice(-20)));
      }
    } catch (e) {}
    return O.call(this, d);
  };
})();
"""


class MicSession(Session):
    """带假麦克风的会话。`EXTRA_FLAGS`/`PRELOAD` 是 `_check_pages.Session` 留的口子。

    ⚠️ 是**实例属性**不是类属性：两个会话放的是不同的 wav（一个有话说、一个纯静音），
       类属性是 import 时算死的，写在那儿两个会话就只能共用一个文件。
    """

    def __init__(self, cdp, wav: Path):
        super().__init__(cdp)
        self.EXTRA_FLAGS = [
            "--use-fake-device-for-media-stream",
            "--use-fake-ui-for-media-stream",
            "--use-file-for-fake-audio-capture=" + str(wav),
        ]
        self.PRELOAD = [HOOK_SENT]


async def until(fn, secs=30.0, every=0.4):
    t0 = time.monotonic()
    while time.monotonic() - t0 < secs:
        v = await fn()
        if v:
            return v
        await asyncio.sleep(every)
    return None


async def sent(S):
    """这一页至今发出去的 `do_result`（翻页带走的那份）。空表是 falsy，`until` 认这个。"""
    return (await S.js("sessionStorage.getItem('xq.sent') || '[]'")) or []


def show(tag, m):
    print("      %s：%s" % (tag, json.dumps(m, ensure_ascii=False)[:170]))


def nav_entries():
    """`chrome.js` 的 `const NAV` → [(键, 标签, 文件)]（和 `_check_voice_do.py` 同一份读法）。"""
    src = (ROOT / "ui" / "web" / "chrome.js").read_text(encoding="utf-8")
    i = src.index("const NAV = [")
    j = src.index("\n];", i)
    return [m.groups() for m in re.finditer(
        r"\[\s*'([A-Za-z_]+)'\s*,\s*'([^']*)'\s*,\s*'([^']+)'", src[i:j])]


# =============================================================== A 语音 → 真跳页
async def case_A(wav: Path) -> None:
    print("\n── A 在 detail.html 上说「打开多媒体」→ 这一页真的开到 /media.html")
    async with MicSession(9441, wav) as S:
        await S.goto("/detail.html", wait=1.0)
        # ⚠️ 等它自己起：`autostart()` 挂在 `hello` 里，hello 要等 WS 连上。写死几秒
        #    去读是**赌**（和 `_check_wake_browser.py` A 段同一个理由）。
        st = None
        for _ in range(15):
            st = await S.js("XQ.wake && XQ.wake.state")
            if st in ("listening", "error"):
                break
            await asyncio.sleep(1.0)
        if not ok(st == "listening", "detail.html 开着麦、在听（state=%r）" % st):
            return
        heard, p = "", "/detail.html"
        t0 = time.monotonic()
        while time.monotonic() - t0 < 90:
            p = await S.path()
            if p != "/detail.html":
                break
            # ⚠️ 必须在**跳走之前**读到它：一跳过去 `XQ.wake` 就没了（media.html 上
            #    没有 wake.js），那时候读回来的是 undefined，而 `heard` 留着上一轮的
            #    值正是我们要的。读 `听到的原文` 而不是只看跳没跳，是为了把这次跳转
            #    钉死在**语音**这条路上：换页也可能是别的原因（脚本崩、点错了）。
            h = await S.js("XQ.wake && XQ.wake.lastHeard")
            if h:
                heard = h
            await asyncio.sleep(0.3)
        print("      %.1f 秒后 location.pathname = %r" % (time.monotonic() - t0, p))
        ok(p == "/media.html", "★ 语音把它**真的开到了** /media.html", "现在是 %r" % p)
        ok("多媒体" in xiaorui.zh_t2s(heard),
           "★ 而且是被那句语音带过去的（识别里出现过「多媒体」）", "heard=%r" % heard)
        got = await until(lambda: sent(S), secs=3)
        show("跳过去的那一页上，sessionStorage 里存着的回执", (got or [{}])[-1])
        m = (got or [{}])[-1]
        ok(m.get("id") == "go:media" and m.get("ok") is True,
           "★ 回执是「go:media 我答应了」（页面自己发的，翻页也带过来了）")
        ok((await S.js("!!(window.XQ && XQ.NAV)")) is True,
           "落地的那一页是正常的页面（XQ.NAV 在）")

        # ---------------------------------------------------------- E 控制台
        # ⚠️ 只打不断言：这一轮跨了 detail.html 和 media.html **两份文档**，报错混在
        #    一起分不出是谁的。detail.html 那一半由下一段咬死，media.html 那一半归
        #    `_check_media_lib.py`。在这儿断言只会得到一条查不出根因的红。
        errs = real_errs(S.errs)
        print("      （A 段两份文档加起来 %d 条报错/警告，只记录不断言：%s）"
              % (len(errs), "；".join("%s %s" % e for e in errs[:2]) or "无"))


# ==================================================== B/C/D 回执与"白重载"
async def case_BCD(wav: Path) -> None:
    print("\n── B 已经在那一页上：「打开驾驶监测」→ 回执 same:true，且**不重载**")
    async with MicSession(9442, wav) as S:
        await S.goto("/detail.html", wait=1.0)
        st = None
        for _ in range(15):
            st = await S.js("XQ.wake && XQ.wake.state")
            if st in ("listening", "error"):
                break
            await asyncio.sleep(1.0)
        on = await S.js("!!(XQ.wake && XQ.wake.link && XQ.wake.link.online)")
        if not ok(st == "listening" and on is True,
                  "detail.html 开着麦、连着服务端（state=%r online=%s）" % (st, on)):
            return
        # ★★ 假麦克风放的是**纯静音**：这一页不会自己叫醒自己，回执只可能来自下面
        #    这两针。于是"页面做对了什么"和"服务端说了什么"彻底分开 —— 这一段验
        #    的纯粹是**页面那一侧**。
        # ---------------------------------------------------------- B 不跳
        await S.js("sessionStorage.removeItem('xq.sent'); 1")
        await S.js("XQ.wake.onMsg({ev:'do', id:'go:mon', seq:424242}); 1")
        got = await until(lambda: sent(S), secs=6)
        m = (got or [{}])[-1]
        show("页面发出去的 do_result", m)
        ok(m.get("id") == "go:mon" and m.get("seq") == 424242,
           "回执认的是同一条指令（id/seq 原样带回）")
        ok(m.get("ok") is True and m.get("same") is True,
           "★ 回执里 **`same:true` 真的发出去了** —— 服务端靠它换一句"
           "「你就在这一页上」")
        await asyncio.sleep(JUMP_MS / 1000.0 + 0.6)
        p = await S.path()
        ok(p == "/detail.html", "★ 而且**没有白重载**（还在 detail.html）",
           "现在是 %r" % p)

        # ---------------------------------------------------------- C 控制台（B 段）
        errs = real_errs(S.errs)
        ok(not errs, "到这一步为止控制台零报错", "；".join("%s %s" % e for e in errs[:3]))

        # ---------------------------------------------------------- C 真跳
        print("\n── C 喊「导航」→ 跳到 nav.html?ask=rest_stop")
        await S.js("sessionStorage.removeItem('xq.sent'); 1")
        await S.js("XQ.wake.onMsg({ev:'do', id:'rest_stop', seq:424243}); 1")
        got = await until(lambda: sent(S), secs=6)
        m = (got or [{}])[-1]
        show("页面发出去的 do_result", m)
        ok(m.get("ok") is True, "★ 回执说「答应了、这就去做」（ok:true）")
        ok(not m.get("here"), "这时**没有**报 here（这一页确实要重新进来）",
           "here=%r" % m.get("here"))
        # 等它跳走（页面自己 setTimeout 180 ms 之后才动，别当场就读）
        p = "/detail.html"
        for _ in range(24):                                # 最多 12 s
            p = await S.path()
            if p != "/detail.html":
                break
            await asyncio.sleep(0.5)
        q = await S.js("location.search")
        ok(p == "/nav.html", "★ 真的跳到了 /nav.html", "现在是 %r" % p)
        ok(q == "?ask=rest_stop",
           "★ 而且带着 ?ask=rest_stop（这一页据此**替小瑞问那一句**）",
           "search=%r" % q)
        # ★★ 2026-09-26：`?ask=rest_stop` 是**语音那条路**的东西（用户拍板的
        #    「跳过去 + 问一句」）。页面上那三颗按钮走的仍是 `?do=nearby`
        #    （`app.js:455` / `chat.html:473` / `detail.html:733`）—— 那是人点的，
        #    不是语音判的，没有「要不要我导」这一问。**两条路都要在**，别把
        #    `?do=nearby` 当成过期的删掉（`nav.html` 的 `WANT` 那一支还在用它）。
        # ⚠️ `nav.html` 之后**不再断言控制台**：那一页要加载高德 SDK，`INVALID_USER_DOMAIN`
        #    那类错归 `_check_pages.py` / `_check_amap.py` 管。在这儿一起断言的话，
        #    高德那一侧的毛病会把这颗"跳转"的判据染成红的，两件事分不开。
        errs = real_errs(S.errs)
        print("      （到这儿为止一共 %d 条报错/警告，含 nav.html 的：%s）"
              % (len(errs), "；".join("%s %s" % e for e in errs[:2]) or "无"))

        # ---------------------------------------------------------- D 两张表
        print("\n── D 浏览器里那两个小函数，对五个键逐一算对")
        want = {k: f for k, _, f in nav_entries()}
        keys = list(xiaorui.PAGES)
        ok(set(keys) == set(want), "★ 两张手抄的表的键一模一样",
           "PAGES=%s NAV=%s" % (keys, list(want)))
        got = {k: await S.js("navTarget(%s)" % json.dumps(k)) for k in keys}
        ok(got == want, "★ navTarget(键) 就是 chrome.js 里那五个文件",
           json.dumps(got, ensure_ascii=False))
        files = list(want.values())
        tbl = await S.js("JSON.stringify(%s.map(function(f){return samePage(f)}))"
                         % json.dumps(files))
        # 现在站在 nav.html 上 → 只有 nav.html 那一项该是 true
        ok(tbl == [f == "nav.html" for f in files],
           "★ samePage 只对**当前这一页**说是（其余四个不是）", "%s" % tbl)
        # 认不出来的键必须回空串（wake.js 靠它回 `no_target` 让服务端照实说）
        bad = await S.js("JSON.stringify([navTarget('不存在'), navTarget(''), "
                         "navTarget(null)])")
        ok(bad == ["", "", ""], "★ 认不出的键回空串（不编一个页名出来）", bad)


async def main():
    jump_wav = mic_wav("_fake_mic_jump.wav", SAMPLES / "pos_goto_media.wav")
    mute_wav = mic_wav("_fake_mic_mute.wav", None)
    print("假麦克风：%s（%.1f s 说话 + %.1f s 静音）、%s（纯静音）"
          % (jump_wav.name, SAMPLE_S, PAD_S, mute_wav.name))
    log = open(LOG, "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", PORT,
                            "--source", "demo"],
                           cwd=str(ROOT), stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    try:
        up = False
        # ⚠️ 给到 60 s（别的检查脚本是 20 s）：2026-09-26 头一次跑时，同一个启动命令
        #    整整 30 s 一个字都没吐出来（日志 0 字节、端口也没人听），重跑就正常 ——
        #    冷启动要先摸几十 MB 的 whisper/KWS 权重，杀软扫一遍的量级不是常数。
        #    预算不够时的表现是"服务没起来"，而真凶（慢，不是坏）在那句话里看不出来。
        for _ in range(120):
            try:
                with urllib.request.urlopen(CP.BASE + "/music.json", timeout=3):
                    up = True
                    break
            except Exception:                              # noqa: BLE001
                time.sleep(0.5)
        if not up:
            log.flush()
            raise RuntimeError("服务没起来（等了 60 s）。日志尾巴：\n%s"
                               % "".join(LOG.read_text(encoding="utf-8",
                                                      errors="replace").splitlines(True)[-8:]))
        await case_A(jump_wav)
        await case_BCD(mute_wav)
    finally:
        srv.terminate()
        try:
            srv.wait(timeout=10)
        except Exception:                                  # noqa: BLE001
            srv.kill()
        log.close()
        # 探针的中间产物不是资产，跑完清掉（和 `_probe_rest_stop_wav.py` 一个规矩）
        for f in (jump_wav, mute_wav):
            try:
                f.unlink()
            except OSError:
                pass

    print("\n" + "=" * 74)
    if BAD:
        print("❌ %d 条不对：%s" % (len(BAD), "、".join(BAD)))
        return 1
    print("✅ 全对 —— 语音说的话，**真的**让这一页跳到目标页去了；已经在那一页上时"
          "不白重载、而且那句话也真的换成了「你就在这一页上」。")
    return 0


if __name__ == "__main__":
    rc = asyncio.run(main())
    sys.stdout.flush()
    os._exit(rc)
