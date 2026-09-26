# -*- coding: utf-8 -*-
"""流式语音识别：一边说一边出字，说完给整句。

    a = StreamAsr()
    a.feed(pcm16k)          # 说的时候一直喂，随时能读 a.text（还没说完的部分）
    a.finalize()            # 说完了，拿最终一句，然后这轮清空

用的是 sherpa-onnx 的**流式** zipformer（中文 int8，~133 MB）。为什么不用 whisper
（`ui/asr.py` 里那个）：whisper 是**整段**识别 —— 必须先把话录完、拿到完整音频才能
出字，中间一个字都看不到。这个助手要的是"说完就能答"，而且断句要靠静音实时判断，
所以必须是流式的。

⚠️ 三件事，都是真会咬人的：

  1. **模型文件名不写死，靠 glob 找。** sherpa 的包换版本就换文件名
     （int8/非 int8、epoch 号、chunk 参数…），写死一个名字，将来换个包就静默
     变成"不可用"。所以这里按特征找，找不到就把**目录里到底有什么**打出来。
  2. **断句（endpointing）的阈值是体验的核心**，不是技术细节：静音判太短，
     用户话没说完就被切断（尤其是"那个…""就是…"这种停顿）；判太长，用户说完
     要干等一会儿才等到答复。**2026-09-26 用户拍板取 10 s**（原话：「语音结束的
     标志是我中途 10s 没有发出声音」「否则可以一直说 一直对话」）—— 也就是
     **宁可等 10 s，也不许切主人的话**。之前那个 0.9 s 就是被他报"没说完就停"
     的原因。**这个数必须跟着实测调**，两条路各有一个（见 DEFAULTS 与 WhisperAsr）。
  3. **唤醒词本身也该喂给 ASR**。用户经常一口气说"你好小瑞我有点困" —— 唤醒的
     瞬间话已经说了一半。所以 `loop.py` 要留着唤醒前那一两秒的环形缓冲，
     命中后**先把缓冲里的补喂进来**，再接着喂实时的。这个模块提供 `RingBuffer`。
"""
from __future__ import annotations

import glob
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SR = 16000

# ★ 繁简归一：**流式这条路的出口也要用它一次**（见 `StreamAsr.text` 的注释）。
#   `ui/zh.py` 和 `ui/asr.py` 在同一个目录下；这里显式把那个目录塞进 `sys.path`，
#   和 `WhisperAsr.__init__` 里为了 `import asr` 做的是同一件事（它那份在下面，
#   **故意没删**：那一份是给 `import asr` 用的，两份都成立时不冲突）。
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from zh import zh_t2s                                        # noqa: E402

DEFAULTS = {
    "model_dir": None,          # 不填 = 自动找 models/sherpa/ 下的流式 ASR 模型
    "num_threads": 2,
    "decoding_method": "greedy_search",
    # ↓ 断句：静音多久算"说完了"。rule1 是"已经有字了，静音这么久就收"；
    #   rule2 是"一个字都还没出来，再等这么久就放弃"（用户可能只是清了清嗓子）。
    #
    # ★ 2026-09-26 用户拍板：「**语音结束的标志是我中途 10s 没有发出声音**」
    #   「否则可以一直说 一直对话」。这两个数原来分别是 0.9 / 1.6 —— 那是按
    #   "说完就赶紧答"定的（实测收口 0.84 s），代价是**话没说完就被切**：
    #   用户原话「为啥我说你好小瑞 它最长听我才 8s 不应该一直听吗」。
    #   ⚠️ 直接后果：**答复会比主人闭嘴晚 10 s 出来**（收口等待 0.84 s → 10 s）。
    #      这是这条判据本身的意思，不是 bug。嫌慢就把它和
    #      `whisper_silence_s`（whisper 那条路的同一个数）**一起**调小 ——
    #      两条路各有一个数，管的是同一件事，别只动一个。
    # ⚠️ 这两个数是**流式（sherpa）那条路**用的。本机流式模型没下（跑的是 whisper），
    #   所以 **10.0 这一对在流式那条路上没实测过** —— 写在这儿是为了别让"换了个
    #   引擎"顺手把判据换掉（`make_asr` 是自动选的，用户看不见用的哪条）。
    "rule1_min_trailing_silence": 10.0,
    "rule2_min_trailing_silence": 10.0,
    # ⚠️ rule3 **不是**"说多久算完"，是**安全阀**：攒到这么久必须收口，防的是
    #   "麦克风被卡住/一直有噪声"那种无限录下去。300 也是 sherpa-onnx 自己例子里的
    #   取值。真的判"说完"只看上面那两条静音规则。
    "rule3_min_utterance_length": 300.0,
    "hotwords": "",            # 可选热词表，逗号分隔（"导航,空调"），提高专有词命中
    "hotwords_score": 1.5,
}


