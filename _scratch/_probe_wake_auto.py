# -*- coding: utf-8 -*-
"""**不按任何一下**，直接说「你好，小瑞」能不能叫醒 —— 落地前必须实测的三件事。

用户 2026-09-25 晚问的原话：
    「能不能不需要我按就可以说你好小瑞 然后唤醒了」

`ui/web/wake.js` 现在是**故意不自动开麦**的（文首第 1 条纪律，抄的是用户对
摄像头那句「只有我点接入摄像头才接入」）。用户现在要把这条翻过来 —— 但翻之前
得先知道**翻过去之后是活的还是死的**，因为这条路有三种失败，而且**前两种都不报错**：

  ① **权限**：`getUserMedia` 规范上**不需要**用户手势，Chrome/Edge 也不拦 ——
     但它会弹权限框。kiosk 全屏下那个框是个气泡，弹在哪儿、看不看得见，没人知道。
     更糟的是**框在等**的时候，promise 既不 resolve 也不 reject：页面停在
     'starting'，界面上就一句「正在起麦克风…」**永远转下去**。
  ② **AudioContext 自动播放策略**：`new AudioContext()` 在没手势的页面上可能是
     `suspended`。**suspended 的 context 里 `onaudioprocess` 一次都不触发** ——
     于是状态显示 `listening`、按钮亮着、界面说「在听」，而**一帧音频都没收到**。
     这正是本项目最怕的那类"不报错的坏掉"（静音检测、摄像头全零音轨都是这一族）。
     ⚠️ **`wake.js` 现在没有检查 `ctx.state`** —— 这个洞是真的。
  ③ **`start()` 要连上服务端**（`link.online` + 引擎状态到手）才能起，所以"自动开麦"
     的挂点只能是 `hello` 之后，不能写在 DOMContentLoaded 里。

这一支就量这三件事，两臂对照：

  · 臂 A **没有权限**（不传 `--use-fake-ui-for-media-stream`，等价于"这台机器上
    从来没人点过允许"）→ 预期是卡在 `starting`，`why` 一个字都没有。
  · 臂 B **已经给了权限**（传那个 flag = 用户点过允许、浏览器记住了）→ 这才是我要
    的答案：`ctx.state` 是什么、音频片涨不涨、**唤醒和答复会不会自己发生**。

★ **两臂都不点任何东西**：`Runtime.evaluate` 默认 `userGesture=false`，所以这两次
  `XQ.wake.start()` 和"页面加载时自己调一次"在浏览器眼里**是同一件事**。

⚠️ **它证明不了**：真机上权限框长什么样（headless 里根本没有那个框）、真人嘴上的
   唤醒率、延迟数字。这三件事只有目标和真嘴算数。

    D:\\Anaconda3\\envs\\dms\\python.exe _scratch\\_probe_wake_auto.py
"""
import asyncio
import io
import os
import subprocess
import sys
import time
import urllib.request
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from _check_pages import Session, ck                      # noqa: E402

PY = r"D:\Anaconda3\envs\dms\python.exe"
ROOT = HERE.parent
PORT = "8811"
BASE = "http://127.0.0.1:%s" % PORT

_TMP = HERE / "_tmp"
_TMP.mkdir(exist_ok=True)
os.environ["TMP"] = os.environ["TEMP"] = str(_TMP)

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8",
                              errors="replace")

SRC_WAV = ROOT / "runs" / "wake_samples" / "pos_hello_xiaorui_slow.wav"
FAKE_WAV = HERE / "_fake_mic_loopback.wav"
PAD_S = 6.0


def build_fake_mic() -> None:
    """和 `_check_wake_browser.py` 同一个假麦克风循环体：原样本 + N 秒数字静音。

    ⚠️ 采样率照抄源文件、不重采样（理由见那个文件的注释）。
    ⚠️ 尾部静音不能省：Chrome 是**循环**放这个文件的，样本尾只有 0.7 s 静音，
       短于 0.9 s 的断句线 —— 那样"说完了"永远判不出来，表现是"叫醒了、听到了、
       最后给你一句太长了"。那是**测试道具的毛病**，不是产品行为。
    """
    with wave.open(str(SRC_WAV), "rb") as w:
        nch, width, sr, n = (w.getnchannels(), w.getsampwidth(),
                             w.getframerate(), w.getnframes())
        raw = w.readframes(n)
    with wave.open(str(FAKE_WAV), "wb") as w:
        w.setnchannels(nch)
        w.setsampwidth(width)
        w.setframerate(sr)
        w.writeframes(raw + b"\x00" * (int(PAD_S * sr) * nch * width))


