# -*- coding: utf-8 -*-
"""常听唤醒 · **服务端侧**验收（一条真的 WebSocket + 真的音频，但没有浏览器）。

    python _scratch/_check_voice_ws.py 8790

`_check_wake_browser.py` 验的是浏览器那一半（采麦、编码、画字、发音轨），
这一份验的是**它对面那一半**：`{"type":"pcm"}` 进来之后，服务端有没有
按顺序把 `ready / wake / partial / heard / reply` 发出去，以及
`voice_spoken` 回来之后**能不能再叫醒一次**（这一条最容易坏 —— 状态机卡在
SPEAK 的话，表现是"叫醒一次就哑了"）。

⚠️ 音频按 **100 ms 一片、按真实时间节拍**喂（`await asyncio.sleep(0.1)`）。
   不是为了好看：服务端有几处机制是**按挂钟**算的（`debounce_s`、`GUARD_S`），
   一次性灌进去的话它们全都还没过期，第一片之后的音频会被整片吞掉 ——
   离线回放踩过这个坑两次，见 `ui/voice/kws.py` 第 2 条纪律。

⚠️ 这个脚本**证明不了**识别准不准（样本是合成的），也**证明不了**浏览器那边
   任何事。它只证明"这条协议是通的、顺序是对的"。
"""

import asyncio
import base64
import json
import sys
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent / "ui"))
sys.path.insert(0, str(Path(__file__).parent.parent / "ui" / "voice"))

import asr                                              # noqa: E402
from kws import SR                                      # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8790"
URL = "ws://127.0.0.1:%s/ws" % PORT
ROOT = Path(__file__).resolve().parents[1]
ONE_SHOT = ROOT / "runs" / "wake_samples" / "pos_hello_xiaorui_slow.wav"
WAKE_ONLY = ROOT / "runs" / "wake_samples" / "pos_hello_xiaorui.wav"
CHUNK = 1600                                             # 100 ms
FAILS = []


def ck(name, ok, note=""):
    print("  %s %-34s %s" % ("OK  " if ok else "!!  ", name, note))
    if not ok:
        FAILS.append(name)
    return 0 if ok else 1


def pcm(path) -> np.ndarray:
    return asr.wav_bytes_to_float32(path.read_bytes(), want_sr=SR)


def frames(x):
    for i in range(0, len(x), CHUNK):
        yield x[i:i + CHUNK]


async def send_audio(ws, x, silence_s=10.5):
    """按真实节拍喂一段音频，末尾补静音 —— 收口**只**靠静音判。

    ⚠️ 默认 10.5 s 是按生产值来的（2026-09-26 用户拍板：「语音结束的标志是我中途
       10s 没有发出声音」，见 `ui/voice/asr_stream.py`）。别为了跑得快改小：
       改小了就是「用测试的阈值迁就代码」，谁把 10 调回去这份脚本也照样全绿。
       这一段是**真按 0.1 s 一片实时喂**的，所以补多少静音就真的多花多少挂钟时间。
    """
    for ch in frames(np.concatenate([x, np.zeros(int(silence_s * SR), np.float32)])):
        pcm16 = (np.clip(ch, -1, 1) * 32767).astype("<i2").tobytes()
        await ws.send_json({"type": "pcm", "seq": 1,
                            "b64": base64.b64encode(pcm16).decode("ascii")})
        await asyncio.sleep(0.1)


