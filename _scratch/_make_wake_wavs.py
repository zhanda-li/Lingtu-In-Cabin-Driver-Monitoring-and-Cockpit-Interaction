# -*- coding: utf-8 -*-
"""生成唤醒词自测用的样本（SAPI 离线合成，不联网）。

    python _scratch/_make_wake_wavs.py

为什么要码点拼中文：这台机器上 PowerShell 5.1 按 GBK 读脚本，命令行里的中文
会被解析坏（见 `windows-dev-env` 那条记录）。所以源码里**全 ASCII**，中文用
`[char[]](0x4F60,...)` 在 PS 侧拼出来 —— 这样整条链路一个字节的中文都不经过
shell。

样本分两类，**正样本和反样本都要有**：
  pos_*  —— 说了唤醒词，必须叫醒
  neg_*  —— 没说到唤醒词，**必须不叫醒**（反样本才是唤醒词真正难的地方：
            「你好，小心前面那辆车」里"小心"和"小瑞"只差一个韵母）

产出的 wav 是 22.05 kHz 单声道，交给 `ui/asr.py` 的 `wav_bytes_to_float32`
转 16 kHz —— 复用现成的那个函数，别在这儿再写一遍重采样。
"""
import os
import subprocess
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

OUT = os.path.join("runs", "wake_samples")
SAMPLES = {
    "pos_hello_xiaorui": "你好，小瑞",
    "pos_hello_xiaorui2": "你好小瑞",
    "pos_hello_xiaorui_slow": "你好，小瑞，我有点困",
    # ★ 2026-09-25：`_check_voice_do.py` 要用它 —— 用户报的那句原话
    #   （「你好小瑞给我放个音乐 它怎么不放」）。唤醒词和内容**一口气**说，
    #   和 `pos_hello_xiaorui_slow` 同一个形状：要先被叫醒、再整句识别出来。
    #   ⚠️ 句子里**必须留着「音乐」两个字**：`xiaorui.py` 的 `KEYWORDS` 靠它命中
    #      `music` 意图（`("music", ("音乐","歌","放点","来一首","广播","听听"))`）。
    #      改这句文案时别把它顺手改没了，否则 `_check_voice_do.py` 会走成 chat 意图。
    "pos_music": "你好，小瑞，给我放个音乐",
    # ★ 2026-09-26：用户要「对这个网页所有东西的操控权」——说「打开某一页」就得真跳、
    #   说「导航到服务区」就得真跳到导航页去查。`_check_voice_do.py` 的 H 段要用这两个。
    #   ⚠️ 两句都必须留着**动词 + 页面呼法**：`detect_action` 判「打开某一页」要
    #      动词（`GO_VERBS` 里有「打开」）**和**呼法（`GO_WORDS` 里 media 那一行有
    #      「多媒体」）两样都在；「我要去休息区」靠 `REST_WORDS`（「休息区」）
    #      **加** `NAV_CMD`（「我要去」）、且不能撞上 `ASK_WORDS` —— 少一样就会掉进
    #      `nearby`（问句）或者 `chat`，H 段当场红，而那是**样本的锅不是产品的**。
    #      改这两句文案时，把这两条一起念一遍再改。
    #   🔴 这句**故意说「休息区」不说「服务区」**，别改回去。实测（见
    #      `_probe_rest_stop_wav.py`）：whisper-**base** 对 SAPI 合成的「服务区」
    #      很不稳 —— 「导航到最近的服务区」被听成「倒行到最近的服務」/「服務區」/
    #      「服務群」，六种说法一半落空；而「我要去休息区」**一字不差**。
    #      两个词都在 `REST_WORDS` 里、都由 `detect_action` 判成同一个动作，所以
    #      这只是**换一个识别得稳的说法**，判据一个字没松。
    #      ⚠️ 这是"合成音 + base 模型"的坑，**不是**说真人也听不出「服务区」——
    #         同一批里「前面有服务区吗」「服务区在哪里」反而一字不差（和语调有关）。
    #         所以**不许**拿这条去放宽 `REST_WORDS`，那是拿噪声改产品。
    "pos_goto_media": "你好，小瑞，打开多媒体",
    "pos_rest_stop": "你好，小瑞，我要去休息区",
    # ★★ 2026-09-26：`_check_voice_do.py` 的 A 段要用它 —— **用户报的那句原话**
    #   「我让它导航咋不做」。原来这句话在 `detect_action` 里判出**空串**（`NAV_CMD`
    #   只在服务区分支里被读，而这句话里没有「服务区」），于是落进模型那一支，
    #   模型现编了一句"要不要我帮您导航到最近的服务区？"，**服务端一次动作都没发起**。
    #   A1 之后它判成 `rest_stop`。
    #   ⚠️ 句子里**必须留着「导航」两个字**（`NAV_STRONG` 靠它，这是这张表存在的
    #      理由）；也别改成「打开导航页」—— 那是 `go:navi`，另一支。
    #   🔴 **这里不是用户的原话"给我导航"，是"导航"** —— 这是量出来的，不是随手改的：
    #      SAPI 合成 + whisper 把「给我导航」听成**「给我倒行」**（「航」丢了），
    #      「我要导航」→「我要倒行」、「开始导航」→「开始到床」、「帮我导航」→
    #      「帮我倒行」—— 都判不出动作（见 `_probe_nav_wav.py`，十个说法逐个真喂）。
    #      而「导航」两个字**一字不差**（→`'你好小瑞导航'`→`rest_stop`）。
    #      ⚠️ 所以分工要记清：
    #        · **F 段**（纯判据表、不经过音频）钉的才是**用户的原话**「给我导航」；
    #        · **A 段**（真音频 → 真识别 → 真发 `do`）用的是这句能认出来的说法。
    #      两句合起来才等于"那句话真的通了"。**不许**只留一句就说验过了。
    #   ⚠️ 这是"合成音 + base 模型"的坑，**不是**说真人也听不出「给我导航」。
    #      不许拿它去放宽 `NAV_STRONG`（那是拿噪声改产品）。
    "pos_goto_nav": "你好，小瑞，导航",
    # ★★ 2026-09-26：**同意上一句的提议**（`take_pending` 要靠 `is_affirm` 认出它）。
    #   🔴 这里**故意不写「要」** —— 一个字的词 whisper 认不出来，实测（见
    #      `_probe_affirm_wav.py`，10 个候选逐个真喂给服务端那条识别路）：
    #        「要」→ 空串、「好」→ 空串、「行」→「作画」、「嗯嗯」→「保重加勤」；
    #        而**两个字以上**的一认一个准：「要的」「好的」「可以」「可以可以」
    #        「来吧」「去吧」→ 原样回来。
    #      所以样本用「要的」（和主人真会说的「要」最接近，同时认得出来）。
    #   ⚠️ 这一条**不是**说真人也认不出「要」：同一个坑在 `pos_rest_stop` 那条注释里
    #      记过（合成音 + base 模型对短词/语调不稳）。**不许**拿它去删 `AFFIRM` 里的
    #      单字 —— 那几行不要钱，删了才是拿测试迁就代码。
    #      但它**值得说给人听**：真机上主人说「嗯」「行」是可能落空的，说「好的」
    #      「要的」「可以」稳得多（2026-09-26 手点那一条就该照这个说）。
    #   🔴 **这句里绝对不能带唤醒词。** `is_affirm` 要的是**整句相等**，而
    #      `pos_music` 那种"唤醒词和内容一口气说"的样本，整段音频（连唤醒词）
    #      会一起进识别 —— 回上来的是「你好小瑞要的」，`is_affirm` false。
    #      （`detect_intent` 靠"句子里有没有「音乐」"命中，所以它不怕带唤醒词；
    #        `is_affirm` 是**整句相等**，怕。）
    #      → 这一段走的正是**追问窗口**那条路：小瑞刚问完，主人**不喊唤醒词**
    #        直接应一声。那也是真机上最自然的用法（见 `ui/voice/loop.py` 的 FOLLOW）。
    "pos_affirm": "要的",
    # ★★ 2026-09-26：E 段要用它 —— **问完那句之后主人换了话题**。
    #   待确认的动作必须被顶掉（`take_pending` 是"取走即清"），
    #   之后再喂「要的」**不许**发出 `ev:"do"`。这句话本身不碰任何意图。
    #   ⚠️ 同样**不带唤醒词**（在追问窗口里说，见上一条）。
    "pos_other_topic": "今天天气不错",
    "neg_weather": "你好，今天天气怎么样",
    "neg_xiaoxin": "你好，小心前面那辆车",
    "neg_name_only": "小瑞",
    "neg_plain": "帮我把空调调低两度",
}


def cps(s: str) -> str:
    return ",".join("0x%04X" % ord(c) for c in s)


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    bad = 0
    for name, text in SAMPLES.items():
        path = os.path.abspath(os.path.join(OUT, name + ".wav"))
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            print("  ✓ %-24s 已经有了" % name)
            continue
        ps = (
            "Add-Type -AssemblyName System.Speech; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$s.Rate = 0; "
            "$s.SetOutputToWaveFile('%s'); " % path +
            "$s.Speak([string]::Join('', [char[]](%s))); " % cps(text) +
            "$s.Dispose()"
        )
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive",
                            "-Command", ps],
                           capture_output=True, text=True)
        ok = os.path.exists(path) and os.path.getsize(path) > 1000
        print("  %s %-24s %-22s %s"
              % ("✓" if ok else "✗", name, text,
                 "%d bytes" % os.path.getsize(path) if ok else "合成失败"))
        if not ok:
            bad += 1
            print("      " + (r.stderr or r.stdout or "")[:300].replace("\n", " "))
    print("\n样本目录：%s" % os.path.abspath(OUT))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
