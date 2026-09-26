# -*- coding: utf-8 -*-
"""小瑞的耳朵：状态机。把「一直听唤醒词 → 听到就录 → 录完交给大脑 → 说完再回去听」串起来。

    v = VoiceLoop()
    for ev in v.feed(pcm16k):      # 页面送来的实时音频，一直喂
        print(ev)                  # → {'type':'wake'} / {'type':'partial',...} / …

    # 收到 need_answer 之后，调用方去问 DeepSeek（那是慢操作，要放线程里），
    # 拿到回复先让页面/服务端念，念完告诉状态机：
    v.answer_done()

**这个文件里没有网络、没有 aiohttp、没有 DeepSeek** —— 那些都在调用方
（`ui/server.py` 的 WS 那一段）。这里只有状态和音频，所以能单独跑、单独测
（`_scratch/_check_voice_loop.py`）。

状态：

    IDLE ──唤醒词──▶ LISTEN ──静音断句──▶ THINK ──收到回复──▶ SPEAK ──念完──▶ FOLLOW
      ▲                                       ▲                │               │
      │                                       │            唤醒词           接着说了话
      │                                       │          （掐断它的话）        ▼
      │                                       │                └─▶ LISTEN ── THINK
      │                                       └────────── 静音断句 ──────────┘
      └──── 没听清 / 超时 / 静默满 follow_s ───┘
      （FOLLOW 里**没人说话**满 `follow_s` 秒也回 IDLE；一开口就按上面那条静音判据收口）
      ⚠️ SPEAK ──唤醒词──▶ LISTEN 这条路要求 `barge_in_ok` 为真，见第 1 条。

★ **FOLLOW（追问窗口）是 2026-09-26 加的，它补的是真人用起来最别扭的那一下。**
  原来的循环是 SPEAK ──念完──▶ IDLE，而 IDLE **只认唤醒词**：主人问了一句
  「你好小瑞」，小瑞答「主人，我在。有什么要我帮忙的？」，然后主人说「给我放个音乐」
  —— 这一句被**整句丢掉**，因为它不在唤醒词后面。用户报的原话就是
  「我在说了你好 小瑞之后 它只回复一句话 根本不听我后边说的什么 也不去做
   他应该听我后边的啊」。这句「有什么要我帮忙的」本身就是个**反问**，
  反问之后却不听，是这套东西最不像人的地方。
  现在念完之后 **10 秒内**（`FOLLOW_S`）**不用再喊唤醒词**，接着说就接着答；
  连着说就连续对话，静默满 10 秒才回 IDLE。
  ⚠️ 这个 10 和"说完了"那条判据（`whisper_silence_s` / `rule1_min_trailing_silence`）
     **是同一个数、同一条规矩**：用户 2026-09-26 拍板「语音结束的标志是我中途 10s
     没有发出声音」「否则可以一直说 一直对话」。**改一个必须改另一个** ——
     不然会出现"句子还没说完，对话已经结束了"这种自相矛盾的状态。
     ⚠️ 真要改的时候看清楚：**它不是"进窗口 10 s 后就关窗口"**（曾经是，
        那是个真 bug，见 `feed()` 里 FOLLOW 那一支）—— 主人一开口，窗口就不再
        按时钟收，改成由识别器那条静音判据收口。两个 10 是"同一个数"说的是
        **判据**（安静多久算说完），不是"两道独立的计时器同时倒计时"。

⚠️ 半双工，但**可以被打断**（2026-09-26 用户拍板改成这样）：
  小瑞**正在念**的时候（SPEAK）主人插话，那几秒**内容**仍然是丢的 —— 没有回声
  消除，它分不清是主人说的还是自己的声音从喇叭绕回麦克风。**所以 SPEAK 期间
  ASR 一个字节都不喂这件事没有变，也变不了。**
  变的是**唤醒词那一层**：SPEAK 期间 KWS 是**开着**的 —— 主人喊一声唤醒词，
  状态机当场进 LISTEN，并且让页面**把小瑞的话掐断**（服务端发 `ev:"halt"`，
  页面 `XQ.tts.halt()` → `speechSynthesis.cancel()`）。
  用户的原话是「它回复我话的时候 我说话为啥它听不见」，选的是「掐断+听」：
  与其"你说话时它听不见"，不如"你叫它一声，它闭嘴听你说"。
  能办到的补偿还有一条：**主人趁小瑞在想（THINK）的时候接着说的话不会丢** ——
  那几秒喇叭是静的，见第 6 条。

⚠️ 六个真会咬人的地方，都在这儿处理掉了：

  1. **自己的声音会把自己叫醒。** 这套东西**没有回声消除（AEC）**，喇叭放出来的
     "小瑞在呢，主人" 会被麦克风听进去 —— 里面要是带了唤醒词，就自激了。
     所以念完要压一小段静默（`GUARD_S`）等音箱的余音散掉，
     **而且 SPEAK 期间开 KWS 这件事有一个总闸**（`barge_in_ok`，见下面 `feed()`
     的 SPEAK 那一支）：只有"掐得断"的那条路才开 —— 服务端兜底在念的时候
     掐不断（`ui/tts.py` 的 `stop()` 是一次性闩锁），那种情况下照旧一个字节都不喂，
     否则它自己的声音会被当成主人的话。另外服务端在组话时还会挡一手：
     哪一句答复里带唤醒词，那一轮就不开这个闸。
  2. **唤醒词后面的话不能丢。** 真人说话是"你好小瑞我有点困"一口气说完的，
     唤醒命中的那一瞬间，这句话已经说了一半。所以 IDLE 期间音频**一直**进
     环形缓冲（`RingBuffer`），唤醒时先把缓冲里那一段补喂给 ASR，再接着喂实时的。
  3. **IDLE 期间不跑 ASR。** ASR 比 KWS 贵得多（KWS 1.6% 一颗核），没人说话时
     没必要一直识别。只在 LISTEN 期间跑 —— 这是"常听"能便宜的关键。
  4. **唤醒要有超时。** 叫醒了却不说话（或者只是电视里说了个词），不能一直
     录下去：`WAKE_TIMEOUT_S` 那一档兜底到点就回 IDLE。
     ⚠️ 这个兜底**只在"一个字都没听到"时才出手**（`not self._heard()`）——
       主人真的在说话时它能一直听下去，那是用户 2026-09-26 要的「可以一直说」。
     ⚠️ 但"说完了"的**正常**出口是识别器自己（静音断句）。这个兜底只防"识别器的
        规则没生效"，**别把它当单句长度的设定值**：它比识别器能收下的长得多，
        拿它当设定值的话，中间那一段会**整句丢掉**（踩过，见常量注释）。
  5. **ASR 没就绪时唤醒照样要能工作。** 唤醒模型 3.3 MB 早就下好了，识别模型
     133 MB（要联网下）。所以这里 `asr.ready` 是 False 也**不影响唤醒**，
     只是听到之后没法转文字 —— 如实告诉用户"识别模型还没下好"，别假装。
  6. **趁小瑞在想的时候接着说的那半句，不能丢。** THINK 那几秒（一次 DeepSeek
     往返 ≈ 2.6 s）**喇叭是静的**，主人听不到动静就接着说下去了 —— 而原来的
     `if self.state == THINK: return ev` 是把这几秒的音频**直接从门口扔掉**。
     现在这几秒进 `self.think`（一个独立的环形缓冲），等 `answer_done()` 打开
     追问窗口时**先把它补喂给识别器**，主人那句"给我放个音乐"就接得上。
     ⚠️ 只攒 THINK，**不攒 SPEAK**：SPEAK 那几秒麦克风里是小瑞自己的声音
     （从喇叭绕回来的），攒下来就是把它的声音当主人的话说（见第 1 条）。
"""
from __future__ import annotations