MIC_FLAGS = ["--use-fake-device-for-media-stream",
             "--use-file-for-fake-audio-capture=" + str(FAKE_WAV)]


class NoPerm(Session):
    """臂 A：**没人点过允许**。设备是真的（假麦克风），但权限框会拦在那儿。"""
    EXTRA_FLAGS = list(MIC_FLAGS)


class HasPerm(Session):
    """臂 B：**权限早就给过了**（这个 flag 的语义就是"自动点允许"，不产生假设备
    —— 产生假设备的是 `--use-fake-device-for-media-stream`，两个名字很像，别搞混）。

    ⚠️ `Session` 的基类**硬写着** `--autoplay-policy=no-user-gesture-required`，
       而 `server.py` 的 `open_browser()`（第 1320 行）也带着同一条 —— 所以
       **这一臂等价于"用 run_ui.bat 启动"**。那"用户自己开个浏览器敲地址"呢？
       见臂 C。"""
    EXTRA_FLAGS = list(MIC_FLAGS) + ["--use-fake-ui-for-media-stream"]


# ---------------------------------------------------------------- 臂 C 的道具
# 臂 C 要问的是：**没有那条 `--autoplay-policy` 会怎样**。`Session` 把它写死在
# `__aenter__` 里了，所以这里在 `subprocess` 这一层把它摘掉 —— `_check_pages` 里
# 写的是 `subprocess.Popen(...)`（调用时按模块名解析），所以在模块上换掉就够。
# ⚠️ `--use-fake-ui-for-media-stream` 换成 `--use-fake-ui-…` 是不行的：两个
#    flag 管的是**完全不同**的两件事，别把"免权限框"和"免手势"混成一条。
_POPEN = subprocess.Popen
_STRIP = {"on": False}


def _popen_filtered(cmd, *a, **kw):
    if _STRIP["on"] and isinstance(cmd, list):
        cmd = [c for c in cmd if not c.startswith("--autoplay-policy")]
    return _POPEN(cmd, *a, **kw)


subprocess.Popen = _popen_filtered


class NoPolicy(HasPerm):
    """臂 C：权限给了，但**启动参数里没有** `--autoplay-policy` —— 在浏览器眼里
    这跟"用户自己开一个 Edge、直接敲 127.0.0.1:8765"是同一件事。

    ★ 这一臂存在的理由：`ctx.state` 一旦是 `suspended`，`onaudioprocess`
      **一次都不触发**，而 `wake.js` 会把状态行写成「在听 —— 说「你好，小瑞」」。
      那正是本项目的头号失败形态：**不报错的坏掉**。这一臂就是要把它逼出来。"""
    EXTRA_FLAGS = list(HasPerm.EXTRA_FLAGS)


# ★ 把服务端发来的语音事件记下来。没有它，"状态还是 listening"这一句话同时符合
#   三件完全不同的事：没叫醒 / 叫醒了但没显示 / 显示了但没画出来（`_check_wake_browser`
#   的头一条注释就是这么栽的）。⚠️ 必须**包着原函数**调 —— 只记录不转发 = 自己把
#   被测的东西拆了。
HOOK_EVS = """
(function () {
  window.__evs = [];
  if (!window.XQ || !XQ.wake) return 'no XQ.wake';
  var orig = XQ.wake.onMsg.bind(XQ.wake);
  XQ.wake.onMsg = function (d) {
    window.__evs.push((d.ev || '?') + (d.text ? ':' + d.text
                                       : (d.why ? ':' + d.why : '')));
    return orig(d);
  };
  return 'ok';
})()
"""

SNAP = """JSON.stringify({
  state: XQ.wake.state, why: XQ.wake.why,
  want: (function () { try { return sessionStorage.getItem('xq.wake.want'); }
                       catch (e) { return 'ERR'; } })(),
  label: (document.querySelector('#wake .wk-label') || {}).textContent || '',
  pressed: (document.getElementById('wake') || {}).getAttribute
    ? document.getElementById('wake').getAttribute('aria-pressed') : null,
  online: !!(XQ.wake.link && XQ.wake.link.online),
  sent: XQ.wake.sent, frames: XQ.wake.frames, lost: XQ.wake.lost,
  sr: XQ.wake._ctx ? XQ.wake._ctx.sampleRate : null,
  ctx: XQ.wake._ctx ? XQ.wake._ctx.state : null,
  tracks: XQ.wake._stream
    ? XQ.wake._stream.getTracks().map(function (t) { return t.readyState; }) : [],
  host: (document.getElementById('wakeHost') || {}).textContent || '',
  partial: XQ.wake.partial, heard: XQ.wake.lastHeard, reply: XQ.wake.reply,
  bubbles: Array.prototype.map.call(document.querySelectorAll('#bubbles .b'),
    function (b) { return b.querySelector('p').textContent; }),
  evs: (window.__evs || []).slice(-14)
})"""