def find_model_dir(cfg: dict | None = None) -> Path | None:
    """找流式 ASR 模型目录。按前缀找，不写死版本号。"""
    cfg = cfg or {}
    if cfg.get("model_dir"):
        p = Path(cfg["model_dir"])
        return p if p.is_absolute() else ROOT / p
    pats = ["sherpa-onnx-streaming-zipformer-zh-*",     # 默认下的这个（int8，133 MB）
            "sherpa-onnx-streaming-paraformer-*",       # 备选
            "sherpa-onnx-streaming-zipformer-small-*"]
    for pat in pats:
        hits = sorted(glob.glob(str(ROOT / "models" / "sherpa" / pat)))
        if hits:
            return Path(hits[-1])
    return None


class RingBuffer:
    """最近 N 秒的音频环形缓冲 —— 为了让唤醒词那一句也能进 ASR。

    用法：实时音频**一直往里丢**，唤醒命中时 `take()` 把最近的一段取出来，
    先补喂给 ASR，再接着喂实时的。这样"你好小瑞我有点困"这种一口气说的
    就能整句识别，用户不需要在唤醒词后面停一下。
    """

    def __init__(self, seconds: float = 2.0, sr: int = SR):
        self.n = int(seconds * sr)
        self._buf = np.zeros(0, dtype=np.float32)

    def push(self, x: np.ndarray) -> None:
        self._buf = np.concatenate([self._buf, np.asarray(x, dtype=np.float32).reshape(-1)])
        if len(self._buf) > self.n:                # 只留最近这一段
            self._buf = self._buf[-self.n:]

    def take(self) -> np.ndarray:
        """取走缓冲内容并清空（避免下一轮把同一段再喂一遍）。"""
        x, self._buf = self._buf, np.zeros(0, dtype=np.float32)
        return x

    def __len__(self) -> int:
        return len(self._buf)