import time

import numpy as np

from asr_stream import RingBuffer, make_asr           # noqa: F401 (同目录)
from kws import SR, WakeWord

# 兜底窗口（秒）：**正常情况下永远不该它出手**。正常出口是 `asr.endpoint()`
# ——"说完了"（静音够久，2026-09-26 起是 10 s）。
# 这里留着是防"识别器那条规则没生效"（换了个模型、规则没配），
# 那样的话没有它就是无限录下去。
#
# ★ 2026-09-26：这一条加了 `not self._heard()` 这个条件，**只管"一个字都没听到"**。
#   用户要的是「可以一直说 一直对话」，所以主人真在说话时这条兜底绝不许出手
#   （原来到点就收，一口气说超过 26 s 的那句会被从中砍断）。
#
# ⚠️ 这个数**不许**小于识别器的单句上限（安全阀），否则正常的句子会被它先砍掉。
#    真实上限在 `asr_stream.WhisperAsr.max_utterance_s`（从 `LocalAsr.max_s` 推出来）/
#    流式那条的 `rule3_min_utterance_length`。**踩过**：这里写死过 26 s，而 whisper
#    的上限当时是 8 s，于是 8~26 s 的整句被**整段拒收**（不是截断，是全丢），
#    页面上只说"没听清"。
#    ⚠️ 判据不是"这个数小于上限"就没事：真正要成立的是**上限本身短于识别器能收下的
#       长度**（`WhisperAsr` 里那种 −0.5 s 的余量就是这么来的）。
#
# ⚠️ 已知的后果，先说在这儿别让人当 bug 查：叫醒了**一句话都不说**（误唤醒、
#    电视里的词）时，识别器判不出"说完了"，所以会硬听到 26 s 才回 IDLE ——
#    这 26 s 里叫它，它是听不见的。想改的话得先在**目标机器上量** `WhisperAsr`
#    的 `speech_peak`（见 asr_stream.py：那个判据是相对本句峰值算的，增益低的
#    麦克风上"说了话"可能一直判不出来），没有实测就动它是拿"安静房间说半句话
#    被丢"去换"少聋 20 秒"。
WAKE_TIMEOUT_S = 6.0
# 念完之后压多久再恢复听 —— 等音箱余音散掉，见上面第 1 条
GUARD_S = 0.4
# 追问窗口（秒）：念完之后这么久之内，**不用再喊唤醒词**，接着说就接着答。
#
# ⚠️ 这个数是**人说话的空档**，不是机器的：主人听小瑞答完、想一下要说什么，
#    再开口。实测自己念一遍「主人，我在。有什么要我帮忙的？」那 2 秒里，
#    从"听完"到"开口"用掉 1.5~3 秒是常态，再算上一次没想好重说的余量。
#
# ★ 2026-09-26 用户拍板改成 **10 s，和"说完了"那条判据取同一个数**（原话：
#    「语音结束的标志是我中途 10s 没有发出声音」「否则可以一直说 一直对话」）。
#    这条现在管的是**对话什么时候结束**：主人连着说就一直在对话里，静默满
#    10 s 才回 IDLE（之后要再喊唤醒词）。原来取 8 的理由（"窗口开着的时候识别器
#    一直在吃音频，太长像一直开着的录音笔，还会把车里的闲聊收进来"）**依然成立**
#    —— 是用户拿"一直跟我对话"这个需求换掉了它，不是那个理由失效了。
FOLLOW_S = 10.0
# ⚠️ 这个数**不是**"进窗口 10 s 后就关"：主人一开口，窗口就不再按时钟收，
#    改由识别器那条 10 s 静音判据收口（见 `feed()` 里 FOLLOW 那一支的注释 ——
#    旧写法照挂钟收，追问窗口里永远接不住第二句，是个真 bug）。
# THINK 期间先攒着的音频留多久（秒），见文首第 6 条。
# ⚠️ 一次 DeepSeek 往返 ≈ 2.6 s，所以这个数只要盖得住 THINK 就够了；
#    留 5 s 是因为"答复来迟了"（模型超时/重试）也发生过，那时候主人早就
#    又说了一句，攒着的这段就是他唯一的机会。
THINK_PREROLL_S = 5.0
# 环形缓冲留多久：够装下唤醒词 + 紧跟的半句话
PREROLL_S = 2.0
# partial 文本推送的最小间隔（秒）—— 每个字都推会把页面刷爆
PARTIAL_EVERY_S = 0.25