async def main():
    import aiohttp
    worst = 0
    evs = []                                              # 收到的 voice 事件（按顺序）
    says = []
    # ⚠️ hello 装在**字典**里，不能用 `hello = None` 那种写法：下面 `pump()` 里
    #    一赋值，Python 就把它当成 pump 的局部变量，外面读到的永远是 None。
    box = {}

    async with aiohttp.ClientSession() as sess:
        async with sess.ws_connect(URL, max_msg_size=0) as ws:
            async def pump():
                # ⚠️ 这个任务挂了**没有任何提示**：后面的判据会一条接一条地失败，
                #    而原因（pump 死了、不是服务端坏了）一个字都看不到。
                #    上一版就是这样误报的，所以异常必须打出来。
                try:
                    async for m in ws:
                        if m.type != aiohttp.WSMsgType.TEXT:
                            continue
                        d = json.loads(m.data)
                        if d.get("type") == "voice":
                            evs.append(d["data"])
                            print("      ← %s" % json.dumps(
                                {k: v for k, v in d["data"].items()
                                 if k in ("ev", "word", "text", "why", "emotion")},
                                ensure_ascii=False)[:150])
                        elif d.get("type") == "say":
                            says.append(d["data"])
                        elif d.get("type") == "hello":
                            box["hello"] = d["data"]
                except Exception as e:
                    print("      !! 收消息的任务挂了：%s: %s（后面的判据都不可信了）"
                          % (type(e).__name__, e))

            async def ear_state(timeout=3.0):
                """问服务端"状态机现在在哪一档"。

                ⚠️ **必须问，不能等 sleep 猜。** 上一版就是靠猜：`voice_spoken`
                   发出去之后固定睡 0.8 s 再喂下一轮，而"答复"那一下要等一次
                   DeepSeek 往返（几秒）—— 于是出现了一轮还没收干净、下一轮
                   就开说的时序，把两个本来都对的实现判成了红的。
                """
                n = len(evs)
                await ws.send_json({"type": "voice_status"})
                t0 = asyncio.get_event_loop().time()
                while asyncio.get_event_loop().time() - t0 < timeout:
                    for e in reversed(evs[n:]):
                        if e.get("ev") == "status":
                            return e
                    await asyncio.sleep(0.05)
                return None

            async def wait_state(want, timeout=40.0, what=""):
                """等状态机落到 `want`（或它已经不在那一档了）。"""
                t0 = asyncio.get_event_loop().time()
                last = None
                while asyncio.get_event_loop().time() - t0 < timeout:
                    st = await ear_state()
                    if st is None:
                        return last
                    last = st
                    if (st.get("ear") or {}).get("state") == want:
                        return st
                    await asyncio.sleep(0.3)
                print("      （等 %s 超时，最后是 %r）"
                      % (what or want, (last or {}).get("ear", {}).get("state")))
                return last

            async def wait_idle_feeding(seconds=16.0, what=""):
                """**边喂静音边等**状态机回 IDLE —— 真页面的麦克风是一直开着的。

                🔴 为什么必须喂：追问窗口的超时判据长在 `VoiceLoop.feed()` 里
                   （`loop.py` 的 FOLLOW 那一支：`not self._heard() and
                   now - self._t_follow > self.follow_s`）—— **没有音频进来，
                   这个判据就不会被算**。原来这里干等 16 s，于是窗口永远不关，
                   报出来是三条 `!!`（"等 idle 超时，最后是 'follow'"），看着像
                   状态机不会收尾，其实是**脚本**没扮演好：真页面的 mic 一直在推
                   PCM，服务端每 100 ms 就会算一次这个判据。
                   （同一个毛病的另外几处：`--use-file-for-fake-audio-capture` 循环
                    播放、`_check_barge_in.py` 里补喂那一片 —— 都是"输入没送到"。）
                """
                t0 = asyncio.get_event_loop().time()
                last = None
                while asyncio.get_event_loop().time() - t0 < seconds:
                    for ch in frames(np.zeros(int(0.5 * SR), np.float32)):
                        pcm16 = (np.clip(ch, -1, 1) * 32767).astype("<i2").tobytes()
                        await ws.send_json({"type": "pcm", "seq": 1,
                                            "b64": base64.b64encode(pcm16)
                                            .decode("ascii")})
                        await asyncio.sleep(0.1)
                    st = await ear_state()
                    if st is None:
                        return last
                    last = st
                    if (st.get("ear") or {}).get("state") == "idle":
                        return st
                print("      （边喂静音边等 %s 超时，最后是 %r）"
                      % (what, (last or {}).get("ear", {}).get("state")))
                return last

            async def wait_ev(kind, timeout=40.0):
                """等某一个事件出现（转文字、答复都要等真算完，不能定时长）。"""
                t0 = asyncio.get_event_loop().time()
                while asyncio.get_event_loop().time() - t0 < timeout:
                    hit = next((e for e in evs if e.get("ev") == kind), None)
                    if hit is not None:
                        return hit
                    await asyncio.sleep(0.2)
                return None

            t = asyncio.create_task(pump())
            await asyncio.sleep(0.6)

            # ------------------------------------------------------ A hello
            print("\n=== A hello 里报了耳朵的状态 ===")
            v = (box.get("hello") or {}).get("voice") or {}
            worst += ck("hello.voice 在", bool(v), json.dumps(v, ensure_ascii=False)[:110])
            worst += ck("唤醒模型在", bool(v.get("kws_model")), str(v.get("kws_model")))
            # ⚠️ 「hello **不预载**耳朵」这一条**只在刚起的服务上验得到**：耳朵是
            #    懒创建的（`Hub.ear_start`），这份服务上一旦有人点过「听」，
            #    之后所有连接的 `built` 都是 True —— 那是**对的**，不是坏的。
            #    所以这里不把"第二次跑"判成红（那正是"判据坏了"冒充"产品坏了"），
            #    而是如实说明；判据本身换成"报的和实际一致"。
            st0 = await ear_state()
            worst += ck("built 和服务端实际一致（不撒谎）",
                        v.get("built") == (st0 or {}).get("voice", {}).get("built"),
                        "hello=%s status=%s" % (v.get("built"),
                                                (st0 or {}).get("voice", {}).get("built")))
            if v.get("built") is False:
                worst += ck("新服务上不预载耳朵（built=False）", True, "第一次跑，符合预期")
            else:
                print("  --   built=True：这份服务上已经有人点过「听」了"
                      "（同一份服务上跑第二遍的正常现象）。\n"
                      "      「不预载」那条只在**刚起的服务**上才验得到 —— 要验它，重启服务再跑。")

            # ------------------------------------------------------ B 开始听
            print("\n=== B voice_start → ready ===")
            await ws.send_json({"type": "voice_start"})
            for _ in range(60):                           # 建耳朵要加载模型，给它 30 s
                await asyncio.sleep(0.5)
                if any(e.get("ev") == "ready" for e in evs):
                    break
            rdy = [e for e in evs if e.get("ev") == "ready"]
            worst += ck("回了 ready", bool(rdy),
                        json.dumps(rdy[-1].get("voice", {}) if rdy else {},
                                   ensure_ascii=False)[:130] if rdy else "没等到")
            if rdy:
                vv = rdy[-1].get("voice") or {}
                worst += ck("ready 里带了引擎自报", bool(vv.get("kws") and vv.get("asr")),
                            "kws=%r asr=%r" % (vv.get("kws", "")[:34], vv.get("asr", "")[:34]))

            # ------------------------------------------------------ C 一口气说
            print("\n=== C 说「你好，小瑞，我有点困」（唤醒词和内容一口气） ===")
            evs.clear()
            says.clear()
            await send_audio(ws, pcm(ONE_SHOT))
            # ⚠️ 转文字（whisper）和问模型（一次 DeepSeek 往返）都是**秒级**的，
            #    所以这里等事件、不定时长 —— 上一版固定睡 0.8 s，把两个都对的实现
            #    判成了红的，正是那种"看起来像产品坏了、其实是判据坏了"的误报。
            await wait_ev("heard", timeout=60)
            order = [e.get("ev") for e in evs]
            print("      事件顺序：%s" % " → ".join(order))
            worst += ck("有 wake", "wake" in order, "word=%r"
                        % next((e.get("word") for e in evs if e.get("ev") == "wake"), None))
            heard = next((e.get("text") or "" for e in evs if e.get("ev") == "heard"), "")
            worst += ck("有 heard", "heard" in order, "听到：%r" % heard)
            worst += ck("wake 在 heard 前面",
                        "wake" in order and "heard" in order
                        and order.index("wake") < order.index("heard"))
            worst += ck("整句接上了（含「困」）", "困" in heard, "heard=%r" % heard)
            # 说了话之后**不该**已经回 idle：它在等"念完了"
            st0 = [e.get("ev") for e in evs if e.get("ev") == "idle"]
            worst += ck("听到话之后没提前回 idle", not st0, "idle=%r" % (st0[:1],))
            rep = await wait_ev("reply", timeout=60)
            worst += ck("有 reply", rep is not None, "%r" % ((rep or {}).get("text") or "")[:70])
            vs = [s for s in says if s.get("voice") is True]
            worst += ck("答复也广播成 say 了（气泡要画）", bool(vs),
                        "%d 条 / 共 %d 条 say" % (len(vs), len(says)))
            if vs:
                worst += ck("say 上带**语音来的**标记（页面靠它不重复念）",
                            vs[-1].get("silent") is True and bool(vs[-1].get("user")),
                            "silent=%s user=%r" % (vs[-1].get("silent"), vs[-1].get("user")))
            sp = await ear_state()
            worst += ck("答复之后进了 SPEAK（念的期间不听自己）",
                        (sp or {}).get("ear", {}).get("state") == "speak",
                        "state=%r" % (sp or {}).get("ear", {}).get("state"))

            # ------------------------------------------------------ D 追问窗口
            # ★ 2026-09-26：这一段原来叫「念完能再叫」，判据是"voice_spoken 之后
            #   状态回 idle、再喊一次唤醒词还能叫醒"。**那个判据现在是错的** ——
            #   念完之后进的是**追问窗口**（`follow`），不是 idle，而且窗口里
            #   **不用唤醒词**。判据照旧的话，喂进去的「你好，小瑞」既不唤醒
            #   （窗口里不喂 KWS）、又会被识别器当成一句话接住 —— 两条都判成红，
            #   而两条都是对的（正是"判据坏了冒充产品坏了"）。
            print("\n=== D 念完 → 进追问窗口：接着说就接着答（不用再喊唤醒词） ===")
            await ws.send_json({"type": "voice_spoken"})
            await wait_state("follow", timeout=10, what="follow（追问窗口）")
            fl = next((e for e in evs if e.get("ev") == "follow"), None)
            worst += ck("回了 follow（页面据此改状态行）", fl is not None,
                        "sec=%r" % ((fl or {}).get("sec"),))
            sp = await ear_state()
            worst += ck("服务端的状态机在 follow（不是 idle）",
                        (sp or {}).get("ear", {}).get("state") == "follow",
                        "state=%r" % (sp or {}).get("ear", {}).get("state"))
            evs.clear()
            # ⚠️ 用的样本是「你好，今天天气怎么样」—— **里面没有"小瑞"两个字**，
            #    所以它只可能在追问窗口里被接住。窗口没开的旧版本这里一条事件都没有。
            await send_audio(ws, pcm(ROOT / "runs" / "wake_samples" / "neg_weather.wav"))
            await wait_ev("heard", timeout=60)
            order2 = [e.get("ev") for e in evs]
            print("      事件顺序：%s" % " → ".join(order2))
            worst += ck("追问窗口里**没有** wake（不用唤醒词了）", "wake" not in order2,
                        "；".join(order2))
            heard2 = next((e.get("text") or "" for e in evs if e.get("ev") == "heard"), "")
            worst += ck("接着说的一句被接住了（含「天气」）", "天气" in heard2,
                        "heard=%r" % heard2)
            rep2 = await wait_ev("reply", timeout=60)
            worst += ck("这一句也答了", rep2 is not None, "%r" % ((rep2 or {}).get("text") or "")[:70])

            # ------------------------------------------------------ D2 窗口会自己关
            print("\n=== D2 窗口到点没人说话 → 自己关掉，之后还能再喊唤醒词 ===")
            # ⚠️ **必须真的等**，而且是**挂钟**：窗口长度 `follow_s`（8 s）是
            #    按挂钟算的，压缩回放里推不动它（离线那份踩过两次，见 ui/voice/kws.py
            #    第 2 条纪律）。念完之后还有 `GUARD_S`（0.4 s）的余音保护，也是挂钟。
            await ws.send_json({"type": "voice_spoken"})           # 收这一轮
            await wait_state("follow", timeout=10, what="follow（又开了一个窗口）")
            print("      边喂静音边等窗口自己关（最多 %.0f s）…"
                  % (float((fl or {}).get("sec") or 10) + 3))
            sp = await wait_idle_feeding(float((fl or {}).get("sec") or 10) + 3,
                                         what="idle（窗口超时收的）")
            worst += ck("窗口到点自己关了（回到 idle）",
                        (sp or {}).get("ear", {}).get("state") == "idle",
                        "state=%r" % (sp or {}).get("ear", {}).get("state"))
            closed = [e.get("ev") for e in evs if e.get("ev") in ("idle", "follow")]
            worst += ck("关窗时给页面发了 idle（状态行要改回去）", "idle" in closed,
                        "；".join(closed))
            # 收尾：把这一轮放回 IDLE，免得影响 E 段
            await ws.send_json({"type": "voice_spoken"})
            # ⚠️ **必须真的等**这一段：念完之后有 `GUARD_S`（0.4 s）的余音保护，
            #    它是**按挂钟**算的。这一版第一遍就是在这儿判红的 —— 状态一到
            #    idle 就立刻喂音频，前 0.4 s 全被保护窗口吃掉，唤醒词正好在那一段里，
            #    于是"第二次叫不醒"。这和 `debounce_s` 是同一类坑，离线回放踩过两次：
            #    **凡是按挂钟计时的机制，压缩时间里的回放都不成立。**
            await asyncio.sleep(0.6)
            evs.clear()
            # 这一条只验「还能不能再叫醒」，不等收口 —— 所以静音给 1.0 s 就够，
            # 不必是 10.5 s（唤醒由 KWS 直接触发，跟断句线无关）。
            await send_audio(ws, pcm(WAKE_ONLY), silence_s=1.0)
            order3 = [e.get("ev") for e in evs]
            print("      事件顺序：%s" % " → ".join(order3))
            worst += ck("窗口关掉之后，喊唤醒词还能再叫醒", "wake" in order3, "；".join(order3))
            # 收尾：把这一轮也放回 IDLE，免得影响 E 段
            await ws.send_json({"type": "voice_spoken"})

            # ------------------------------------------------------ E 停
            print("\n=== E voice_stop ===")
            evs.clear()
            await ws.send_json({"type": "voice_stop"})
            # ⚠️ 又一处"**别睡固定时长**"：上一轮那句答复可能还在路上（一次
            #    DeepSeek 往返，实测几秒），服务端要等它回来才轮到处理 stop。
            #    照旧等事件 —— 这一版第一遍就是睡 0.6 s 之后立刻断言，于是
            #    `reply` 和 `idle` 都在断言**之后**才到，判成红的。
            #    （答复先到、idle 后到是正常的：先到说明那一轮抢在 stop 前面收了尾，
            #      两条顺序最后都落在 idle，都是对的。）
            got_idle = False
            t0 = asyncio.get_event_loop().time()
            while asyncio.get_event_loop().time() - t0 < 30:
                if any(e.get("ev") == "idle" for e in evs):
                    got_idle = True
                    break
                await asyncio.sleep(0.2)
            worst += ck("停之后回了 idle", got_idle,
                        "；".join(e.get("ev", "") for e in evs))
            sp = await ear_state()
            worst += ck("服务端的状态机也回到 idle",
                        (sp or {}).get("ear", {}).get("state") == "idle",
                        "state=%r owner=%s" % ((sp or {}).get("ear", {}).get("state"),
                                               (sp or {}).get("owner")))
            await ws.send_json({"type": "pcm", "seq": 1, "b64": ""})   # 空片：不该炸
            await asyncio.sleep(0.3)
            worst += ck("停了之后送音频不再有事件",
                        not [e for e in evs if e.get("ev") == "wake"])

            t.cancel()

    print("\n" + "=" * 74)
    if worst:
        print("❌ %d 条不对" % worst)
        return 1
    print("✅ 全对 —— voice_start/ready → 唤醒 → 转文字 → 答复 → 念完再来一轮，协议是通的。")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
