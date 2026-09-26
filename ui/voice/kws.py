# -*- coding: utf-8 -*-
"""唤醒词：常听「你好，小瑞」。离线、只认词、不看内容。

用的是 sherpa-onnx 的关键词检测（KWS）—— **不是** openWakeWord。理由很实在：
openWakeWord 官方那几个预训练模型全是英文（`hey_jarvis` 那一类），中文唤醒词
要自己训；而 sherpa-onnx 这个中文 KWS 模型是**现成的 3.3 MB**，建模单元是
拼音（声母 + 韵母），自定义唤醒词只要在 `keywords.txt` 里写一行拼音。

    n ǐ h ǎo x iǎo r uì @你好小瑞
    └ 你 ┘ └ 好 ┘ └ 小 ┘ └ 瑞 ┘     ← 声母 + 带声调的韵母，中间用空格分开

那行 `@` 后面是人类看的名字，检测出来就返回它。**每个 token 都必须在模型的
`tokens.txt` 里有**，写错了 sherpa 会在建实例时直接报错（不是静默失效），
所以改唤醒词之后跑一次 `_scratch/_check_wake.py` 就知道对不对。

⚠️ 三条纪律，都是这套东西实际会咬人的地方（前两条是实测出来的，不是照抄文档）：

  1. **音频必须是 16 kHz 单声道 float32 的流式小块**。这是模型本身的要求
     （它是个流式 zipformer），一次性丢一整段进去不成立。
  2. **`debounce_s` 是按挂钟时间算的，离线回放会把它变成陷阱**。回放 2 秒的文件
     只要几十毫秒，于是连着喂样本时后面那些全被前一次的窗口吃掉，症状是
     **一整场只报一个命中，而且总是第一个样本** —— 看起来像"检测器死了"。
     我为此白查了一轮（`_scratch/_wake_reset.py`），回放前调 `clear_debounce()`。
  3. **`num_trailing_blanks` 影响的是"什么时候报"，不是"报不报"**：实测 0 / 1 / 2
     三个值下三个正样本都命中，只是命中时刻从 1800 ms 变成 2100 ms。

它**只做唤醒**这一件事：听到词 → 返回一个字符串。放提示音、开录音、问模型、
说话，都是 `loop.py` 的事。
"""
from __future__ import annotations

import glob
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]          # dms_project
VOICE_DIR = Path(__file__).resolve().parent
SR = 16000                                          # 模型只吃这个采样率
FRAME = 1600                                        # 100 ms 一帧，喂的粒度

# 说话人换气/停顿多长算"一句完了"。KWS 靠尾部 blank 数判定，调大更稳但更迟。
DEFAULTS = {
    "model_dir": None,          # 不填 = 自动找 models/sherpa/ 下最新的那个 kws 模型
    "keywords_file": None,      # 不填 = ui/voice/keywords.txt
    "num_trailing_blanks": 1,
    "keywords_score": 1.0,
    "keywords_threshold": 0.25,
    # ⚠️ 同时搜索的关键词条数上限。**关键词比它多的时候要一起调大**，否则排在
    #   后面的词根本不会被搜到（症状是"加了词却没反应"）。默认 4 够单唤醒词用，
    #   做多方案对比时（_scratch/_wake_tokens.py）必须调大。
    "max_active_paths": 4,
    "num_threads": 2,
    # 命中后多久内的重复命中都算同一次。**这是按挂钟时间算的** —— 线上的音频是
    # 实时到的，一秒就是真的一秒；但**离线回放会把时间压扁**（2 秒的文件几十
    # 毫秒就喂完了），于是连着喂几个样本时，后面那些全都落在前一次的窗口里被
    # 吃掉，看起来就像"检测器死了"。离线回放前记得 `clear_debounce()`。
    "debounce_s": 1.0,
}