async def snap(S):
    return await S.js(SNAP)


STUCK = ("★ 这两件事**同形**：状态还是 'starting' 而 `why` 是空的 —— 权限框在等一个"
         "永远不会有的人点。界面上只有一句「正在起麦克风…」永远转下去。")


async def arm(label, cls, cdp, want_wake, strip_policy=False):
    """开一个浏览器、**不点任何东西**、直接调 start()，然后量到底发生了什么。"""
    print("\n" + "=" * 74)
    print("臂 %s" % label)
    print("=" * 74)
    worst = 0
    _STRIP["on"] = strip_policy
    async with cls(cdp) as S:
        # 浏览器已经在 `__aenter__` 里起好了（要摘的 flag 只在启动那一刻有意义），
        # 立刻恢复 —— 不然这个开关会漏到下一臂去，而漏了的形态是"臂 B 悄悄变成了
        # 臂 C"，两个臂都错、还看不出来。
        _STRIP["on"] = False
        await S.goto("/detail.html", 3.0)
        print("  装事件记录器：%s" % await S.js(HOOK_EVS))
        a = await snap(S)
        print("  装之前：state=%r online=%s host=%r"
              % (a["state"], a["online"], a["host"]))
        worst |= ck("%s · hello 到了（没有它 start() 根本起不来）" % label,
                    a["online"], "link.online=%s" % a["online"])

        # ★★ 整支脚本的重点：**不点任何一下，也不手动调 start()** —— 等在
        #    `hello` 之后由**页面自己**调 `XQ.wake.autostart()`（那才是现在真正
        #    上线的那条路）。
        #    ⚠️ 这一行原来是手动的 `XQ.wake.start()`。**改成等它自己起是必须的**：
        #    "我手动调一下能通"证明不了"页面会自己调"，而后者恰恰是这次要交付的东西
        #    —— 手动调那一版**两个臂都是绿的**，可页面上一个音符都没动。
        s = a
        for _ in range(12):
            await asyncio.sleep(1.0)
            s = await snap(S)
            if s["state"] in ("listening", "error"):
                break
        print("  **不点任何一下**，%s 秒后：" % 12)
        print("    state=%r  why=%r" % (s["state"], s["why"]))
        print("    AudioContext: sampleRate=%s  **state=%r**"
              % (s["sr"], s["ctx"]))
        print("    音频片 sent=%s  音轨=%s" % (s["sent"], s["tracks"]))
        print("    状态行说的是：%r" % s["host"])

        # ★★ 这一条管着"功能到底上没上线"：`state` 还是 'off' 就说明
        #    `onHello` 里的 `autostart()` 压根没跑（或它自己退回来了）。
        #    ⚠️ 没有这一条的话，**没上线**和**上线了但起不来**会混成同一个读数。
        worst |= ck("%s · ★★ 是**页面自己**起的（我没点、也没手动调 start）" % label,
                    s["state"] != "off",
                    "state=%r —— 'off' = autostart 没跑" % s["state"])

        if not want_wake:
            # ★ 判据是**"不许静默卡住"**，不是"必须报某个特定的错"。
            #   实测（headless）：headless 里根本没有权限框，Chromium 直接**拒**，
            #   于是 `NotAllowedError` 一路传到状态行上 —— 这是好的那一半。
            #   ⚠️ 但**真机 kiosk 不是这个形态**：那边会弹一个权限气泡。气泡没人点
            #   的时候 promise 既不 resolve 也不 reject，页面就停在 'starting'，
            #   界面上只有一句「正在起麦克风…」永远转下去。**那一半 headless 测不到**，
            #   只能人眼看一次（`_check_asr.py` 的文件头也把这条列在"只能靠人验"里）。
            worst |= ck("%s · 拿不到权限时**必须说实话**（不许静默卡住）" % label,
                        s["state"] == "error" and bool(s["why"]),
                        "state=%r why=%r" % (s["state"], s["why"]))
            print("  ⚠️ headless 里 Chromium 是**直接拒**（没有权限框可弹）。真机 kiosk 上")
            print("     那个气泡没人点的时候是**一直等**，页面会停在 'starting' 转下去 ——")
            print("     这一格 headless 测不到，得人眼看一次。")
            return worst

        # ---- 有权限那一臂：这才是我要的答案
        worst |= ck("%s · 不用点就到了 listening" % label,
                    s["state"] == "listening", "state=%r why=%r"
                    % (s["state"], s["why"]))
        worst |= ck("%s · sampleRate 真的是 16000（不是就成胡话且不报错）" % label,
                    s["sr"] == 16000, "sr=%s" % s["sr"])
        # ★★ 这一条是**整支脚本里最要紧的**：ctx.state 不是 running 的话，
        #    onaudioprocess 一次都不触发 —— 界面显示"在听"、按钮亮着、一片音频
        #    都没有。`wake.js` 现在**不检查这一条**。
        worst |= ck("%s · ★★ AudioContext 是 running（suspended = 界面在撒谎）"
                    % label, s["ctx"] == "running",
                    "ctx.state=%r ← suspended 就意味着 onaudioprocess 永不触发"
                    % s["ctx"])
        worst |= ck("%s · ★★ 音频片真的在往服务端走（没手势）" % label,
                    (s["sent"] or 0) >= 5, "sent=%s" % s["sent"])
        if strip_policy and (s["ctx"] != "running" or (s["sent"] or 0) < 5):
            # ★ 臂 C 的**唯一意义**就是这个分支。它**故意不记成红**（红 = "产品行为
            #   不对"，这里是"我来量一条假设"）：量到的是什么就说什么。
            print()
            print("  🔴 **量到了**：不带 `--autoplay-policy=no-user-gesture-required` 时，")
            print("     AudioContext 是 %r、音频片 %s 片 —— 而状态行写的是 %r。"
                  % (s["ctx"], s["sent"], s["host"]))
            print("     **界面在说「在听」，实际上什么都没收到。** 这就是本项目最怕的")
            print("     那种'不报错的坏掉'，而 `wake.js` 现在**没有检查 `ctx.state`**。")
            print("     ⇒ 自动开麦要上线，必须先补这道哨兵。")
            return worst          # 都收不到音频了，再等 40 s 唤醒没有意义

        # ---- 真的被叫醒（假麦克风循环放的就是「你好，小瑞，我有点困」）
        print("\n  等唤醒（假麦克风一轮 9.7 s，最多等 40 s）…")
        for _ in range(20):
            await asyncio.sleep(2.0)
            s = await snap(S)
            if s["heard"]:
                break
        print("    服务端发来的语音事件：%s" % " | ".join(s["evs"]))
        print("    状态行：%r  第二行听到：%r" % (s["host"], s["heard"]))
        worst |= ck("%s · ★★ 没人碰键盘，它自己被叫醒了并听到了话" % label,
                    bool(s["heard"]), "heard=%r evs=%s"
                    % (s["heard"], " | ".join(s["evs"]) or "一条都没来"))
        r = s
        for _ in range(20):
            if r["reply"]:
                break
            await asyncio.sleep(2.0)
            r = await snap(S)
        worst |= ck("%s · 而且答了话、字画进了气泡" % label,
                    bool(r["reply"]) and any(r["reply"][:8] in b
                                             for b in r["bubbles"]),
                    "reply=%r 共 %d 个气泡"
                    % ((r["reply"] or "")[:40], len(r["bubbles"])))
        errs = [e for e in S.errs
                if "ScriptProcessorNode is deprecated" not in e[1]]
        worst |= ck("%s · 控制台零报错" % label, not errs,
                    "；".join("%s %s" % e for e in errs[:4]))
    return worst