class StreamAsr:
    """流式识别。`feed` 可以喂任意长度，内部自己按帧推。"""

    SR = SR

    def __init__(self, cfg: dict | None = None):
        c = dict(DEFAULTS)
        c.update(cfg or {})
        self.cfg = c
        self.ready = False
        self.why = ""
        self.model_dir = find_model_dir(c)
        self._rec = None
        self._stream = None
        self._n_final = 0
        self._last_ms = 0.0
        self._init()

    # ---------------------------------------------------------------- 建
    def _pick(self, *pats: str) -> Path | None:
        """按特征找文件。**每个 pat 是一串候选**，先 int8 后非 int8。"""
        for pat in pats:
            hits = sorted(self.model_dir.rglob(pat))
            if hits:
                return hits[-1]
        return None

    def _init(self):
        if self.model_dir is None or not self.model_dir.is_dir():
            self.why = ("没找到流式 ASR 模型 —— 先跑 "
                        "`python ui/voice/fetch_models.py asr`（133 MB）")
            print("[asr] " + self.why, file=sys.stderr)
            return
        try:
            import sherpa_onnx
        except Exception as e:
            self.why = "没装 sherpa-onnx：%s" % e
            print("[asr] " + self.why, file=sys.stderr)
            return

        tokens = self._pick("tokens.txt")
        # ⚠️ int8 优先：CPU 上快得多，中文短句场景精度损失可以忽略
        enc = self._pick("*encoder*int8*.onnx", "*encoder*.onnx")
        dec = self._pick("*decoder*int8*.onnx", "*decoder*.onnx")
        joi = self._pick("*joiner*int8*.onnx", "*joiner*.onnx")
        if not (tokens and enc and dec and joi):
            have = [p.name for p in sorted(self.model_dir.rglob("*.onnx"))][:12]
            self.why = ("模型包里缺文件（tokens=%s encoder=%s decoder=%s joiner=%s）；"
                        "目录里的 onnx 有：%s"
                        % (bool(tokens), bool(enc), bool(dec), bool(joi), have))
            print("[asr] " + self.why, file=sys.stderr)
            return

        kw = dict(tokens=str(tokens), encoder=str(enc), decoder=str(dec), joiner=str(joi),
                  num_threads=int(self.cfg["num_threads"]),
                  sample_rate=SR, feature_dim=80,
                  decoding_method=str(self.cfg["decoding_method"]),
                  enable_endpoint_detection=True,
                  rule1_min_trailing_silence=float(self.cfg["rule1_min_trailing_silence"]),
                  rule2_min_trailing_silence=float(self.cfg["rule2_min_trailing_silence"]),
                  rule3_min_utterance_length=float(self.cfg["rule3_min_utterance_length"]),
                  provider="cpu")
        hw = (self.cfg.get("hotwords") or "").strip()
        try:
            if hw:
                try:
                    self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(
                        hotwords=hw, hotwords_score=float(self.cfg["hotwords_score"]), **kw)
                except TypeError:
                    # 老版本没有热词参数 —— 别因为一个可选功能就整个不可用
                    print("[asr] 这版 sherpa-onnx 不支持热词，忽略 hotwords", file=sys.stderr)
                    self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(**kw)
            else:
                self._rec = sherpa_onnx.OnlineRecognizer.from_transducer(**kw)
        except AttributeError:
            self.why = ("sherpa-onnx 版本太老，没有 OnlineRecognizer.from_transducer"
                        "（装 1.10+：pip install -U sherpa-onnx）")
            print("[asr] " + self.why, file=sys.stderr)
            return
        except Exception as e:
            self.why = "建识别器失败：%s: %s" % (type(e).__name__, e)
            print("[asr] " + self.why, file=sys.stderr)
            return

        self._stream = self._rec.create_stream()
        self.ready = True
        print("[asr] 就绪：%s（%.1f MB）"
              % (self.model_dir.name,
                 sum(f.stat().st_size for f in self.model_dir.rglob("*.onnx")) / 1e6))

    # ---------------------------------------------------------------- 喂
    def feed(self, samples) -> str:
        """喂一段 16 kHz 单声道 float32，返回**到目前为止**的整句文本。"""
        if not self.ready or samples is None or len(samples) == 0:
            return self.text
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        t0 = time.perf_counter()
        self._stream.accept_waveform(SR, x)
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)
        self._last_ms = (time.perf_counter() - t0) * 1000.0
        return self.text

    @property
    def text(self) -> str:
        if not self.ready:
            return ""
        # ★ 2026-09-26：繁简归一**在这里**做（用户拍板「全部是简体中文」）。这里
        #   是流式那条路的**唯一出口** —— `feed()`（中间结果，页面上"正在听写"
        #   那几个字）和 `finalize()`（收尾那句）都是读这个属性，换在这儿两处
        #   一起生效，**不要在别处再换第二遍**。
        #   ⚠️ 流式那个模型（sherpa 中文 zipformer）本来就基本吐简体，这一行是
        #      **兜底**、是按"出口只允许简体"这条规矩写的，不是因为实测到它吐繁体。
        #      （whisper 那条路吐繁体是实测到的，它走的是 `ui/asr.py`。）
        return zh_t2s(self._rec.get_result(self._stream))

    def endpoint(self) -> bool:
        """静音够久，可以判定"这句说完了"。"""
        if not self.ready:
            return False
        return bool(self._rec.is_endpoint(self._stream))

    @property
    def heard(self) -> bool:
        """这一句里听到过人说话没。见 `WhisperAsr.heard`（`loop.py` 的兜底超时用）。"""
        return bool(self.text)

    def finalize(self) -> str:
        """收尾：把尾部音频推完，拿最终文本，然后清空等下一位用户。"""
        if not self.ready:
            return ""
        self._stream.input_finished()
        while self._rec.is_ready(self._stream):
            self._rec.decode_stream(self._stream)
        t = self.text.strip()
        if t:
            self._n_final += 1
        self.reset()
        return t

    def reset(self) -> None:
        """清空这一句的状态（**不是清空识别器**，下一句还能接着说）。"""
        if not self.ready:
            return
        fn = getattr(self._rec, "reset", None)
        if fn is not None:
            try:
                fn(self._stream)
                return
            except Exception:
                pass
        self._stream = self._rec.create_stream()

    # ---------------------------------------------------------------- 报
    def status(self) -> dict:
        return {
            "ready": self.ready,
            "why": self.why,
            "engine": "sherpa-onnx 流式 zipformer 中文 int8",
            "model": self.model_dir.name if self.model_dir else None,
            "sentences": self._n_final,
            "decode_ms_per_chunk": round(self._last_ms, 2),
            "endpoint_silence_s": self.cfg["rule1_min_trailing_silence"],
            "partial": True,
        }


