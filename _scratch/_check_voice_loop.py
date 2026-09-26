# -*- coding: utf-8 -*-
"""整条语音链路的自测：喂音频进去 → 唤醒 → 断句 → 出文字。**全离线，不用浏览器。**

    python _scratch/_check_voice_loop.py            # 全跑
    python _scratch/_check_voice_loop.py --levels   # 只打样本电平（用来定断句阈值）

这里测的是**链路**（状态机 + 唤醒 + 识别怎么咬合），不是识别准不准 ——
准不准只有真人对着麦克风说才算数，而且那属于模型的账。

最要紧的一条是「一口气说」：`pos_hello_xiaorui_slow` 是
**「你好，小瑞，我有点困」** —— 唤醒词和要说的内容在同一句里。真实的用法就是这样，
没有人在唤醒词后面停一下。它能不能整句接上，靠的是唤醒瞬间把**环形缓冲**里
那一两秒补喂给识别（见 ui/voice/loop.py 第 2 条）。这一条要是不灵，
用户就得"先说唤醒词、停一下、再说内容"，那种交互在车上很别扭。

还有一条 2026-09-26 补上的：**追问窗口到点时主人正在说话，窗口不许关**（D1b 段）。
    `follow_s` 和"说完了"那条判据是同一个数（10 s），所以照挂钟关窗口必然在主人
    说话的中途关掉、整句被扔。⚠️ 这条**只有按真挂钟喂才量得出来** —— 这一份脚本
    是压缩回放（一口气喂完，挂钟不走），所以是 `_check_voice_do.py`（按 100 ms
    真实节拍喂）逮到的。D1b 因此特意**真的 sleep** 过那个窗口。

⚠️ 关于"这几条判据有多可信"，先看清楚：
  · 唤醒/状态机的流转 —— 真值来自事件的**顺序和次数**，跑一遍就知道对错。
  · 识别出的文字 —— 是 whisper 在这个样本上给的，**样本是合成的**，所以它只证明
    "链路通了"，不证明"在车里也这么准"。
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "ui" / "voice"))

import asr                                    # noqa: E402  借 wav 解析 + 电平
import loop as loop_mod                       # noqa: E402
from kws import SR                            # noqa: E402
from loop import VoiceLoop                    # noqa: E402

CHUNK = 1600                                  # 100 ms
# 每个样本后面补的静音（秒）—— **按生产值来，不许为了跑得快改小**。
# 2026-09-26 用户拍板：「语音结束的标志是我中途 10s 没有发出声音」。所以这里补
# 10.5 s（判据 10 s + 一片余量）。这份脚本是**回放**，补静音不花挂钟时间，
# 代价只是 whisper 要多转 10 s 的静音（一两秒）。
# ⚠️ 别把它改回 1.5 s：那等于"用测试的阈值去迁就代码"，判据一旦被改坏
#    （比如谁又把 10 调回 0.9）这份脚本会照样全绿。
TAIL = 10.5
FAILS = []
ONE_SHOT = "pos_hello_xiaorui_slow"           # 你好，小瑞，我有点困
WAKE_ONLY = "pos_hello_xiaorui"               # 你好，小瑞


def check(ok, msg):
    print("  %s %s" % ("✅" if ok else "❌", msg))
    if not ok:
        FAILS.append(msg)
    return ok


def pcm(stem: str) -> np.ndarray:
    p = ROOT / "runs" / "wake_samples" / (stem + ".wav")
    return asr.wav_bytes_to_float32(p.read_bytes(), want_sr=SR)


def feed(v: VoiceLoop, x: np.ndarray, tag: str = ""):
    """按 100 ms 喂，收集所有事件（带上发生在第几毫秒）。

    ⚠️ 收到 `need_text` 就地调 `finalize_text()` —— 这里**同步**调是可以的（这个
    测试没有事件循环，慢一点只是脚本多花一秒）；在服务端**必须放到线程里**，
    理由见 `ui/voice/loop.py` 的 `_finish`。
    """
    evs = []
    for i in range(0, len(x), CHUNK):
        got = list(v.feed(x[i:i + CHUNK]))
        for e in got:
            evs.append(dict(e, _ms=int((i + CHUNK) / SR * 1000)))
        if any(e["type"] == "need_text" for e in got):
            for e in v.finalize_text():
                evs.append(dict(e, _ms=int((i + CHUNK) / SR * 1000)))
    if evs:
        print("    %s事件：%s" % (tag, "、".join(
            "%s%s" % (e["type"], "@%dms" % e["_ms"]) for e in evs)))
    return evs


def wait_asr(v: VoiceLoop, timeout: float = 90.0) -> bool:
    """等识别模型就绪（whisper 是后台线程加载的，要几秒到几十秒）。"""
    t0 = time.time()
    while time.time() - t0 < timeout:
        if v.asr.ready:
            return True
        time.sleep(0.5)
        if int(time.time() - t0) % 10 == 0:
            sys.stdout.write(".")
            sys.stdout.flush()
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", action="store_true", help="只打样本电平")
    a = ap.parse_args()

    # ------------------------------------------------------------------ A 电平
    print("=" * 78)
    print("A 样本电平 —— 断句阈值要按**实测**定，不能拍脑袋")
    print("=" * 78)
    for stem in (WAKE_ONLY, ONE_SHOT, "neg_weather"):
        x = pcm(stem)
        pk, rms = asr.level(x)
        print("  %-26s 峰值 %.4f   RMS %.4f   幅度比 %.3f"
              % (stem, pk, rms, rms / pk if pk else 0))
    tdir = ROOT / "models" / "sherpa" / "sherpa-onnx-kws-zipformer-wenetspeech-3.3M-2024-01-01" / "test_wavs"
    if tdir.is_dir():
        ws = sorted(tdir.glob("*.wav"))
        for p in ws[:3]:
            x = asr.wav_bytes_to_float32(p.read_bytes(), want_sr=SR)
            pk, rms = asr.level(x)
            print("  真人录音 %-18s 峰值 %.4f   RMS %.4f   （%.1f s）"
                  % (p.stem, pk, rms, len(x) / SR))
    print("  → 说话时的峰值都在 0.0x~0.x 量级；whisper 路的 speech_peak=0.02、")
    print("    quiet_ratio=0.10 是照这些数取的，换机器/换麦克风要重新看这张表。")
    if a.levels:
        return 0

    # ------------------------------------------------------------------ B 全链路
    print("\n" + "=" * 78)
    print("B 一口气说：「你好，小瑞，我有点困」")
    print("=" * 78)
    v = VoiceLoop()
    print("  唤醒路：%s" % ("就绪" if v.kws.ready else v.kws.why))
    print("  识别路：%s" % v.asr_note)
    if not v.kws.ready:
        return 1
    sys.stdout.write("  等识别模型加载 ")
    ok = wait_asr(v)
    print(" %s" % ("好" if ok else "超时"))
    if not ok:
        print("  ⚠️ 识别没就绪（%s）—— 唤醒那部分照样测，出文字的部分会如实报'没听清'"
              % getattr(v.asr, "why", ""))
    print("  识别引擎：%s" % v.asr.status().get("engine"))

    x = pcm(ONE_SHOT)
    # 末尾补静音：真实麦克风是一直在流的，说完之后静音继续来 ——
    # 断句就是靠这一段判的。文件本身只有 0.7 s 尾巴，不够（见 `TAIL`）。
    x = np.concatenate([x, np.zeros(int(TAIL * SR), dtype=np.float32)])
    evs = feed(v, x, "① ")

    wakes = [e for e in evs if e["type"] == "wake"]
    check(len(wakes) == 1, "只唤醒一次（实际 %d 次）" % len(wakes))
    if wakes:
        check(wakes[0]["word"] == "你好小瑞",
              "唤醒词报的是「%s」" % wakes[0]["word"])
    need = [e for e in evs if e["type"] == "need_answer"]
    heard = [e for e in evs if e["type"] == "heard"]
    if ok:
        check(len(need) == 1, "出了一条要交给大脑的文本（实际 %d 条）" % len(need))
        if need:
            t = need[0]["text"]
            print("      识别出来的是：「%s」" % t)
            check(bool(t), "文本不是空的")
            check("困" in t, "整句接上了（含'困'这个字）—— 说明唤醒前那一秒没丢")
    else:
        check(len(need) == 0, "识别没就绪时**不编话**（没出需要回答的事件）")
    # 没出文字时，把**为什么**打出来。空串可能是"真没声音"，也可能是"音频读不了/
    # 模型没就绪" —— 不看这个就只能猜，而猜错方向会浪费一整轮（见 _wake_reset.py）。
    if not need and hasattr(v.asr, "status"):
        s = v.asr.status()
        print("      为什么没出文字：%s（这段音频 %.2f s，耗时 %s ms）"
              % (s.get("last_why") or "（没有说明）", s.get("last_dur_s", 0),
                 s.get("last_ms", 0)))

    # ------------------------------------------------------------------ C 说话期间不被自己的声音叫醒
    print("\n" + "=" * 78)
    print("C 小瑞说话时，喂唤醒词不应该有反应（没有回声消除，只能靠半双工）")
    print("=" * 78)
    v.speaking()                       # 走真实那一支（服务端也是调它，不直接改 state）
    check(v.state == loop_mod.SPEAK, "speaking() 之后状态是 SPEAK（现在 %s）" % v.state)
    evs = feed(v, pcm(WAKE_ONLY), "② ")
    check(len(evs) == 0, "SPEAK 期间喂唤醒词，事件数 = %d（必须是 0）" % len(evs))

    # ------------------------------------------------------------------ D 追问窗口
    print("\n" + "=" * 78)
    print("D 念完之后进**追问窗口**：接着说就接着答，不用再喊唤醒词")
    print("=" * 78)
    rnd = v.round                     # 服务端的看门狗认的是这个号，见 loop.py 的 round
    check(rnd >= 1, "轮次号在外发过文本之后涨到了 %d（看门狗靠它认轮次）" % rnd)
    v.answer_done()
    check(v.state == loop_mod.FOLLOW,
          "念完之后进的是追问窗口（现在 %s）—— 不是 IDLE" % v.state)
    check(v.round == rnd, "answer_done 不动轮次号（还是 %d）" % v.round)
    # ⚠️ 这一条守的是用户报的那个 bug，原话：「我在说了你好 小瑞之后 它只回复一句话
    #    根本不听我后边说的什么 也不去做 他应该听我后边的啊」。
    #    `neg_weather` 是「你好，今天天气怎么样」—— **里面没有小瑞两个字**，
    #    所以它只可能在追问窗口里被接住；窗口没开的旧版本这里一条事件都不会有。
    wakes_before = v.status()["wakes"]
    x = np.concatenate([pcm("neg_weather"), np.zeros(int(TAIL * SR), dtype=np.float32)])
    evs = feed(v, x, "③ ")
    check(len([e for e in evs if e["type"] == "wake"]) == 0,
          "追问窗口里**不靠唤醒词**（唤醒次数还是 %d 次）" % wakes_before)
    need2 = [e for e in evs if e["type"] == "need_answer"]
    check(len(need2) == 1, "接着说的一句被接住了（要回答的文本 %d 条）" % len(need2))
    if need2:
        t2 = need2[0]["text"]
        print("      接住的是：「%s」" % t2)
        check("天气" in t2, "而且就是**接着说**的那一句（含'天气'）")

    # --------------------------------------- D1b 主人正在说话时，窗口**不许**按时钟关
    print("\n" + "=" * 78)
    print("D1b 窗口到点时主人**正在说** → 不许关（关了 = 这一句被整句扔掉）")
    print("=" * 78)
    # 为什么单列这一条：`follow_s` 和"说完了"那条判据现在**是同一个数**（10 s），
    # 于是"进窗口起算 10 s"和"最后一次出声之后安静 10 s"就撞在一起了 —— 主人只要
    # 在窗口里开口（哪怕第 1 秒就说），收口最早也要等到第 11 秒，比窗口晚。
    # 第一版是照挂钟收窗口的，结果**追问窗口里永远接不住第二句**。而 D 段测不出来：
    # 它把整段音频一口气喂完，**挂钟根本没走**（这也是 D2 要把窗口改小 + 真 sleep
    # 的原因）。所以这一条必须按**真挂钟**来量：说半句 → 真的睡过窗口 → 再接着说。
    # ⚠️ 逮到它的是 `_check_voice_do.py`（按 100 ms 的真实节拍喂），不是这一份。
    v.answer_done()                   # 刚答完一句 → 又开一个窗口
    check(v.state == loop_mod.FOLLOW, "新窗口开了（现在 %s）" % v.state)
    half = pcm("neg_plain")[: int(1.2 * SR)]     # 1.2 s 真人说话（够 `_heard()` 黏住）
    evs = feed(v, half, "⑤ ")
    lv = v.asr.status().get("levels") or {}
    # ⚠️ 先单独确认"识别器确实认为听到了人声" —— 不然下面那条红是**电平判据**的锅
    #    （样本太轻/增益太低），不是窗口的锅，两件事要分得开。
    check(bool(v._heard()),
          "识别器认为这一句里有人说话（speech_s=%s peak=%s）"
          % (lv.get("speech_s"), lv.get("peak")))
    check(not any(e["type"] in ("idle", "need_text") for e in evs),
          "说了半句还不该收口")
    keep, v.follow_s = v.follow_s, 0.3
    time.sleep(0.5)                   # **真挂钟**：睡过窗口（0.3 s）
    evs = feed(v, np.zeros(CHUNK, dtype=np.float32), "⑥ ")
    v.follow_s = keep
    check(v.state == loop_mod.FOLLOW,
          "★ 窗口到点了、但主人说过话 → 留在追问窗口里（现在 %s，"
          "掉了就是「整句被扔」那个 bug 又回来了）" % v.state)
    check(not any(e["type"] == "idle" for e in evs), "而且没给页面发 idle")
    # ③ 接着说 → 整句必须接得住（收口仍由那条 10 s 静音判据决定）
    evs = feed(v, np.concatenate([pcm("neg_plain"),
                                  np.zeros(int(TAIL * SR), dtype=np.float32)]), "⑦ ")
    need3 = [e for e in evs if e["type"] == "need_answer"]
    check(len(need3) == 1, "接住了、而且只接住一句（%d 条）" % len(need3))

    # ------------------------------------------------------- D2 窗口到点自己关
    print("\n" + "=" * 78)
    print("D2 窗口到点没人说话 → 自己回 IDLE（且**识别器要清干净**）")
    print("=" * 78)
    v.answer_done()                   # 上面那一句的答复念完了 → 又是一个新窗口
    check(v.state == loop_mod.FOLLOW, "新的一轮又开了窗口（现在 %s）" % v.state)
    # ⚠️ 窗口超时是**挂钟**计时（`follow_s`），压缩回放里推不动它 ——
    #    和下面「第二次叫不醒」是同一个坑，所以这里把窗口改小 + **真的 sleep**。
    keep, v.follow_s = v.follow_s, 0.3
    time.sleep(0.5)
    evs = feed(v, np.zeros(CHUNK, dtype=np.float32), "④ ")
    v.follow_s = keep
    check(v.state == loop_mod.IDLE, "到点自己回 IDLE（现在 %s）" % v.state)
    check(len([e for e in evs if e["type"] == "idle"]) == 1, "给页面发了 idle")
    # ⚠️ 用 `.get` 取：`levels` 是 whisper 那条路报的（流式那条没有这个字段），
    #    这个断言是**守 whisper** 的 —— 它才是"攒满 8 s 静音、下一句被整段拒收"
    #    会咬人的那一条。
    lv = v.asr.status().get("levels") or {}
    check(float(lv.get("speech_s", 0) or 0) == 0 and float(lv.get("silent_s", 0) or 0) == 0,
          "识别器的缓冲清干净了（speech_s=%s silent_s=%s —— 不清的话下一句一开口就撞"
          "'太长了'）" % (lv.get("speech_s"), lv.get("silent_s")))

    # ------------------------------------------------------- D3 再叫一次还得能叫醒
    print("\n" + "=" * 78)
    print("D3 窗口关掉之后，再叫一次还得能叫醒（别叫醒一次就哑了）")
    print("=" * 78)
    # ⚠️ **余音保护（GUARD_S=0.4 s）是按挂钟算的，所以这里必须真的等**。
    #    第一版是"喂 0.6 s 静音把时间推过去"—— 那是错的：回放 0.6 s 音频只要
    #    几毫秒，挂钟根本没走，保护窗口一直压着，于是"第二次叫不醒"。
    #    这和 `debounce_s` 是同一类坑（见 ui/voice/kws.py 的第 2 条纪律）：
    #    **凡是按挂钟计时的机制，在压缩时间的回放里都不成立。**
    time.sleep(loop_mod.GUARD_S + 0.1)
    # 还有一道：第一次唤醒留下的**去抖**（debounce_s=1.0，也是挂钟时间）。
    # 回放跑得太快，第二次唤醒会落在那 1 s 窗口里被吃掉 —— 和上面是同一个道理，
    # 回放前显式清掉（线上不需要，线上音频本来就是实时到的）。
    v.kws.clear_debounce()
    v.answer_done(follow=False)       # 收干净，别让窗口开着（这一条测的是唤醒）
    time.sleep(loop_mod.GUARD_S + 0.1)
    v.kws.clear_debounce()
    evs = feed(v, pcm(WAKE_ONLY), "⑤ ")
    check(len([e for e in evs if e["type"] == "wake"]) == 1,
          "第二次也叫醒了（余音保护过后）")

    # ------------------------------------------------------------------ F 一直说
    # ⚠️ 这一段是**回归**，它守的是一个真的发出去过的 bug（浏览器那一路自测抓到的）：
    #    状态机原来把「单句最长」写死成 26 s，而 whisper 的上限是 8 s ——
    #    于是 8~26 s 之间的整句，攒到收口那一刻被识别器**整段拒收**（不是截断），
    #    用户说的一整句全丢，页面上只说「没听清」。真值一句话就能说清：
    #    **「说多长算太长」是识别器的属性，不是状态机的**，所以必须从识别器那边取。
    #
    # 🔴 2026-09-26 用户改了规矩：「语音结束的标志是我中途 10s 没有发出声音」
    #    ——「单句最长」于是从**判据**降级成**安全阀**（299.5 s，管的是「装不下」）。
    #    这一段守的东西也跟着翻了个面：
    #      · 旧：该截的时候要截（cap+0.3 之内必须收口）
    #      · 新：**不该截的时候一个字都不许截** —— 没有 10 s 静音就一直听
    #    两次都留着的那条不变：安全阀必须**短于**识别器能吃下的长度（留 0.5 s 余量），
    #    否则攒到识别器那里才被拒收，等于白留。
    print("\n" + "=" * 78)
    print("F 一直说：没有 10 s 静音就不收口；收口那一刻整句还得能出文字")
    print("=" * 78)
    st_asr = v.asr.status()
    cap, loc = st_asr.get("max_utterance_s"), None
    loc = getattr(getattr(v.asr, "_local", None), "max_s", None)
    sil_s = getattr(v.asr, "silence_s", None)
    print("  识别器能吃下的最长一句：%s s；状态机自设的安全阀：%s s；断句线：%s s"
          % (loc, cap, sil_s))
    check(cap is not None, "识别路报出了自己的单句上限（status.max_utterance_s）")
    if cap is not None and loc:
        check(float(cap) < float(loc),
              "安全阀（%s s）**短于**识别器能吃下的（%s s）—— 留了余量才有得截" % (cap, loc))
    check(sil_s is not None and abs(float(sil_s) - 10.0) < 0.01,
          "断句线就是用户拍板的 10 s（实际 %s）" % sil_s)
    if cap is not None and sil_s:
        check(float(cap) > 4 * float(sil_s),
              "安全阀（%s s）远在断句线（%s s）之外 —— 它管的是「装不下」，不是「说完了」"
              % (cap, sil_s))
    v.stop()                          # 清干净再喂，免得带上 D 段那半句
    v.kws.clear_debounce()
    long_x = np.tile(pcm(ONE_SHOT), 4)    # ≈ 15 s，句内停顿只有 0.7 s，够不着 10 s 的断句线
    print("  喂一段 %.1f s 不停的话（句内那 0.7 s 停顿够不着断句线）" % (len(long_x) / SR))
    evs = feed(v, long_x, "④ ")
    cut0 = [e for e in evs if e["type"] == "need_text"]
    check(len(cut0) == 0,
          "**说了 %.1f s 一个字都没被截**（收口 %d 次；安全阀要到 %s s 才动）"
          % (len(long_x) / SR, len(cut0), cap))
    check(v.state == loop_mod.LISTEN,
          "说完这 %.1f s 还在听（现在 %s）—— 主人还没静够 10 s" % (len(long_x) / SR, v.state))

    # 接着说完了：补 10.5 s 静音，这时候才该收口
    #
    # ⚠️ 判据要**带上识别器自己已经算进去的那段静音**，不能只看"我补的那 10.5 s"：
    #    样本自己末尾就拖着静音（`pos_hello_xiaorui_slow.wav` 的尾巴），那几秒在
    #    判据眼里和我补的静音是**同一件事**。上一次跑就是照"我补的"去比，报出
    #    "静音第 9.2 s 才收" —— 而那是**对的**（9.2 + 样本尾巴 ≈ 10）。所以这里
    #    直接问识别器要它自己那个计数（`status().levels.silent_s`），不猜、不凑。
    pre_sil = float((v.asr.status().get("levels") or {}).get("silent_s") or 0.0)
    print("  补静音之前识别器已经算了 %.2f s 静音（样本自己的尾巴，那也是静音）" % pre_sil)
    evs2 = feed(v, np.zeros(int(TAIL * SR), dtype=np.float32), "⑤ ")
    cut = [e for e in evs2 if e["type"] == "need_text"]
    heard_long = [e for e in evs2 if e["type"] == "heard"]
    check(len(cut) == 1, "补上 10.5 s 静音之后才收口（收口 %d 次）" % len(cut))
    if cut:
        sil = cut[0]["_ms"] / 1000.0
        check(sil + pre_sil >= float(sil_s or 10.0) - 0.15,
              "收口发生在**静音满 %s s 之后**（样本尾巴 %.1f s + 补的 %.1f s = %.1f s）"
              % (sil_s, pre_sil, sil, pre_sil + sil))
    if heard_long:
        t = heard_long[0]["text"]
        print("      整句（%.1f s 说话 + %.1f s 静音）识别出来是：「%s」"
              % (len(long_x) / SR, TAIL, t))
        check(bool(t), "**这么长的一句照样出文字**（整句没被识别器拒收）")
        check("困" in t, "中间那几遍还认得出来（含'困'）")
    if not (heard_long and heard_long[0]["text"]) and hasattr(v.asr, "status"):
        print("      为什么没出文字：%s" % (v.asr.status().get("last_why") or "（没有说明）"))

    # ------------------------------------------------------------------ G 抢话
    # ⚠️ 这一条守的是**用户报的同一个 bug 的另一半**：主人听小瑞半天不吭声，
    #    就接着把下一句说下去了 —— 而这几秒是 THINK（等 DeepSeek，2.6 s 上下），
    #    喇叭是静的，主人说的话**一个字都不该丢**。
    #    旧版本 `if self.state == THINK: return ev` 是直接从门口扔掉的。
    print("\n" + "=" * 78)
    print("G 趁小瑞还在想（THINK）的时候接着说的那一句，不能丢")
    print("=" * 78)
    v.stop()
    v.kws.clear_debounce()
    x = np.concatenate([pcm(ONE_SHOT), np.zeros(int(TAIL * SR), dtype=np.float32)])
    evs = feed(v, x, "① ")
    check(v.state == loop_mod.THINK, "第一句进了 THINK（现在 %s）" % v.state)
    think_ms = v.status()["think_ms"]
    print("      THINK 期间攒下的音频：%d ms" % think_ms)
    # 主人接着说第二句（这时候小瑞还没有任何声音）—— 它只该进缓冲
    x2 = np.concatenate([pcm("neg_weather"), np.zeros(int(0.4 * SR), dtype=np.float32)])
    evs2 = feed(v, x2, "② ")
    check(len(evs2) == 0, "THINK 期间不出声、不识别（事件数 %d）" % len(evs2))
    check(v.status()["think_ms"] > think_ms, "攒下来的音频变多了（那是主人接着说的）")
    v.answer_done()                   # 答复念完 → 追问窗口开 → 补喂
    check(v.state == loop_mod.FOLLOW, "进追问窗口了（现在 %s）" % v.state)
    check(v.status()["think_ms"] == 0, "补喂之后那段缓冲归零（不会重喂第二遍）")
    evs3 = feed(v, np.zeros(int(TAIL * SR), dtype=np.float32), "③ ")
    need3 = [e for e in evs3 if e["type"] == "need_answer"]
    check(len(need3) == 1, "补喂的那一句断句了（要回答的文本 %d 条）" % len(need3))
    if need3:
        t3 = need3[0]["text"]
        print("      补喂之后识别出来的是：「%s」" % t3)
        check("天气" in t3, "**就是抢在小瑞答话之前说的那一句**（含'天气'）")

    # ------------------------------------------------------------------ E 状态
    print("\n" + "=" * 78)
    print("E 状态")
    print("=" * 78)
    st = v.status()
    for k in ("state", "wakes", "answers", "asr_ready", "preroll_ms"):
        print("  %-12s %s" % (k, st[k]))
    print("  唤醒       %s" % st["kws"]["engine"])
    print("  识别       %s" % st["asr"]["engine"])

    print("\n" + "=" * 78)
    if FAILS:
        print("❌ %d 条不对：" % len(FAILS))
        for f in FAILS:
            print("   · %s" % f)
        return 1
    print("✅ 全对 —— 唤醒 → 断句 → 出文字，全离线跑通；说话期间不被自己的声音叫醒。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