IDLE, LISTEN, THINK, SPEAK, FOLLOW = "idle", "listen", "think", "speak", "follow"


class VoiceLoop:
    """状态机。`feed()` 是唯一入口，`answer_done()` 是外部把控制权还回来的地方。"""

    def __init__(self, cfg: dict | None = None, kws=None, asr=None, local=None):
        cfg = cfg or {}
        self.kws = kws if kws is not None else WakeWord(cfg.get("kws"))
        # 识别走哪条路由 `make_asr` 决定（流式的在了就用流式，没在就 whisper），
        # 反正接口一样，这里不关心是哪条。`local` 是服务端已有的那份 whisper。
        self.asr, self.asr_note = (asr, "注入的") if asr is not None \
            else make_asr(cfg, local=local)
        self.ring = RingBuffer(PREROLL_S, SR)
        # 见文首第 6 条：THINK 那几秒单独攒，和唤醒用的 `ring` **不是同一个**
        # —— 混在一起的话，唤醒时补喂的那一段会掺进小瑞答话之前的旧音频。
        self.think = RingBuffer(THINK_PREROLL_S, SR)
        # 追问窗口的长度。测试可以改小（它是**挂钟**计时，回放里挂钟是压缩的，
        # 等 8 秒真等不起 —— 见 `_check_voice_loop.py` D 段那条纪律）。
        self.follow_s = float(cfg.get("follow_s") or FOLLOW_S)
        self.state = IDLE
        self.wake_word = ""            # 这一次是被哪个词叫醒的
        self._t_wake = 0.0             # 唤醒时刻（用来判超时）
        self._t_follow = 0.0           # 进追问窗口的时刻（同为超时用，见 FOLLOW_S）
        self._t_partial = 0.0
        self._last_partial = ""
        self._n_wake = 0
        self._n_answer = 0
        self._guard_until = 0.0        # 这个时刻之前不喂 KWS（念完的余音）
        # ★ 轮次号：每交出去一条要回答的文本 +1。调用方拿它给"念完了"的看门狗
        #   定时 —— 见 `answer_done()` 的说明，**别用时间来认轮次**。
        self.round = 0
        # ★★ 2026-09-26：「小瑞在念的时候，主人喊唤醒词能不能把它打断」——
        #   见文首第 1 条。**默认 False**（= 原来那条半双工的行为），由调用方在
        #   **确认"这一句掐得断"之后**才置 True（`server.py` 广播 `ev:"reply"`
        #   之前；页面走兜底那条路会回一条 `{"type":"tts"}`，那边再置回 False）。
        #   ⚠️ 默认值必须是 False：这个开关的另一半是**"放开麦克风"**，忘设的
        #      后果是小瑞把自己的声音听成主人的话（没有 AEC），比"打断不了"坏得多。
        self.barge_in_ok = False

    def wake_words(self) -> tuple:
        """唤醒词的人类名字（`keywords.txt` 里 `@` 后面那一截）。

        ★ 给调用方一个**挡自激**的判据：哪一句答复里带唤醒词，那一轮就别开
          `barge_in_ok` —— 否则小瑞自己念出唤醒词就把自己叫醒了。
        ⚠️ 从 `kws` 现取，不在这儿另抄一份常量：唤醒词是在 `keywords.txt` 里
          改的，抄一份的结果是"改了唤醒词，这个挡板就失效了"（而且不报错）。
        ⚠️ 拿不到就回空元组（假 KWS 的测试会走到这条）——**空的意思是"没得挡"**，
          不是"全都挡"，所以调用方那边 `any(...)` 自然为假，行为退回默认的 False。
        """
        try:
            return tuple(self.kws.keywords or ())
        except Exception:                                # noqa: BLE001
            return ()

    # ---------------------------------------------------------------- 喂
    def _heard(self) -> bool:
        """这一句里**听到过人说话**没。两条识别路都报这个量（`asr_stream` 里）。

        ⚠️ 用 `getattr` 兜底，而且**兜成 True**：`asr` 是构造时注入的（测试和脚本
           会塞自己的假识别器进来），拿不到就当"听到了" —— 那样兜底超时只会晚一点
           收，不会把正在说话的主人从中间砍断。宁可多听，不可切话。
        """
        return bool(getattr(self.asr, "heard", True))

    def feed(self, samples) -> list[dict]:
        """喂一段实时音频（16 kHz 单声道 float32），返回**要给页面发的事件**。"""
        if samples is None or len(samples) == 0:
            return []
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        now = time.time()
        ev: list[dict] = []

        if self.state == SPEAK:
            # 见第 1 条：**ASR 一个字节都不进**（没有 AEC，它自己的声音会被当成
            # 主人的话）。但唤醒词那一层是开的 —— 主人喊一声就把它掐断、转过来听。
            if not self.barge_in_ok:
                return ev
            # 唤醒前那两秒要攒着：`_wake()` 会把它补喂给 ASR。SPEAK 期间原来
            # 连 `ring.push` 都没有（直接 return 在上面），现在补上 ——
            # 不攒的话主人说的"你好小瑞，给我…"那半句就只从唤醒词之后开始录。
            self.ring.push(x)
            for w in self.kws.feed(x):
                self._wake(w, ev, from_speak=True)
                break
            return ev
        if self.state == THINK:
            # 见文首第 6 条：只攒不识别（识别器刚 finalize 过，这是**新的一句**，
            # 现在喂进去会跟上一句的尾巴搅在一起）。等追问窗口开的时候补喂。
            self.think.push(x)
            return ev

        if self.state == IDLE:
            self.ring.push(x)                          # 见第 2 条：一直存着
            if now < self._guard_until:                # 见第 1 条：余音期不喂
                return ev
            for w in self.kws.feed(x):
                self._wake(w, ev)
                break
            return ev

        # LISTEN / FOLLOW：喂 ASR，边喂边把中间结果报出去
        # FOLLOW 和 LISTEN 就两处不同：**不用唤醒词**（进这个窗口本身就是
        # "小瑞刚答完、主人在接着说"），以及没人说话时会自己关（`follow_s`，
        # 现在和"说完了"那条判据是同一个数：10 s）。
        # ⚠️ FOLLOW 里**不喂 KWS**：识别器已经能听见全部，再喂一份是白算，
        #    而且"小瑞"两个字会被唤醒词再报一次（同一个句子叫醒两次）。
        self.ring.push(x)
        text = self.asr.feed(x)
        if text and text != self._last_partial and now - self._t_partial >= PARTIAL_EVERY_S:
            self._last_partial, self._t_partial = text, now
            ev.append({"type": "partial", "text": text})
        if self.asr.endpoint():
            ev.extend(self._finish())
        # ★★ 追问窗口到点收工。2026-09-26 补上的 `not self._heard()`，
        #    **它修的是一个真 bug**：
        #    「说完了」那条判据从 8 s 改成 10 s（用户拍板：「语音结束的标志是我
        #    中途 10s 没有发出声音」）之后，`follow_s` 和它变成了**同一个数**，
        #    于是追问窗口**必然在主人还在说话的时候关掉**：窗口是"进窗口那一刻起
        #    算 10 s"（挂钟），而收口是"最后一次出声之后再安静 10 s"。
        #    主人只要在窗口里开口（哪怕第 1 秒就说），收口最早也要等到第 11 秒——
        #    而窗口第 10 秒就关了、`_to_idle()` 把整句扔了。那正是用户要的那件事：
        #    「否则肯定一直跟我对话」—— 旧写法下**追问窗口里永远接不住第二句**，
        #    而速度比挂钟快的回放测不出来（`_check_voice_loop.py` 的 D 段一口气
        #    喂完，挂钟根本没走；是 `_check_voice_do.py` 按真实节拍喂才逮到的）。
        #    现在它和 LISTEN 那条一样**只在"一个字都没听到"时才收**（同一个
        #    `_heard()`，语义是"这一句里听见过人声"、进了就黏住），收口仍旧由
        #    识别器那条 10 s 静音判据决定 —— 一个数管两处。
        # ⚠️ 认的是 `_heard()` **不是** `partial` 文本：主人说得含糊时 partial 可能
        #    一直是空的，而"有没有人在说"这件事识别器自己有更硬的判据。
        # ⚠️ 兜底还在：真的一直有噪声灌进来，识别器自己的 `max_s`（299.5 s）会从
        #    时长那一条把句子收掉（见 `asr_stream.endpoint`），不会无限录下去。
        elif self.state == FOLLOW and not self._heard() \
                and now - self._t_follow > self.follow_s:
            # 这 10 秒里**一个字都没听到** —— 安安静静回 IDLE（`why` 留空：
            # 页面只在 `why` 非空时才 flash，这一条不是出错，没什么可报的）。
            # ⚠️ 识别器**必须清干净**：这 10 秒的静音全攒在它的缓冲里，
            #    不清的话下一句一开口就撞上"太长了"，整句被截掉。
            self._to_idle()
            ev.append({"type": "idle", "why": ""})
        elif self.state == LISTEN and not self._heard() \
                and now - self._t_wake > WAKE_TIMEOUT_S + 20.0:
            # 见 WAKE_TIMEOUT_S：最后一道保险。
            # ★ 2026-09-26 加了 `not self._heard()` —— 用户要的是「否则可以一直说
            #   一直对话」，那么**主人真的在说话时必须能一直说下去**。原来这一条不看
            #   有没有说话，到点就收：一口气说超过 26 s 的那句会被从中间砍断（用户
            #   报的正是这一类）。现在它只管"叫醒了、但一个字都没听到"（误唤醒、
            #   电视里的词、麦克风增益低到判不出说话）—— 那种情况识别器两条规则
            #   都不会出手，不兜底就是无限录下去。
            ev.extend(self._finish())
        return ev

    def finalize_text(self) -> list[dict]:
        """把这一句转成文字。**调用方负责把它放到线程里**（见 `_finish` 的说明）。"""
        text = self.asr.finalize() if self.asr.ready else ""
        self.state = THINK
        out = [{"type": "heard", "text": text}]
        if text:
            self._n_answer += 1
            self.round += 1
            out.append({"type": "need_answer", "text": text})
        else:
            # 为什么没出文字 —— **把识别那边给的原因带上**（`WhisperAsr.last_why`），
            # 别一律说"没听清"。"真的是静音"、"模型还没就绪"、"音频读不了"、
            # "识别那边抛错了"是四件要修的地方完全不同的事，而"没听清"这三个字
            # 会让人往**麦克风/环境**那个方向查，查半天查不到。
            # （浏览器那一路的自测就是这么栽的：服务端全绿、页面只显示"没听清"，
            #   真原因躺在 status() 里没人看 —— 正是"不报错的坏掉"。）
            why = getattr(self.asr, "last_why", "") or ""
            if not why:
                why = "没听清" if self.asr.ready else (self.asr.why or "识别模型不可用")
            self.state = IDLE
            self._guard_until = time.time() + GUARD_S
            out.append({"type": "idle", "why": why})
        return out

    # ---------------------------------------------------------------- 状态迁移
    def _wake(self, word: str, ev: list[dict], from_speak: bool = False) -> None:
        """叫醒了。`from_speak` = **这次是在小瑞念话的时候叫的**（要掐断它）。

        ⚠️ `from_speak` 是**在覆盖 `self.state` 之前**记下来的参数，不是进函数
           之后再判断 —— 这个函数第一件事就是把 state 改成 LISTEN，"原来在不在
           SPEAK"出了这个函数就再也看不出来了。调用方（`server.py`）靠它决定
           要不要先发一条 `ev:"halt"` 让页面把小瑞的话掐断。
        """
        was_speak = self.state == SPEAK or from_speak
        self.state = LISTEN
        self.wake_word = word
        self._t_wake = time.time()
        self._last_partial = ""
        self._n_wake += 1
        # 见文首第 1 条：这一轮是"掐断它的话"进来的，闸跟着关掉 —— 它的话已经被
        # 页面掐了，往后这几秒是主人在说，别再让下一句答复误以为闸还开着。
        self.barge_in_ok = False
        # 上一轮 THINK 攒下的那一段不能带进这一轮（见文首第 6 条）：
        # 它是**上一句话**的续集，混进来会让这一句开头多出半句不相干的话。
        self.think.take()
        ev.append({"type": "wake", "word": word, "asr_ready": self.asr.ready,
                   "asr_why": self.asr.why, "from_speak": was_speak})
        # 见第 2 条：把唤醒前那两秒补喂给 ASR —— 用户可能已经说了半句
        pre = self.ring.take()
        if len(pre) and self.asr.ready:
            t = self.asr.feed(pre)
            if t:
                self._last_partial = t
                ev.append({"type": "partial", "text": t})

    def _finish(self) -> list[dict]:
        """这一句说完了。

        ⚠️ **这里只发一个"该收尾了"的信号，不在这里转文字。** 因为转文字是
        **几百毫秒到两秒的阻塞调用**（whisper 整段式），而 `feed()` 是在 aiohttp
        的事件循环里被调的 —— 在这里直接调，这段时间**所有页面的状态推送、心跳
        全停**，表现是"说了一句话，整块屏幕卡住"（`ui/asr.py:787` 记过同一件事）。
        所以真正干活的 `finalize_text()` 由调用方放进线程池里跑，见 `ui/server.py`
        的 `{"type":"pcm"}` 那一段。
        """
        self.state = THINK
        return [{"type": "need_text"}]

    def expecting(self) -> None:
        """**小瑞马上要主动说一句**，把状态摆到"该说话了"那一档。

        ★★ 2026-09-26：给「跳过去 + 问一句」那条路用的（`ui/server.py` 的
        `voice_ask`）。这件事**不是**主人刚说完话来的，所以没有 `finalize_text()`
        替我们进 THINK —— 状态停在这一页刚 `voice_start` 之后的 IDLE 上。而
        `server.py` 的 `voice_say` 有一条**不能删**的守门（那一句答复可能是几秒前
        那一轮留下的，用户早按了停、页面早走了），它只在 `state == THINK` 时才肯
        念。所以这一趟必须自己把状态摆正，否则表现是"跳过去之后小瑞一个字都不说，
        气泡也是空的" —— 而且**不报任何错**。

        ⚠️ 只摆状态，**不碰 `round`**：这一句答复不属于新的一轮，它是**上一轮
           那句话的续集**（轮次号变了的话，页面念完带回来的 `voice_spoken` 会被
           卫兵当成过期的丢掉，追问窗口就永远开不了）。

        ⚠️ THINK 顺带把这几秒的音频从门口扔掉（见文首第 1 条那张表）—— 这正是
           要的：这几秒是页面在跳、小瑞还没开口，没有人在跟它说话。
        """
        self.state = THINK

    def speaking(self) -> None:
        """答复开始念了。进 SPEAK 之后**ASR 一个字节都不处理**（见第 1 条）。

        ⚠️ 这一步必须由调用方在**把答复发出去之前**调。漏掉的话小瑞一边念
        "小瑞在呢，主人"一边听自己念 —— 没有回声消除，这一句里只要沾上唤醒词
        就自激了。
        ★ 2026-09-26：现在 SPEAK 期间只跑**唤醒词检测**（KWS），ASR 仍然一个
          字节都不进 —— 而且 KWS 那一层还要 `barge_in_ok` 为真才开，见文首第 1 条
          和 `feed()` 的 SPEAK 那一支。**这个开关由调用方置**（`server.py` 在广播
          答复之前），这里不碰它。
        """
        self.state = SPEAK

    def answer_done(self, follow: bool = True) -> None:
        """外部念完了（TTS 播完），把控制权还回来。

        ⚠️ **这个信号不保证一定来**，调用方要自己架一道看门狗（`ui/server.py` 的
        `voice_answer` 里有），理由很具体：浏览器念不出来时会走服务端兜底
        （`live.js` 的 `XQ.tts._fallback` 往服务端发一条 `{"type":"tts"}`），
        而那条路**只报"排上队了"、不报"念完了"**（`ui/tts.py` 的 `say()` 注释里
        写明了）。所以"没收到回执"是正常会发生的事，不是异常 —— 状态机不能
        等一个可能永远不来的信号，否则表现就是**叫醒一次之后再也叫不醒**。

        ★ 2026-09-26：默认进的是 **FOLLOW（追问窗口）**而不是 IDLE，见文首那段 ——
        「你好小瑞」之后主人接着说的那句，原来就是在这儿被丢掉的。
        ⚠️ `follow=False` 是**给"其实不知道它闭没闭嘴"的那条路**留的：看门狗到点
        自己收尾时，没有任何证据说小瑞已经念完了，它很可能还在说话；这时候把
        麦克风放开（FOLLOW 是真的在喂识别器），它自己的声音就变成主人的话了
        （没有回声消除）。**依据是"知不知道它闭嘴了"，不是"谁调的"。**
        """
        if follow:
            self.state = FOLLOW
            self._t_follow = time.time()
            self._t_partial = 0.0
            self.wake_word = ""
            self._last_partial = ""
            # 见第 1 条：念完之后压一段，等余音散掉再恢复听
            self._guard_until = time.time() + GUARD_S
            self.kws.reset()
            # 见文首第 6 条：小瑞想的时候主人接着说的那半句，补喂进来当这一句的开头
            self._prime()
        else:
            self._to_idle()

    def _prime(self) -> None:
        """把 THINK 期间攒下的音频补喂给识别器（见文首第 6 条）。

        ⚠️ 只在 `asr.ready` 时喂：识别模型还没下来的时候喂进去就是白丢，
        留着反而占内存。取走即清空（`RingBuffer.take`），下一轮不会重喂。
        """
        pre = self.think.take()
        if len(pre) and self.asr is not None and self.asr.ready:
            self.asr.feed(pre)

    def _to_idle(self) -> None:
        """收工回 IDLE，**把识别器清干净**。

        ⚠️ 清识别器不是可选项：万一刚才那一整段是静音（追问窗口里没人说话），
        它会一直攒在识别器的缓冲里，下一句一开口就撞上"太长了"——整句被截。
        """
        self.state = IDLE
        self.wake_word = ""
        self._last_partial = ""
        self._t_follow = 0.0
        # 见第 1 条：闸跟着关掉。收工之后麦克风要重新变成"只认唤醒词"，
        # 留着一个 True 就是"下一轮答复还没开口，抢话的口子先开着"。
        self.barge_in_ok = False
        # 见第 1 条：念完之后压一段，等余音散掉再恢复听
        self._guard_until = time.time() + GUARD_S
        self.kws.reset()
        if self.asr is not None:
            self.asr.reset()

    def stop(self) -> None:
        """用户把耳朵关了（页面停止送音频）。**状态清干净**，下次点开是全新的。

        ⚠️ 不清环形缓冲的话，下次点开会把**上一回的**最后两秒当成本次的开头
        补喂给识别 —— 用户会看到小瑞答一句他刚才说过、但这次没说出口的话。
        """
        self.state = IDLE
        self.wake_word = ""
        self._last_partial = ""
        self._t_wake = 0.0
        self._t_follow = 0.0
        self._guard_until = 0.0
        self.barge_in_ok = False          # 见第 1 条（同上：闸跟着关）
        self.ring = RingBuffer(PREROLL_S, SR)
        self.think = RingBuffer(THINK_PREROLL_S, SR)   # 见第 6 条：同样是"上一回的"
        if self.asr is not None:
            self.asr.reset()
        if self.kws is not None:
            self.kws.reset()

    # ---------------------------------------------------------------- 报
    def status(self) -> dict:
        return {
            "state": self.state,
            "wake_word": self.wake_word,
            "wakes": self._n_wake,
            "answers": self._n_answer,
            "round": self.round,
            "follow_s": round(self.follow_s, 1),
            "preroll_ms": round(len(self.ring) / SR * 1000.0),
            # THINK 期间攒下的那一段（见文首第 6 条）—— 追问窗口开的时候它会归零。
            # 留着是给 `_check_voice_loop.py` 和排查用的：非 0 说明"主人抢在
            # 小瑞答话之前就把下一句说了"，那正是这套机制要捞回来的东西。
            "think_ms": round(len(self.think) / SR * 1000.0),
            # 见第 1 条：SPEAK 期间"抢话"这个口子现在开着没有。
            # 摆出来是给排查用的：用户报"它说话时我喊它不理"时，第一个要看的就是它
            # ——为假要么是这一句根本不是浏览器在念（兜底），要么是这句话里带了唤醒词。
            "barge_in_ok": self.barge_in_ok,
            "asr_ready": self.asr.ready,
            "kws": self.kws.status(),
            "asr": self.asr.status(),
        }