async def arm_stop():
    """臂 D：点过「停」之后翻页，**不许又自己开起来**（这一次会话内黏住）。

    ★ 为什么非要有这一臂：自动开麦最烦人的形态就是"我明明关了，它自己又开了"。
      而它的成因就藏在挂点上 —— `autostart()` 挂在 `onHello` 里，**每翻一页都会跑**
      （座舱是整页导航，不是 SPA）。没有这一臂的话，"关不掉"这件事要等用户在
      答辩现场发现。
    ⚠️ 反面也要成立：**新开一次浏览器必须回到"自己听"** —— 那一条由臂 B 兜着
      （每次都是新起的浏览器、空的 sessionStorage），这里不用重复。"""
    print("\n" + "=" * 74)
    print("臂 D 点过「停」之后翻页，不许又自己开起来")
    print("=" * 74)
    worst = 0
    async with HasPerm(9474) as S:
        await S.goto("/detail.html", 2.5)
        for _ in range(12):
            await asyncio.sleep(1.0)
            if (await snap(S))["state"] == "listening":
                break
        s = await snap(S)
        worst |= ck("D · 前提：它先自己起来了", s["state"] == "listening",
                    "state=%r why=%r" % (s["state"], s["why"]))
        print("  起来之后：state=%r 按钮=%r want=%r"
              % (s["state"], s["label"], s["want"]))

        await S.js("document.getElementById('wake').click()")   # ← 用户点「停」
        await asyncio.sleep(1.2)
        s = await snap(S)
        print("  点「停」之后：state=%r 按钮=%r 状态行=%r want=%r"
              % (s["state"], s["label"], s["host"], s["want"]))
        worst |= ck("D ★ 点一下就停了（状态回 off、按钮变回「听」）",
                    s["state"] == "off" and s["label"] == "听",
                    "state=%r 按钮=%r" % (s["state"], s["label"]))
        worst |= ck("D ★ 「停」被记下来了（sessionStorage，不是 localStorage）",
                    s["want"] == "off", "want=%r" % s["want"])

        # 整页导航换出去再换回来 —— 这正是 `onHello` 会再跑一次的那条路
        await S.goto("/index.html", 2.0)
        await S.goto("/detail.html", 2.5)
        await asyncio.sleep(3.0)
        s = await snap(S)
        print("  翻出去又翻回来：state=%r 按钮=%r 状态行=%r"
              % (s["state"], s["label"], s["host"]))
        worst |= ck("D ★★ 翻页回来**没有**又自己开起来", s["state"] == "off",
                    "state=%r —— 'listening' 就是「关了又被打开」，"
                    "用户会当场看到" % s["state"])
        worst |= ck("D ★ 而且界面如实说「没在听」", "没在听" in s["host"],
                    s["host"])

        # 反面：用户再点一下「听」，就该重新听上（不然「停」变成单向门）
        await S.js("document.getElementById('wake').click()")
        for _ in range(10):
            await asyncio.sleep(1.0)
            if (await snap(S))["state"] in ("listening", "error"):
                break
        s = await snap(S)
        print("  又点一下「听」：state=%r want=%r" % (s["state"], s["want"]))
        worst |= ck("D ★★ 再点一下能重新听上（「停」不是单向门）",
                    s["state"] == "listening", "state=%r why=%r"
                    % (s["state"], s["why"]))
    return worst