# ============================================================================
# 整段式备路：whisper
# ============================================================================
# 为什么要有它：流式那个模型是 **133 MB，要联网下**，而这台机器到 GitHub 的连接
# 时通时不通（实测 WinError 10060）。whisper 的 `base.pt`（145 MB）**本机早就有**
# （`models/whisper/base.pt`，`ui/asr.py` 那条路用的），所以这一路**今天就能跑，
# 而且全离线**。代价很具体：whisper 是**整段**识别，出不了中间结果 —— 用户说完
# 之后要等 1~2 秒才出字，页面上看不到"正在听写"的效果。
#
# 所以策略是：**流式模型在了就用流式，没在就用 whisper**（`make_asr()` 里选）。
# 两条路实现同一个接口，`loop.py` 一行都不用改 —— 这就是当初定这个接口的用处。

class WhisperAsr:
    """把 `ui/asr.py` 的 `LocalAsr`（整段式）包成和 `StreamAsr` 一样的接口。

    ⚠️ 断句得自己来：whisper 不告诉你"说完了没有"。这里的判据是**相对这条麦克风
    自己听到的峰值**（跟 `ui/asr.py:quiet` 同一条理由 —— 不同机器的增益能差 30 dB，
    写死绝对阈值必然在别的机器上翻车）。

    ⚠️ **阈值的依据是实测，不是拍的**：`_scratch/_check_voice_loop.py --levels`
    会把样本音频的峰值/RMS 打出来。要改这几个数，先跑那个看真数。
    """

    SR = SR

    def __init__(self, cfg: dict | None = None, local=None):
        """`local` 可以传一个**已经在用的** `ui.asr.LocalAsr`。

        ⚠️ 服务端本来就有一个（`hub.asr`，给"语音输入"那条兜底路用的，启动时就把
        whisper 载进内存了）。**必须复用那一个** —— 再建一个就是**又一份 145 MB
        的内存**和又一遍十几秒的加载，而两份 whisper 在同一个进程里除了浪费没有
        任何好处（`ui/asr.py` 里连 torch 线程数都不敢动，就是因为这个进程里
        还有摄像头推理在跑）。
        """
        c = dict(DEFAULTS)
        c.update(cfg or {})
        self.cfg = c
        # ★ 静音多久算说完 —— 2026-09-26 用户拍板 **10 s**（见文件头第 2 条）：
        #   「语音结束的标志是我中途 10s 没有发出声音」「否则可以一直说 一直对话」。
        #   ⚠️ 它和 DEFAULTS 里那对 `ruleX_min_trailing_silence` 是**同一件事的
        #      两条路**：谁在跑就按谁算（`make_asr` 自动选，用户看不见用的哪条）。
        #      **改一个必须改另一个**，否则换台机器就换了判据。
        self.silence_s = float(c.get("whisper_silence_s", 10.0))   # 静音多久算说完
        self.min_speech_s = float(c.get("whisper_min_speech_s", 0.3))
        self.speech_peak = float(c.get("whisper_speech_peak", 0.02))  # 有说话的判据
        self.quiet_ratio = float(c.get("whisper_quiet_ratio", 0.10))
        self.buf: list[np.ndarray] = []
        self._peak = 0.0
        self._silent_s = 0.0
        self._speech_s = 0.0
        self._n_final = 0
        self._last_ms = 0
        self.last_why = ""          # 上一次 finalize 的说明（空串也可能是"真的没声音"）
        self._last_dur_s = 0.0
        self._dur_s = 0.0           # 这一句到现在攒了多久（只用来判"太长了"）
        self._over = False          # 这一句是被"太长了"截掉的（见 endpoint）
        self.last_over = False      # 上一句是不是被截的（status 里给外面看）
        self.why = ""
        self._reused = local is not None
        try:
            sys.path.insert(0, str(ROOT / "ui"))
            import asr as _asr_mod                      # ui/asr.py，不是本模块
            self._mod = _asr_mod
            self._local = local if local is not None else _asr_mod.LocalAsr(c.get("local"))
            if not self._local.ok() and self._local.loading:
                self.why = "whisper 模型正在后台加载…"
            elif not self._local.ok():
                self.why = "本地 whisper 不可用：" + self._local.engine()
            else:
                self.why = ""
        except Exception as e:
            self._mod = None
            self._local = None
            self.why = "拿不到 ui/asr.py 的本地 whisper：%s: %s" % (type(e).__name__, e)

        # ★ 单句上限（秒）—— **它不是"说多久算完"的判据，是安全阀**。
        #   判"说完"只看 `silence_s`（见 `endpoint()`）。这条线管的是另一件事：
        #   识别器收不下的音频是**整段拒收**，不是截断 ——
        #   `LocalAsr.transcribe` 里 `dur > max_s` 那一支直接返回空串 + 一句"太长了"，
        #   于是你说的一整句就这么没了。所以**攒到多长必须收口是识别器的属性**，
        #   不许在状态机里写死。写死过 26 s（`loop.py` 的兜底），而当时 whisper 的
        #   上限是 8 s，中间那 18 秒是**静默丢句**：浏览器那一路的自测就是这么栽的
        #   —— 真被叫醒了、真说了话，最后只得到一句 "太长了（26.2s，最多 8s）"。
        # ⚠️ 留 0.5 s 余量：`endpoint()` 是**喂完一片才问的**，最多超出一片左右。
        # ★ 2026-09-26「可以一直说」之后，`asr.max_s` 从 8 s 抬到 300 s，
        #   所以这条安全阀也一起到了 299.5 s —— 底下那个长度分支实际上只剩
        #   "麦克风卡住/一直有噪声"会碰到。**它响了就是有东西不对**：`status()`
        #   里的 `last_over` 为真、`last_over_s` 是它当时攒到的时长。
        cap = float(getattr(self._local, "max_s", 0) or 0)
        self.max_utterance_s = max(2.0, cap - 0.5) if cap > 0 \
            else float(c.get("whisper_max_utterance_s", 300.0))
        self._last_over_s = 0.0        # 上一次被安全阀截掉时攒了多久（status 里报）

    @property
    def ready(self) -> bool:
        # ⚠️ 模型是**后台线程**加载的（好几秒），所以这里要现问，不能缓存 ——
        #    缓存的话，服务刚起来那几秒会把唤醒后的第一句话丢掉。
        return bool(self._local is not None and self._local.ok())

    def feed(self, samples) -> str:
        """攒音频 + 判静音。**返回的一定是空串**：whisper 出不了中间结果。"""
        if samples is None or len(samples) == 0:
            return ""
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        self.buf.append(x)
        self._dur_s += len(x) / SR
        chunk_peak = float(np.abs(x).max()) if len(x) else 0.0
        self._peak = max(self._peak, chunk_peak)
        # 这一段算"有声"还是"静音"：相对本句到目前为止的峰值，见类注释
        loud = chunk_peak >= max(self.speech_peak, self._peak * self.quiet_ratio)
        if loud:
            self._speech_s += len(x) / SR
            self._silent_s = 0.0
        else:
            self._silent_s += len(x) / SR
        return ""

    @property
    def text(self) -> str:
        return ""                                      # 整段式，没有中间结果

    def endpoint(self) -> bool:
        """说完了没：有过足够的说话声 + 后面安静够了。

        ★ 2026-09-26 起，"说完了"的**唯一**判据是「静音够久」= `silence_s`（10 s，
          用户原话：「语音结束的标志是我中途 10s 没有发出声音」「否则可以一直说
          一直对话」）。原来这里是 0.9 s，那个数是按"说完赶紧答"定的，代价是
          话没说完就被切 —— 就是用户报的那件事。
        ⚠️ 长度那个分支**不是判据**，是安全阀（见 `__init__` 里 `max_utterance_s`
          的说明）。它响 = `status.last_over` 为真，正常使用里永远不该响。
        ⚠️ 长度那一支只在**已经听到说话**之后才截。纯静音那一支不能在这儿截：叫醒了
          没人说话是很常见的事，在这儿收口就变成一次次空的 finalize（每次都要跑一遍
          "太短了"的分支），该由 `loop.py` 的超时兜底去收。
        """
        if self._speech_s >= self.min_speech_s and self._dur_s >= self.max_utterance_s:
            self._over = True
            self._last_over_s = self._dur_s
            return True
        return (self._speech_s >= self.min_speech_s
                and self._silent_s >= self.silence_s)

    @property
    def heard(self) -> bool:
        """这一句里**有没有真的听到人说话**（不是"有没有出文字"）。

        `loop.py` 的兜底超时用它：叫醒了没人说话就该到点回 IDLE，而主人**真的在说**
        （只是还没停够 10 s）时**绝不能**被兜底砍掉 —— 那就是用户 2026-09-26 要的
        「可以一直说 一直对话」。whisper 这条路没有中间结果（`text` 恒为空串），
        所以只能报这一个量。
        """
        return self._speech_s >= self.min_speech_s

    def finalize(self) -> str:
        if not self.buf:
            return ""
        x = np.concatenate(self.buf)
        self.buf = []
        self._peak = self._silent_s = self._speech_s = 0.0
        self._dur_s = 0.0
        self.last_over = self._over          # 这一句是不是被"太长了"截的，见 status()
        self._over = False
        if not self.ready:
            return ""
        t0 = time.perf_counter()
        blob = self._mod._sine_wav(x)                  # 复用 ui/asr.py 的 wav 打包
        text, why = self._local.transcribe(blob)       # 空串 = 没听清，不编话
        self._last_ms = int((time.perf_counter() - t0) * 1000)
        # ⚠️ `why` **必须留着**：空串既可能是"真的是静音"，也可能是"音频读不了/
        #    模型没就绪/正在识别上一句"。把它吞掉，界面上就只能说"没听清" ——
        #    而那句话在"其实是我的代码坏了"的时候是在撒谎。这个模块的头号纪律
        #    就是不许不报错的坏掉，所以原因一律留在 status() 里给外面看。
        self.last_why = why
        self._last_dur_s = len(x) / SR
        if text:
            self._n_final += 1
        return text.strip()

    def reset(self) -> None:
        self.buf = []
        self._peak = self._silent_s = self._speech_s = 0.0
        self._dur_s = 0.0
        self._over = False

    def status(self) -> dict:
        return {
            "ready": self.ready,
            "why": self.why,
            "engine": "whisper base（整段式，全离线）",
            "model": getattr(self._local, "model_name", None),
            "reused": self._reused,        # 复用了服务端已有的那一份，没再建一个
            "sentences": self._n_final,
            "last_ms": self._last_ms,
            "last_why": self.last_why,         # 见 finalize：为什么没出文字
            "last_dur_s": round(self._last_dur_s, 2),
            # 单句上限（从 LocalAsr.max_s 推的，见 __init__）和上一句有没有被它截。
            # 这两个数**必须能看见**：上限比识别器实际能吃下的还长的话，
            # 表现是"说长句子就整句丢"，而界面上只会说"没听清"。
            # ⚠️ 它不是"说多久算完"（那是 `endpoint_silence_s`），是安全阀 ——
            #    `last_over` 为真就说明有人（或有什么东西）连着说了 299.5 s。
            "max_utterance_s": round(self.max_utterance_s, 2),
            "last_over": self.last_over,
            "last_over_s": round(self._last_over_s, 2),
            "heard": self.heard,
            "endpoint_silence_s": self.silence_s,
            "partial": False,                # 页面据此决定要不要显示"正在听写"
            "levels": {"peak": round(self._peak, 4), "speech_s": round(self._speech_s, 2),
                       "silent_s": round(self._silent_s, 2)},
        }


def make_asr(cfg: dict | None = None, local=None):
    """选一条能用的识别路：**流式的在就用流式，没在就用 whisper**。

    返回 (实例, 一句话说明)。实例的具体类型调用方不用关心 —— 两条路接口一样。
    `local` 传服务端已有的那个 `ui.asr.LocalAsr`，见 `WhisperAsr.__init__`。
    """
    c = (cfg or {}).get("asr") or {}
    prefer = str(c.get("prefer") or "stream")
    cands = [("stream", StreamAsr), ("whisper", WhisperAsr)] if prefer == "stream" \
        else [("whisper", WhisperAsr), ("stream", StreamAsr)]
    tried = []
    for name, cls in cands:
        obj = cls(c, local=local) if cls is WhisperAsr else cls(c)
        if getattr(obj, "ready", False):
            return obj, "%s 就绪" % name
        tried.append("%s 不可用（%s）" % (name, getattr(obj, "why", "") or "还没好"))
    # 两条都不行也得返回一个**能说话的**对象：它的 status() 里带着为什么，
    # 界面上就能如实说"识别没就绪"，而不是服务起不来。
    obj = WhisperAsr(c, local=local)
    return obj, "都不行：" + "；".join(tried)
