# -*- coding: utf-8 -*-
"""常听唤醒 · **浏览器侧**验收（headless Edge + 假麦克风 + CDP）。

    python _scratch/_check_wake_browser.py 8790          # 端口要和起着的那份服务一致

它验的是**只有真浏览器里才有意义**的那几件事 —— 服务端那条链路由
`_check_voice_ws.py` 验（那个脚本更快、更确定，先跑它）。这一份专管：

  A ★ **打开页面就自己开麦**（2026-09-25 晚用户把这条翻过来了，原话
    「能不能不需要我按就可以说你好小瑞 然后唤醒了」；在此之前这条写的是
    「绝不自动开麦」）。仍然用**自己装的计数器**验（`getUserMedia` 被调了几次），
    不是"看界面上像不像" —— 而现在它守的是**另一件事**：**只许开一次**。
    自动开麦 + 按钮重复开 = 两路麦克风抢一个设备，症状是音频片成对地冒。
    这一条**只能**用 `addScriptToEvaluateOnNewDocument` 装桩验（见 Session 的
    PRELOAD 注释）：页面脚本跑起来之后再数，前面的调用已经数不着了。
  B 采样率真的是 16000、音频片真的在涨（不是就**必须**停下并说实话，见 wake.js 第 2 条）。
  C 真的被叫醒 —— 说「你好，小瑞，我有点困」（**假麦克风放的就是这个 wav**），
    页面上必须出现 `wake` → 识别文字 → 答复，而且文字**真的画在气泡里**
    （第 4 条纪律：演示现场静音、语音开关关着都发生过，只出声的版本等于坏了）。
  D 收干净 —— 点那一下停：状态回 `off`、**音轨真的 stop 了**（不 stop 的话
    麦克风指示灯还亮着，和摄像头不 release 就换不了是同一类事），
    而且**翻一页不许又自己开起来**（整页导航会让 `onHello` 再跑一次，
    这是"我明明关了它又开了"唯一的成因 —— 见 wake.js 的 `autostart()`）。
  E 控制台零报错。

⚠️ **它证明不了**的两件事，别拿它冒充：
  1. **在车里、在真人嘴上准不准。** 假麦克风放的是合成 wav，而且这个文件是
     "唤醒词 + 内容"一口气说的 —— 它证明的是"链路通了"，不是"车上也这样"。
  2. **延迟数字。** headless + 假设备的时序和真机不是一回事，这里只断言
     "事件顺序对、都到齐了"，不报毫秒数。真延迟要在目标机器上量。
"""

import asyncio
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from _check_pages import Session, ck                     # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
# ★ 假麦克风放的就是这句「你好，小瑞，我有点困」—— 唤醒词和内容一口气说。
#   挑它是因为它同时验两件事：唤醒命中 + **唤醒前那一秒没丢**（环形缓冲预滚）。
SRC_WAV = ROOT / "runs" / "wake_samples" / "pos_hello_xiaorui_slow.wav"

# ★ 但**不能直接拿它当假麦克风的循环体**，得自己拼一份"样本 + 一段静音"。
#   理由：Chrome 是**循环**放这个文件的，样本结尾只有 0.7 s 静音 —— 短于断句线，
#   于是"说完了"这件事永远判不出来：整句一直被录到状态机的兜底，
#   表现是"叫醒了、也听到了，最后给你一句太长了"。这不是用户会做的事，
#   是**测试道具的毛病**（真人说完就不说了，静音一直来）。
#
# 🔴 **补的静音必须 ≥ 断句判据**，所以这个数是**跟着产品走**的，不是随手定的：
#   2026-09-26 用户把"说完了"改成 **10 s**（「语音结束的标志是我中途 10s 没有
#   发出声音」），而这里原来写的是 6.0 —— **那一天这一整段就悄悄红了**：
#   循环体是「3.7 s 说话 + 6 s 静音」，静音永远到不了 10 s，句子永远收不了口，
#   40 s 里只等得到 `ready | wake` 两条事件（叫醒了，再没有下文）。
#   症状长得像"产品叫醒了不识别"，其实是**道具比产品旧**。
#   → 产品那个数一改，这里**必须一起改**（另两个地方也是：`asr_stream.py` 的
#     `whisper_silence_s`、`loop.py` 的 `FOLLOW_S`）。10.5 = 10 s + 一点余量。
FAKE_WAV = ROOT / "_scratch" / "_fake_mic_loopback.wav"
PAD_S = 10.5
SPEECH_S = 3.7               # 只用来打一行人看的字（样本本身多长）