def find_model_dir(cfg: dict | None = None) -> Path | None:
    """找模型目录。按**目录名前缀**找而不是写死版本号 —— 换模型版本时不用改代码。"""
    cfg = cfg or {}
    if cfg.get("model_dir"):
        p = Path(cfg["model_dir"])
        return p if p.is_absolute() else ROOT / p
    hits = sorted(glob.glob(str(ROOT / "models" / "sherpa" / "sherpa-onnx-kws-*")))
    return Path(hits[-1]) if hits else None


class WakeWord:
    """常听唤醒词。用法：

        w = WakeWord(cfg)          # 建实例 = 加载模型（几十毫秒，3.3 MB）
        w.ready                    # 能不能用
        for d in w.feed(pcm16k):   # 一小段一小段喂
            print('叫醒了：', d)

    `feed` 只收 16 kHz 单声道 float32（范围 -1~1），长度随意，内部按 100 ms 切。
    """

    SR = SR

    def __init__(self, cfg: dict | None = None):
        c = dict(DEFAULTS)
        c.update(cfg or {})
        self.cfg = c
        self.ready = False
        self.why = ""               # 不能用的时候，一句话说清原因
        self.model_dir = find_model_dir(c)
        self.keywords_file = Path(c["keywords_file"]) if c.get("keywords_file") \
            else VOICE_DIR / "keywords.txt"
        self.keywords: list[str] = []
        self._n_hit = 0
        self._last_hit: dict[str, float] = {}
        self._last_ms = 0.0         # 上一帧解码花了多久（CPU 预算的实测值）
        self._feed_ms = 0.0         # 喂进去的音频总时长
        self._kws = None
        self._stream = None
        self._reset_stream = None   # 1.13 是 reset_stream(stream)，兼容旧写法
        self._init()

    # ---------------------------------------------------------------- 建
    def _init(self):
        if self.model_dir is None or not self.model_dir.is_dir():
            self.why = ("没找到 KWS 模型 —— 先跑 `python ui/voice/fetch_models.py kws`"
                        "（32 MB，下到 models/sherpa/）")
            print("[kws] " + self.why, file=sys.stderr)
            return
        if not self.keywords_file.exists():
            self.why = "没有 %s —— 唤醒词表就写在这里面" % self.keywords_file
            print("[kws] " + self.why, file=sys.stderr)
            return
        self.keywords = [ln.split("@")[-1].strip()
                         for ln in self.keywords_file.read_text(encoding="utf-8").splitlines()
                         if ln.strip() and not ln.lstrip().startswith("#")]
        try:
            import sherpa_onnx
        except Exception as e:
            self.why = "没装 sherpa-onnx（pip install sherpa-onnx）：%s" % e
            print("[kws] " + self.why, file=sys.stderr)
            return
        try:
            self._kws = self._build(sherpa_onnx)
            self._stream = self._kws.create_stream()
        except Exception as e:
            self.why = ("建 KWS 实例失败：%s: %s（多半是 keywords.txt 里的拼音"
                        "在 tokens.txt 里没有）" % (type(e).__name__, e))
            print("[kws] " + self.why, file=sys.stderr)
            return
        self._reset_stream = getattr(self._kws, "reset_stream", None)
        self.ready = True
        print("[kws] 就绪：%s  唤醒词 %s" % (self.model_dir.name, self.keywords))

    def _build(self, sherpa_onnx):
        d = self.model_dir
        # ⚠️ 认 int8 那一套：模型包里有 epoch-12 和 epoch-99 两版，取 **epoch-99**
        #   （官方推荐的那版，epoch 数多 = 训得久），而且用 int8 —— CPU 上快得多，
        #   3.3 M 这么小的模型量化掉的那点精度本来也无所谓。
        def one(pat: str) -> str:
            hits = sorted(d.glob(pat))
            if not hits:
                raise FileNotFoundError("模型包里没有 %s" % pat)
            return str(hits[-1])

        kw = dict(
            tokens=str(d / "tokens.txt"),
            encoder=one("encoder-epoch-99-avg-1-chunk-16-left-64.int8.onnx"),
            decoder=one("decoder-epoch-99-avg-1-chunk-16-left-64.int8.onnx"),
            joiner=one("joiner-epoch-99-avg-1-chunk-16-left-64.int8.onnx"),
            num_threads=int(self.cfg["num_threads"]),
            keywords_score=float(self.cfg["keywords_score"]),
            keywords_threshold=float(self.cfg["keywords_threshold"]),
            num_trailing_blanks=int(self.cfg["num_trailing_blanks"]),
            max_active_paths=int(self.cfg["max_active_paths"]),
            provider="cpu",
        )
        try:
            return sherpa_onnx.KeywordSpotter(keywords_file=str(self.keywords_file), **kw)
        except TypeError:
            # 老一点的版本只认 keywords_buf（直接给内容）。
            buf = "\n".join(ln for ln in self.keywords_file.read_text(
                encoding="utf-8").splitlines() if ln.strip())
            return sherpa_onnx.KeywordSpotter(keywords_buf=buf, **kw)

    # ---------------------------------------------------------------- 喂
    def feed(self, samples: np.ndarray) -> list[str]:
        """喂一段 16 kHz 单声道 float32，返回这一段里**新**命中的唤醒词。"""
        if not self.ready or samples is None or len(samples) == 0:
            return []
        x = np.asarray(samples, dtype=np.float32).reshape(-1)
        out: list[str] = []
        nfr = 0
        t0 = time.perf_counter()
        for i in range(0, len(x), FRAME):
            nfr += 1
            self._stream.accept_waveform(SR, x[i:i + FRAME])
            while self._kws.is_ready(self._stream):
                self._kws.decode_stream(self._stream)
            r = self._kws.get_result(self._stream)
            if r:
                now = time.time()
                if now - self._last_hit.get(r, -1e9) >= float(self.cfg["debounce_s"]):
                    self._last_hit[r] = now
                    out.append(r)
                    self._n_hit += 1
                self.reset()
        # 摊到每一帧上报 —— 这才是"常听占多少 CPU"能直接比的那个数
        self._last_ms = (time.perf_counter() - t0) * 1000.0 / max(nfr, 1)
        self._feed_ms += len(x) / SR * 1000.0
        return out

    def reset(self) -> None:
        """把流清干净，下一次命中从新的一页开始算。

        实测（`_scratch/_wake_reset.py`）：**不调它也不会重复报** —— 一条流连续喂
        同一句话三遍，三遍各报一次，时间点分别是 1800/2000/1900 ms，干净得很。
        所以它的作用是"别让上一句的尾部状态影响下一句"，不是"防重复报"（防重复
        是 `debounce_s` 的活）。命中后顺手清一下，代价是零（换一条流）。
        """
        if self._kws is None or self._stream is None:
            return
        if self._reset_stream is not None:
            try:
                self._reset_stream(self._stream)
                return
            except Exception:
                pass
        self._stream = self._kws.create_stream()

    def clear_debounce(self) -> None:
        """清掉去抖记录 —— **离线回放（喂文件）之前必须调**。

        线上音频是实时到的，去抖窗口 1 s 就是真的一秒；回放是把 2 秒的文件几十
        毫秒喂完，时间被压扁，于是"上一个样本刚命中"这件事会一直挡着后面的样本，
        症状是：**一整场只有一个命中，还总是第一个样本**。这个坑我踩过一整轮
        （见 `_scratch/_wake_reset.py` 开头那段），所以做成一个显式的方法，
        别让测试去戳私有字段。
        """
        self._last_hit.clear()

    # ---------------------------------------------------------------- 报
    def status(self) -> dict:
        return {
            "ready": self.ready,
            "why": self.why,
            "engine": "sherpa-onnx KWS · zipformer wenetspeech 3.3M · 离线",
            "model": self.model_dir.name if self.model_dir else None,
            "keywords": list(self.keywords),
            "hits": self._n_hit,
            # 每 100 ms 一帧的解码耗时 —— 这就是"常听"要占的 CPU，实测值
            "decode_ms_per_frame": round(self._last_ms, 2),
        }