async def main():
    if not SRC_WAV.exists():
        print("!! 找不到假麦克风的素材 %s" % SRC_WAV)
        return 1
    if not FAKE_WAV.exists():
        build_fake_mic()
    print("假麦克风循环体：%s（3.7 s 说话 + %.0f s 静音 = 一轮 9.7 s）"
          % (FAKE_WAV.name, PAD_S))

    log = open(ROOT / "runs" / "_probe_wake_auto_srv.log", "w", encoding="utf-8")
    srv = subprocess.Popen([PY, "-u", "ui/server.py", "--port", PORT,
                            "--source", "demo"],
                           cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
    worst = 0
    try:
        up = False
        for _ in range(40):
            try:
                with urllib.request.urlopen(BASE + "/music.json", timeout=3):
                    up = True
                    break
            except Exception:                              # noqa: BLE001
                time.sleep(0.5)
        if not up:
            print("!! 服务没起来（看 runs/_probe_wake_auto_srv.log）")
            return 1
        worst |= await arm("A 从来没人点过「允许」", NoPerm, 9471,
                           want_wake=False)
        worst |= await arm("B 权限给过 + 带 --autoplay-policy（= run_ui.bat）",
                           HasPerm, 9472, want_wake=True)
        worst |= await arm("C 权限给过 + **不带** --autoplay-policy（= 自己开浏览器）",
                           NoPolicy, 9473, want_wake=True, strip_policy=True)
        worst |= await arm_stop()
    finally:
        try:
            srv.terminate()
            time.sleep(0.8)
            if srv.poll() is None:
                srv.kill()
        finally:
            log.close()

    print("\n" + "=" * 74)
    print("EXIT = %d" % worst)
    return worst


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