def build_fake_mic() -> None:
    """拼出假麦克风的循环体：原样本（22050 Hz / 16 bit / 单声道）+ N 秒数字静音。

    ⚠️ 采样率照抄源文件、**不重采样**：`--use-file-for-fake-audio-capture` 交上来的
       是设备流，浏览器自己会重采样到页面的 16000（第一次跑就是 22050 直接喂的，
       唤醒是通的）。这里换算是多余动作，还会把"唤醒是不是靠重采样才成的"搅进来。
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

# 见 A 段：数"页面碰过麦克风没有"。装在最前面，所以从文档第一个字节起就有效。
# ⚠️ 计数写在 `window.__micCalls` 上，**不写 localStorage** —— 这一条要的是
# "这一次加载里发生过什么"，跨页面累计会把上一页的算进来。
COUNT_MIC = """
(function () {
  window.__micCalls = 0;
  var md = navigator.mediaDevices;
  if (!md) return;
  var orig = md.getUserMedia && md.getUserMedia.bind(md);
  if (!orig) return;
  md.getUserMedia = function () {
    window.__micCalls += 1;
    return orig.apply(null, arguments);
  };
})();
"""


class WakeSession(Session):
    """带假麦克风的会话：`--use-file-for-fake-audio-capture` 让浏览器把那个 wav
    当成麦克风输入（会循环放），于是"对着笔记本说你好小瑞"这件事在 headless 里
    有了一个可复现的替身。"""
    EXTRA_FLAGS = [
        "--use-fake-device-for-media-stream",
        "--use-fake-ui-for-media-stream",
        "--use-file-for-fake-audio-capture=" + str(FAKE_WAV),
    ]
    PRELOAD = [COUNT_MIC]


# ★ 把服务端发来的每一条语音事件记下来。
#
# ⚠️ 为什么非要有它：第一版**服务端全绿、页面全哑** —— 服务端确实叫醒了、也识别了，
#    可这一页压根没把 `{"type":"voice"}` 转给 `XQ.wake.onMsg`（`XQ.connect` 的
#    catch-all 是要页面自己接的）。没有这条记录，能看到的只有"状态还是 listening"，
#    而那句话同时符合三件完全不同的事：没叫醒 / 叫醒了但没显示 / 显示了但没画出来。
#    有了它，一眼就能分开。
#
# ⚠️ 必须**在页面脚本跑完之后**装（`XQ` 那时候才存在），而且要**包着原函数**调用
#    （`orig(d)`）—— 只记录不转发的话，这一装就把页面自己的反应关掉了，
#    等于自己把被测的东西拆了。
HOOK_EVS = """
(function () {
  window.__evs = [];
  if (!window.XQ || !XQ.wake) return 'no XQ.wake';
  var orig = XQ.wake.onMsg.bind(XQ.wake);
  XQ.wake.onMsg = function (d) {
    window.__evs.push((d.ev || '?') + (d.text ? ':' + d.text : (d.why ? ':' + d.why : '')));
    return orig(d);
  };
  return 'ok';
})()
"""

# ⚠️ 已知且**接受**的警告，和 `_check_pages.py` 里那两条 404 同一个性质
#    （见 KNOWN_PROBE_404）：
#    `ScriptProcessorNode` 被标了 deprecated，官方建议换 `AudioWorkletNode`。
#    这一条是**明知故犯**，理由不是"懒得改"：AudioWorklet 要单独一个模块文件、
#    要异步 `addModule`、失败时还得留一条回退路，而它换来的东西在这件事上没有用
#    —— 我们要的是"每 100 ms 拿一片 16 k 单声道"，ScriptProcessor 在目标浏览器
#    （Edge/Chrome，都是 Chromium）上一直能用，延迟和抖动也扛得住。
#    真要换，得**同时**换掉 `XQ.asr` 那条路，并且先在目标机器上量过再说。
KNOWN_WARNINGS = ("ScriptProcessorNode is deprecated",)


async def snap(S):
    """把页面上这一格的状态一次读齐（一条 CDP 调用，省得来回跑）。"""
    return await S.js("""JSON.stringify({
      state: XQ.wake.state, why: XQ.wake.why,
      frames: XQ.wake.frames, sent: XQ.wake.sent, lost: XQ.wake.lost,
      partial: XQ.wake.partial, reply: XQ.wake.reply,
      heard: XQ.wake.lastHeard, busy: XQ.wake.busy,
      host: (document.getElementById('wakeHost') || {}).textContent || '',
      detail: (document.getElementById('wakeDetail') || {}).textContent || '',
      kws: (XQ.wake.engine || {}).kws || '', asr: (XQ.wake.engine || {}).asr || '',
      model: (XQ.wake.engine || {}).kws_model || '',
      bubbles: Array.prototype.map.call(
        document.querySelectorAll('#bubbles .b'),
        function (b) { return b.querySelector('u').textContent + ':' +
                              b.querySelector('p').textContent; }),
      evs: (window.__evs || []).slice(-12),
      micCalls: window.__micCalls,
      sr: XQ.wake._ctx ? XQ.wake._ctx.sampleRate : null,
      tracks: XQ.wake._stream
        ? XQ.wake._stream.getTracks().map(function (t) { return t.readyState; }) : [],
      pressed: (document.getElementById('wake') || {}).getAttribute
        ? document.getElementById('wake').getAttribute('aria-pressed') : null
    })""")


async def main():
    worst = 0
    build_fake_mic()
    print("假麦克风的循环体：%s（%.1f s 说话 + %.1f s 静音，一轮 %.1f s）"
          % (FAKE_WAV.name, SPEECH_S, PAD_S, SPEECH_S + PAD_S))
    async with WakeSession(9412) as S:
        # ---------------------------------------------------------- A 自己开麦
        print("\n=== A 打开页面**自己就开麦**（2026-09-25 晚用户把规矩翻过来了） ===")
        print("      用户原话：「能不能不需要我按就可以说你好小瑞 然后唤醒了」")
        await S.goto("/detail.html", wait=1.0)
        print("      装事件记录器：%s" % await S.js(HOOK_EVS))
        # ⚠️ 等它自己起：`autostart()` 挂在 `hello` 里，而 hello 要等 WS 连上。
        #    写死 2.5 s 去读是**赌**，起麦慢一点就变成"看着像没上线"（假红）。
        for _ in range(12):
            await asyncio.sleep(1.0)
            s = await snap(S)
            if s["state"] in ("listening", "error"):
                break
        worst += ck("XQ.wake 在页面上", s["state"] is not None, "state=%r" % s["state"])
        # ★★ 「不用点就起来了」——`state` 还是 'off' 就说明 `onHello` 里的
        #    `autostart()` 没跑（或它自己退回来了），也就是**功能没上线**。
        worst += ck("★ 不点任何一下，它自己在听", s["state"] == "listening",
                    "state=%r why=%r" % (s["state"], s["why"]))
        # ★★ 而且**只许开一次**。自动开麦 + 按钮各开一次 = 两路抢同一个麦克风，
        #    症状是音频片成对地冒、服务端序号跳 —— 静默的坏。
        worst += ck("★ getUserMedia **只调了一次**（自动开与按钮没有重复开）",
                    s["micCalls"] == 1, "调了 %s 次" % s["micCalls"])
        worst += ck("AudioContext 的采样率是 16000", s["sr"] == 16000, "sr=%s" % s["sr"])
        # ⚠️ 这里只断言"管道通了"（≥1 片），**不断言片数**：上面那个等它起来的循环
        #    一看到 'listening' 就跳出来了，所以这一刻离麦打开只有零点几秒
        #    （实测 7 片）。原来这里写的是 `>= 10`（= 1 秒音频），那是个**假的**判据
        #    —— 量到的是"我读得多快"，不是"音频在不在流"。真正的"一直在走"交给
        #    下面 B 段：拿 A 的读数当基线，断言两秒里又涨了多少。
        worst += ck("音频管道通了（已经在往服务端送片）", (s["sent"] or 0) >= 1,
                    "%s 片 / %s s" % (s["sent"], round((s["sent"] or 0) / 10.0, 1)))
        worst += ck("状态行说的是实话", "在听" in s["host"], s["host"])
        worst += ck("按钮这时候是「停」", s["pressed"] == "true", "aria-pressed=%s" % s["pressed"])
        worst += ck("hello 里报了唤醒模型", bool(s["model"]), s["model"])
        worst += ck("hello 里报了识别那条路", bool(s["asr"] or s["detail"]),
                    (s["asr"] or s["detail"])[:60])
        worst += ck("那一格的两行字都在（状态 + 引擎）", "在听" in s["host"]
                    and bool(s["detail"]), "detail=%r" % s["detail"][:70])

        # ---------------------------------------------------------- B 一直在走
        print("\n=== B 两秒后：还在听，而且音频片**还在涨**（拿 A 的读数当基线） ===")
        sent_a = s["sent"] or 0
        await asyncio.sleep(2.0)
        s = await snap(S)
        # 100 ms 一片 → 两秒该有 20 片。留到 15 是给调度抖动留余量，
        # 但**不能不留**：留成"比基线大就行"的话，一条卡住的流（一秒冒一片）
        # 也能绿 —— 那正是"看着在听、其实没声"那种坏。
        worst += ck("★ 还在 listening 且这两秒里又涨了 ≥15 片",
                    s["state"] == "listening"
                    and (s["sent"] or 0) - sent_a >= 15,
                    "state=%r  sent %s → %s" % (s["state"], sent_a, s["sent"]))

        # ---------------------------------------------------------- C 真的被叫醒
        print("\n=== C 说「你好，小瑞，我有点困」（假麦克风放的就是这句） ===")
        # 假麦克风是**循环**放的：给它两轮的时间（一轮 = 说话 + 10.5 s 静音 ≈ 14.2 s，
        # 断句要等静音满 10 s，再加上转文字；第一轮没叫醒就等第二轮）。
        #
        # ⚠️ "听到话"和"答了话"是**两个时刻**，必须分开等：转文字是秒级，问模型
        #    （一次 DeepSeek 往返）又几秒。第一版是"快照里有 heard 或 reply 就停下
        #    来判"，于是在 `heard` 刚到、答复还在路上的那一瞬间就断言了 `reply`，
        #    把两个都对的实现判成红的 —— 又是"看起来像产品坏了、其实是判据坏了"。
        heard_snap = None
        for i in range(20):                       # 最多等 40 s
            await asyncio.sleep(2.0)
            s = await snap(S)
            if s["heard"]:
                heard_snap = s
                break
        print("      服务端发来的语音事件：%s" % " | ".join(s["evs"]))
        if heard_snap is None:
            worst += ck("叫醒了 / 听到了", False,
                        "等了 40 s；页面状态 %r，服务端发来过 %d 条语音事件（%s）"
                        % (s["state"], len(s["evs"]), " | ".join(s["evs"]) or "一条都没有"))
        else:
            print("      状态行：%s" % heard_snap["host"])
            print("      第二行：%s" % heard_snap["detail"])
            worst += ck("真的听到了话", True, "听到：%r" % heard_snap["heard"])
            worst += ck("没丢片", (heard_snap["lost"] or 0) == 0,
                        "lost=%s" % heard_snap["lost"])
            # 再等答复：它要等一次 DeepSeek 往返（秒级）。
            rep = heard_snap
            for i in range(20):                   # 再等 40 s
                if rep["reply"]:
                    break
                await asyncio.sleep(2.0)
                rep = await snap(S)
            worst += ck("小瑞答了话", bool(rep["reply"]), "%r" % (rep["reply"] or "")[:70])
            # ⚠️ "答复到了页面"和"答复画在了气泡里"也是两件事（第 4 条纪律：
            #    只出声、不画字的版本在演示现场等于坏了）。所以不光数气泡个数，
            #    还要**在这一轮里**认出来：小瑞那条气泡得就是刚到的这句答复。
            print("      气泡（最后两条）：")
            for b in rep["bubbles"][-2:]:
                print("        %s" % b[:90])
            worst += ck("答复真的画进了气泡", bool(rep["reply"]) and
                        any(rep["reply"][:8] in b for b in rep["bubbles"]),
                        "reply=%r 共 %d 个气泡" % ((rep["reply"] or "")[:24],
                                                  len(rep["bubbles"])))

        # ---------------------------------------------------------- D 收干净
        print("\n=== D 再点一下停：状态回 off、音轨真的 stop ===")
        await S.js("document.getElementById('wake').click()")
        await asyncio.sleep(1.5)
        s = await snap(S)
        worst += ck("状态回 off", s["state"] == "off", "state=%r" % s["state"])
        worst += ck("音轨都停了（不然麦克风指示灯还亮着）",
                    all(t == "ended" for t in s["tracks"]), "tracks=%s" % s["tracks"])
        worst += ck("停之后没再开麦（同一次加载内）", s["micCalls"] == 1,
                    "调了 %s 次" % s["micCalls"])

        # ---------------------------------------------------------- E 关了不许又开
        # ★★ 「我明明关了它又自己开了」**唯一**的成因就在这里：座舱是**整页导航**
        #    （不是 SPA），每翻一页 `onHello` 就再跑一次，`autostart()` 跟着再跑。
        #    所以「停」必须在这一次会话内黏住（`sessionStorage`，见 wake.js 第 1 条）。
        #    ⚠️ 计数器是**每份文档归零**的（`COUNT_MIC` 里那句注释写了为什么），
        #    所以这里该读到的是 **0** —— "这一页加载起来之后一次都没碰麦克风"，
        #    比"和上一页加起来还是 1"更直接。
        print("\n=== E 翻一页回来，不许又自己开起来 ===")
        await S.goto("/index.html", wait=1.5)
        await S.goto("/detail.html", wait=2.0)
        await asyncio.sleep(3.0)
        s = await snap(S)
        print("      翻回来：state=%r 状态行=%r 这一页碰了几次麦=%s"
              % (s["state"], s["host"], s["micCalls"]))
        worst += ck("★★ 翻页回来**没有**又自己开起来", s["state"] == "off",
                    "state=%r（'listening' = 关了又被打开，演示现场会看到）"
                    % s["state"])
        worst += ck("★ 翻页回来状态行也如实说「没在听」", "没在听" in s["host"],
                    s["host"])
        worst += ck("★ 这一页加载起来之后没碰过麦克风", s["micCalls"] == 0,
                    "调了 %s 次" % s["micCalls"])

        # ---------------------------------------------------------- E 控制台
        print("\n=== F 控制台零报错 ===")
        errs = [e for e in S.errs
                if not any(k in e[1] for k in KNOWN_WARNINGS)]
        skipped = len(S.errs) - len(errs)
        worst += ck("没有报错/警告", not errs, "；".join("%s %s" % e for e in errs[:5]))
        if skipped:
            print("      （放过 %d 条已知且接受的警告：%s —— 理由见本文件 KNOWN_WARNINGS）"
                  % (skipped, "、".join(KNOWN_WARNINGS)))

    print("\n" + "=" * 74)
    if worst:
        print("❌ %d 条不对" % worst)
        return 1
    print("✅ 全对 —— 自己开麦（且只开一次）、叫得醒、停得干净、关了不会再开。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
