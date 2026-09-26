"""本地语音识别 —— 「语音输入」的兜底那一路。

主路是**浏览器**的 `SpeechRecognition`（见 `ui/web/live.js` 的 `XQ.asr`）：Edge 上
零安装、走系统语音服务、说三五个字也就几百毫秒。这一侧只在浏览器那条路走不通时
登场，而它走不通的样子很具体：**没有麦克风权限 / kiosk 里整个 API 不可用 / 断网**。

⚠️ 和 `ui/tts.py` 是**同一个形状但不是同一套判据**，别想着抽公共框架：
  · TTS 判「有没有开口」—— 浏览器念不出来才轮到服务端，**两件事不排斥**（兜底
    本来就是"主路没成"之后的动作）。
  · ASR 判「有没有出文本」—— 两条路**恰好交付一条**，而且**不允许并行**：两条都
    出结果就是同一次说话被识别两遍、小瑞答两遍。
`ui/tts.py:14-16` 已经就"为什么不复用 `src/live.py` 的 TTSWorker"讲过同一条道理。

⚠️ **为什么录在浏览器侧、不在这边 `sounddevice`**（按重要性）：
  1. 「停」必须由页面自己掌握。服务端录音时 WS 一断，PortAudio 的流还开着 ——
     麦克风灯亮着，而界面已经不认它了。本项目在摄像头上踩过"不 release 就换不了"。
  2. 服务端录音要在 Hub 上挂 per-socket 状态，而**两个页面都有 mic 按钮**；
     `POST` 是无状态的，与这个形状天然合拍。
  3. `cam` 模式下这个进程的 CPU 已经满载，PortAudio 回调挤进来会让录音带咔哒声。
  4. 服务端录音会把"能不能录"藏进黑盒：Windows 关了麦克风权限时 PortAudio
     拿到的是**全零音轨且不报错** —— 又是一次"不报错的坏掉"。
浏览器侧直接 `AudioContext({sampleRate:16000})` 让浏览器重采样，JS 一行重采样都不用写。

⚠️ **绕开 ffmpeg 是真的，不是照文档推的**：`whisper.transcribe(ndarray)` 把音频原样
交给 `log_mel_spectrogram`，而后者**只在 `isinstance(audio, str)` 时才进 `load_audio`**
（`whisper/transcribe.py` 里 `load_audio` 也只在 `load_model` 之后被那个分支调到）。
这份仓库里 `shutil.which("ffmpeg")` 是 None，所以这一条要能被自动验 —— 见
`_scratch/_check_asr.py`（它还做了反向对照：把同一个 WAV 交给 `whisper.audio.load_audio`
**必须抛异常**，证明"我们绕开它"有意义，而不是"这台机器本来不需要绕"）。

⚠️ **三个全是"不报错"的陷阱**，`wav_bytes_to_float32` 就是为它们存在的：
  1. int16 数组直接喂进去 → `torch.stft` 抛 `NotImplementedError`，报错里**根本没提**
     "你要转成 float32"。
  2. **忘了除 32768.0** → 波形被整体当成 ±3 万倍的信号 → 削顶噪声 → 识别成胡话。
     不抛任何异常。
  3. **44.1k 当成 16k**：whisper 内部**既没有重采样也没有任何采样率检查**，它只会
     按 16k 去理解那串样本 → 放慢 2.76 倍 → 还是胡话。也不抛异常。
一行搞定，但这行必须只有一处：`np.frombuffer(b, np.int16).astype(np.float32) / 32768.0`。

⚠️ **这个模块永远不下载模型。** `whisper.load_model` 在本地没有 `base.pt` 时会自己去
`openaipublic.azureedge.net` 拉，还带一个 tqdm 进度条打到黑框里 —— 那是现场最难看的
失败方式。所以本地文件不存在时**连 `load_model` 都不调**，直接如实报"没装"，
出路交给 `双击 ui\\install_asr.bat`。下载只发生在那个 bat 里。

⚠️ **不碰 `torch.set_num_threads`。** 这个进程里还有 `cam.py` 的推理在跑，而 torch 的
线程数是**进程级**的：为了让识别温柔一点去调它，代价是**换掉 cam 模式的推理速度** ——
那正是答辩现场最不能动的东西。识别慢一点可以忍，cam 掉帧不能。
"""

from __future__ import annotations

import io
import sys
import threading
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent

# ★ 繁简归一那张表在**同目录的 `ui/zh.py`**（2026-09-26 从 `ui/xiaorui.py` 搬过去的，
#   见那个文件开头）。本模块在识别器出口用它一次，见 `transcribe` 里那一行。
#   ⚠️ 能 `import asr` 就一定能 `import zh` —— 两者都在 `ui/` 下，调用方都是先把
#      `ui/` 塞进 `sys.path` 再 import 的（`ui/server.py`、`ui/voice/asr_stream.py`、
#      `_scratch/` 里那一串）。**别改成相对导入**：本模块是被当顶层模块用的。
from zh import zh_t2s                                        # noqa: E402

# 浏览器侧就是按这个采样率录的（`AudioContext({sampleRate:16000})`）。
# whisper 内部认死 16000，别改。
SR = 16000

DEFAULT_MODEL = "base"
# `tiny` 的中文错得离谱（把"我有点困"听成别的），`small` 在 CPU 上要 3~5 秒，
# 现场会被当成卡死。`base` 142 MB / 5 秒音频约 1.5 秒，是这三者里唯一能用的。
# 想换就改配置里的 `asr.model`，但改之前跑 `python ui/asr.py --bench` 看本机真实秒数 ——
# 别拿文档里的形容词当依据。
MODEL_DIR = ROOT / "models" / "whisper"

# 下限：短于这个时长的音频直接不当它是话（多半是误触/点错）。
DEFAULT_MIN_S = 0.4
# 上限（秒）：**识别器能吃多长的音频**。transcribe 里超过它就是**整段拒收**
# （见那边 `dur > self.max_s` 那一支）。
#
# ★ 2026-09-26 用户拍板「可以一直说 一直对话」之后，从 8 s 抬到 300 s。
#   为什么必须抬：常听那条路（`ui/voice/asr_stream.WhisperAsr`）把"单句上限"
#   从**这个数**推出来（`asr.max_s − 0.5`），所以 max_s 是 8 的时候，主人一说
#   超过 7.5 s，整句就被它先收口 —— 那正是用户报的「它最长听我才 8s」。
# ⚠️ 300 s 是**安全阀**，不是"说多久算完"（判说完只看静音，见 `asr_stream.py`）。
#   300 s = 9.6 MB 的 WAV，whisper 整段式在 CPU 上要跑 10 个 30 s 窗口（十几秒）
#   —— 正常演示里永远到不了，到了也说明麦克风被卡住了。
# ⚠️ 它**不管**浏览器那条路能录多久：语音输入是把整段 WAV 一次性 POST 上来的，
#   上限由 HTTP 那一层定（aiohttp `client_max_size` 默认 1 MB ≈ 31 s，
#   见 `ui/web/live.js` 的 `ASR_REC_MAX_S` 和 `server.py` 里那道 Content-Length
#   闸门）。**别拿 max_s 当录音时长的设定值**，那样录满 300 s 就是 9.6 MB 的 413。
DEFAULT_MAX_S = 300.0
# 浏览器那条路的起步探测窗口（毫秒）。它探的是 onstart/onaudiostart 这类**起步事件**
# —— 正常 100 ms 内就到，所以这个数可以小；小才要紧，因为窗口里说的话是丢的
# （浏览器那条路证明不行之后，本地那条路才从头开始录）。
DEFAULT_FIRST_MS = 900

# 服务端插件的安装出路。**这个字符串里的路径必须和实际文件名一致** ——
# 界面上写着一条不存在的命令，是演示现场最尴尬的失败（见 install_asr.bat）。
INSTALL_HINT = "双击 ui\\install_asr.bat 装本地识别（要联网下 142 MB 模型）"

# ★ whisper 的**简体中文提示**（`initial_prompt`）。2026-09-26 用户拍板「全部是简体
#   中文」之后加的，**这是那一件事的主路**（`zh_t2s` 只是兜底，见 `ui/zh.py`）。
#
# 为什么必须有它：whisper 是多语种模型，**简繁两套字形都在它的词表里**，而
# `language="zh"` 只钉住"说中文"，**不区分简繁** —— 不给提示，它就按训练语料里
# 那边多往那边写，于是同一句普通话**有时简体有时繁体**（本机实测到过
# 「你好小瑞給我放客音樂」）。`initial_prompt` 是拿一段文本当**解码器的前缀**，
# 模型会顺着它的字形往下写，所以**这段提示里的字必须是简体的**：它是什么字形，
# 输出就跟着什么字形。
#
# ⚠️ **它为什么是这个形状 —— 量出来的，不是挑出来的**。第一版写的是
#    「请用简体中文转写。你好小瑞，给我放个音乐，导航到最近的服务区，我有点困了。」
#    （一句 meta + 一句"主人会说的话"），想法是顺便把「导航/服务区/音乐」这几个
#    字的字形也钉住。**结果它泄漏**：whisper 把提示当成"前面已经说过的话"往下接，
#    于是「给我放个音乐」那句的识别结果尾巴上多出一个「导航」，**「打开多媒体」
#    那句也多了「导航」** —— 泄漏出来的偏偏是**动作词**，一句"放音乐"会真的跳去
#    导航页（`detect_action` 的 ①b 认「导航」）。所以那句例句**必须删掉**。
#    `_scratch/_probe_asr_zh.py` 拿 9 段真音频 × 5 版候选量过（结果在
#    `runs/_probe_asr_zh.txt`）：带例句那版 繁体 0/9 但**泄漏 1**；下面这一版
#    繁体 0/9、泄漏 0、该认的认出来 8/9（和不发提示的基线一样多）。
#    ⚠️ 「请用简体中文。」四个字那版也是 0 繁体 0 泄漏，但**认对掉到 7/9**
#    （「你好小瑞」被听成「尼好小锐」）—— 太短的提示会把别的东西也带跑。**别改成它。**
# ⚠️ 提示词还可能被模型**自己念出来**（近乎静音的片段）。这里不怕：`transcribe` 进
#    whisper 之前先过 `quiet()`，全静的段根本不进来。
SIMPLIFIED_PROMPT = "以下是普通话的简体中文转写。"


# ---------------------------------------------------------------- WAV → float32
def wav_bytes_to_float32(blob: bytes, want_sr: int = SR) -> np.ndarray:
    """WAV 字节 → 单声道 float32(-1~1) @ `want_sr`。

    用标准库 `wave` 解析而**不是** `blob[44:]` 硬切：44 字节只是最常见的那个
    canonical 头，多一个 `LIST`/`fact` 块就整体错位，而错位之后喂给 whisper
    仍然是"一段能跑完的音频"——只会识别成胡话，不报错。

    返回的一定是 **1 维 float32**：立体声取平均，采样率不是 16000 就用
    `scipy.signal.resample_poly` 重采样（本机 scipy 1.15.3 在，不为这个自己写算法）。
    这两条都是"宁可修好也不悄悄按错的来"——见文件头那三个陷阱。
    """
    with wave.open(io.BytesIO(blob), "rb") as w:
        nch, width, sr, n = (w.getnchannels(), w.getsampwidth(),
                             w.getframerate(), w.getnframes())
        raw = w.readframes(n)
    if width == 1:
        # 8 bit WAV 是无符号的，中点 128。浏览器那条路不会产生它，但别人用
        # 别的工具切一段丢过来就会，而"当成有符号读"会把波形整个翻个面。
        x = (np.frombuffer(raw, np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 2:
        x = np.frombuffer(raw, "<i2").astype(np.float32) / 32768.0
    elif width == 4:
        x = np.frombuffer(raw, "<i4").astype(np.float32) / 2147483648.0
    else:
        raise ValueError(f"不认识的位深 {width * 8} bit")
    if nch > 1:
        x = x.reshape(-1, nch).mean(axis=1)      # 双声道 → 单声道
    if sr != want_sr:
        from math import gcd
        from scipy.signal import resample_poly
        g = gcd(int(sr), int(want_sr))
        x = resample_poly(x, want_sr // g, int(sr) // g).astype(np.float32)
    return np.ascontiguousarray(x, dtype=np.float32)


def level(x: np.ndarray) -> tuple[float, float]:
    """(峰值, RMS)。静音守卫的判据用它们算，别写绝对阈值 ——
    不同笔记本麦克风增益能差 30 dB，写死的数在别人的机器上必然翻车。"""
    if not len(x):
        return 0.0, 0.0
    a = np.abs(x)
    return float(a.max()), float(np.sqrt(np.mean(np.square(x, dtype=np.float64))))


def quiet(x: np.ndarray) -> bool:
    """这段是不是"基本没声音"。

    判据是**相对这一段自己的峰值**取比例（`max(0.004, 峰值*0.06)`），不是绝对阈值。
    目的是挡住"整段都是底噪、末尾有一声鼠标响"那种输入 —— 它的峰值不低（过得了
    `min_s`），但 RMS 相对峰值极小。whisper 对这类输入会**自信地输出一段不存在的话**
    （中文最常见「谢谢观看」），所以要在它开口之前就拦掉。

    ⚠️ 它判的是**整段的平均**，所以**必须先掐掉头尾的静音再调**（见 `trim_silence`）
    —— 直接拿"话 + 10 s 判据留下的静音"来判，就是"话越短越听不见"。
    """
    peak, rms = level(x)
    return rms < max(0.004, peak * 0.06)


# 掐头去尾用的分帧长度（毫秒）。20 ms 一帧：语音的起止沿在几十毫秒量级，
# 再细等于拿单个采样点去判（底噪会把它骗过去），再粗会把短促的字头一起掐掉。
TRIM_FRAME_MS = 20
# 掐完之后头尾**各留这么长**的余量（秒）。不留的话正好从阈值边界上切过去，
# 字头/字尾那几毫秒会被削掉 —— whisper 对削掉的字头很敏感。
TRIM_PAD_S = 0.10


def trim_silence(x: np.ndarray) -> np.ndarray:
    """掐掉**头尾**的准静音，只留中间那一段。掐掉的不进 whisper，也不参与判据。

    ★ 2026-09-26 为什么必须有这个函数（**实测逮到的**，不是防患于未然）：
      "说完了"的判据改成「静音满 10 s」之后，送进识别器的**每一段音频结尾都必然
      拖着约 10 s 静音** —— 那是判据本身造成的，不是异常。而 `quiet()` 拿的是
      **整段**的 RMS 去比"整段峰值 × 0.06"：拖 10 s 静音会把整段 RMS 拉下去，于是

        · 说一句 2.5 s 的话（"你好小瑞，我有点困"）→ 整段 RMS 0.023 < 0.038
          → **判成"基本没听到声音"**，主人说什么都听不见；
        · 说 15 s 的话就刚好过线（0.040 > 0.038）。

      也就是**话越短越听不见**，而"长话能听见"会让人以为是别的原因 ——
      这是最难查的那种坏法。`_scratch/_check_voice_loop.py` 的 B/D/G 三段一起变红
      才把它顶出来（报告只写"基本没听到声音"，一句都不提"因为尾巴太长"）。
      ↳ 根因是判据建在"整段的平均"上。掐掉头尾之后，`min_s`/`max_s`/`quiet`
        三条判的都是**真正的那一段话**，而不是"话 + 判据留下的静音"。
        顺带 whisper 也少跑那 10 s（整段式，CPU 耗时随秒数线性涨）。

    ⚠️ 只掐**头尾**：句子**中间**的停顿（"你好，小瑞，我有点困"里那两个）一个字都
      不许动 —— 它们也是话的一部分，掐了就是把一句话切成两半。
    ⚠️ 判据和 `quiet()` **同一个**（`max(0.004, 峰值 × 0.06)`），不另拍一个：
      两处口径不同就会出现"把安静的部分留下、然后整段被判成没声音"这种自相矛盾。
    ⚠️ 整段都没超过阈值时**原样返回**，不自作主张返回空数组 —— 那句话该由
      `quiet()` 去说（"基本没听到声音"比"太短了（0.0s）"更像人话）。
    """
    if not len(x):
        return x
    f = max(1, int(SR * TRIM_FRAME_MS / 1000))
    n = len(x) // f
    if n < 3:                 # 比一帧还短：不折腾，交给后面的 min_s 去照实报
        return x
    fr = x[:n * f].reshape(n, f)
    rms = np.sqrt(np.mean(np.square(fr, dtype=np.float64), axis=1))
    peak = float(np.abs(x).max())
    loud = np.nonzero(rms >= max(0.004, peak * 0.06))[0]
    if not len(loud):
        return x
    pad = int(SR * TRIM_PAD_S)
    a = max(0, int(loud[0]) * f - pad)
    b = min(len(x), (int(loud[-1]) + 1) * f + pad)
    return x[a:b]


# ---------------------------------------------------------------- 引擎
class LocalAsr:
    """本地 whisper。**绝不阻塞事件循环**、**绝不下载模型**。"""

    def __init__(self, cfg: dict | None = None):
        # `cfg` 传的是 config.json 里整个 `asr` 段。
        c = cfg if isinstance(cfg, dict) else {}
        self.enabled = bool(c.get("enabled", True))
        self.model_name = str(c.get("model") or DEFAULT_MODEL)
        self.language = str(c.get("language") or "zh")
        self.prefer = str(c.get("prefer") or "browser")
        try:
            self.min_s = float(c.get("min_s", DEFAULT_MIN_S))
        except (TypeError, ValueError):
            self.min_s = DEFAULT_MIN_S
        try:
            self.max_s = float(c.get("max_s", DEFAULT_MAX_S))
        except (TypeError, ValueError):
            self.max_s = DEFAULT_MAX_S
        # 浏览器那条路的"到底动没动"探测窗口（毫秒），前端用。
        # ⚠️ 它**不该调大**：探的是 onstart 这类起步事件（正常 100 ms 内就到），
        # 窗口开到几秒的话，浏览器真不行的时候用户就得干等几秒才轮到本地那条路。
        try:
            self.first_ms = int(c.get("first_ms", DEFAULT_FIRST_MS))
        except (TypeError, ValueError):
            self.first_ms = DEFAULT_FIRST_MS
        preload = bool(c.get("preload", True))

        self.model = None
        self.load_s: float | None = None
        self.last_ms: int | None = None
        self.last_text = ""
        self.count = 0
        self.error = ""
        # ⚠️ 只导一次。`whisper` 会把 torch 拉起来（好几秒），demo/replay 用不上它。
        self._whisper = None
        self._import_err = ""
        self._whisper = self._try_import()

        # ⚠️ `blocking=False`：拿不到锁就**立刻**回一句"正在识别"，不排队。
        # 界面上的 busy 只管得住自己那一页，而两个页面连的是同一个 hub ——
        # 排队会让第二次点击看起来像卡住（其实是在等前一次）。
        self.lock = threading.Lock()
        self.busy = False
        self.loading = False
        self._thread: threading.Thread | None = None
        if self.enabled and preload and self.model_local():
            self._start_load()

    # ---------------------------------------------------------------- 探测
    def _try_import(self):
        """第一层：whisper 这个包在不在。**只 import，不加载模型。**"""
        if not self.enabled:
            return None
        try:
            import whisper
            return whisper
        except Exception as e:                     # ImportError 以及它可能带出的别的
            self._import_err = f"{type(e).__name__}: {e}"
            return None

    def model_file(self) -> Path:
        return MODEL_DIR / f"{self.model_name}.pt"

    def model_local(self) -> bool:
        """第二层：模型权重在不在本地。

        ⚠️ 路径要和 `whisper.load_model(download_root=...)` 的拼法一致，不然会出现
        "这里说在本地、那边又去下载"的分裂。whisper 拼的就是 `<download_root>/<名>.pt`。
        """
        try:
            return self.model_file().is_file()
        except OSError:
            return False

    def _start_load(self):
        self.loading = True
        self._thread = threading.Thread(target=self._load, daemon=True)
        self._thread.start()

    def _load(self):
        """后台加载。只在**本地有文件**时才会被调到（见 `model_local` 的两处调用）。"""
        t0 = time.time()
        try:
            # `download_root` 指向仓库里的 models/whisper（已 gitignore）。
            # 不指这里的话默认落在 ~/.cache/whisper，删项目带不走，换机器要重下。
            self.model = self._whisper.load_model(
                self.model_name, download_root=str(MODEL_DIR), device="cpu")
            self.load_s = time.time() - t0
            self.error = ""
        except Exception as e:
            self.error = f"模型加载失败：{type(e).__name__}: {e}"
        finally:
            self.loading = False

    def engine(self) -> str:
        """一句人话说明现在是什么状态。界面上的只读区直接显示它，不另编。"""
        if not self.enabled:
            return "关掉了（配置 asr.enabled = false）"
        if self._whisper is None:
            return f"没装 openai-whisper（{self._import_err or 'import 失败'}）"
        if not self.model_local():
            return f"装了 whisper，但本地没有模型 {self.model_file().name}"
        if self.loading:
            return f"正在加载模型 {self.model_name}…"
        if self.model is not None:
            return f"本地 whisper {self.model_name} · 已就绪"
        return f"本地 whisper {self.model_name} · 加载失败"

    def ok(self) -> bool:
        """现在**能不能真的转写**。注意它和 `enabled` 不是一回事：
        enabled 是"配置里开着"，ok 是"现在这一秒真的能干活"。"""
        return bool(self.enabled and self._whisper is not None
                    and self.model_local() and self.model is not None)

    def status(self) -> dict:
        """进 `hello.asr`。**每个键都要在**，缺键会让前端显示"—"而不是报错，
        而"—"在界面上和"没做"长得一模一样。"""
        return {
            "enabled": self.enabled,
            "ok": self.ok(),
            "model": self.model_name,
            "model_local": self.model_local(),
            "model_path": str(self.model_file()),
            "engine": self.engine(),
            "prefer": self.prefer,
            "language": self.language,
            "min_s": self.min_s,
            "max_s": self.max_s,
            "first_ms": self.first_ms,
            "loading": self.loading,
            "load_s": self.load_s,
            "busy": self.busy,
            "count": self.count,
            "last_ms": self.last_ms,
            "last_text": self.last_text,
            "error": self.error,
            # 只在真的干不了活时给一条出路。能干活还挂着安装提示，等于在骗人去重装。
            "install_hint": "" if self.ok() else INSTALL_HINT,
        }

    # ---------------------------------------------------------------- 转写
    def transcribe(self, blob: bytes) -> tuple[str, str]:
        """WAV 字节 → (识别文本, 说明)。**不抛异常**，坏消息通过说明文本回来。

        返回的文本在"没识别出来"时一律是**空串** —— 空串是"没听清"的唯一表示，
        绝不用一段编的话去填空（那是这个项目最不能犯的错）。调用方拿空串就回
        「没听清，再说一遍？」。
        """
        if not self.ok():
            return "", self.engine()
        try:
            x = wav_bytes_to_float32(blob)
        except Exception as e:
            return "", f"这段音频读不了：{type(e).__name__}: {e}"

        # ★ 三条判据 + 送进 whisper 的，一律是**掐掉头尾静音之后**的那一段。
        #   为什么必须在这儿（而不是在各调用方）：10 s 静音判据让**每一段**都拖着
        #   长尾巴，拿整段去判就是"话越短越听不见"，见 `trim_silence` 那段。
        x = trim_silence(x)
        dur = len(x) / SR
        if dur < self.min_s:
            return "", f"太短了（{dur:.1f}s，至少要 {self.min_s:.1f}s）"
        if dur > self.max_s:
            return "", f"太长了（{dur:.1f}s，最多 {self.max_s:.0f}s）"
        if quiet(x):
            return "", "基本没听到声音（麦克风没拾到，或者没开权限）"

        # ⚠️ 锁是非阻塞的：拿不到就立刻说"正在识别"，**不排队**。
        if not self.lock.acquire(blocking=False):
            return "", "正在识别上一句，等一下再说"
        self.busy = True
        t0 = time.time()
        try:
            # ⚠️ 是 `self.model.transcribe`，**不是** `self._whisper.transcribe`。
            # `self._whisper` 是**模块**，而模块级的 `whisper.transcribe` 签名是
            # `transcribe(model, audio, *, ...)` —— 拿模块去调，`x` 会被当成
            # `model`，然后报 "missing 1 required positional argument: 'audio'"。
            # 这个错以前一直没被发现：`ok()` 只检查"模型加载了没"，而这条路
            # （浏览器麦克风走不通时的本地兜底）**从来没被真的走过一遍**。
            # 2026-09-24 由 `_scratch/_check_voice_loop.py` 第一次真的转写才暴露。
            r = self.model.transcribe(
                x,
                language=self.language,   # 钉死 zh：为 None 时会先跑一遍语种检测
                                          # （多一遍完整 encoder，CPU 上直接翻倍），
                                          # 而且三五个字的短句语种检测本来就不准。
                fp16=False,               # CPU 上 fp16 不支持；不写它 whisper 会打一行
                                          # "FP16 is not supported on CPU" 的警告。
                verbose=None,             # 不打 tqdm 进度条：它打在启动这个服务的黑框里，
                                          # 现场看起来像报错。
                condition_on_previous_text=False,
                # ^ 默认 True 会让上一段输出影响下一段。这里每次都是独立的一句
                #   （POST 无状态），开着它只会把偶发的错词传染下去。
                initial_prompt=SIMPLIFIED_PROMPT,
                # ^ 简繁的主路，见上面那个常量的注释。**它不占"上一段"那个开关**
                #   （`condition_on_previous_text` 管的是音频上下文，提示是每次都发
                #   的固定前缀），关着前者它照样生效。
            )
            text = " ".join(str(r.get("text") or "").split())
            # 中文里 whisper 会在词间插空格，界面上看着别扭；只在**中文字符之间**
            # 去掉空格，英文短语里的空格留着。
            text = _tidy(text, self.language)
            # ★ 2026-09-26：**兜底那一层** —— 模型还是吐了繁体就在这里换掉（表见
            #   `ui/zh.py`）。**必须在这儿换**：这里是"主人说的话"的**唯一出生点**
            #   （浏览器那条路 `POST /asr` 和常听那条 whisper 路都走这个函数），
            #   换在这里，页面气泡、`say` 里的 `user`、`hub.history`、喂给模型的
            #   那句话**一处都不用改**就是简体。
            #   ⚠️ 不能等下游某处再换：下游有好几处（`ev:"heard"`、`partial`、
            #     气泡、模型输入），漏一处就是"换个页面还是繁体"。
            text = zh_t2s(text)
        except Exception as e:
            self.error = f"识别出错：{type(e).__name__}: {e}"
            return "", self.error
        finally:
            self.busy = False
            self.lock.release()

        self.last_ms = int((time.time() - t0) * 1000)
        self.last_text = text
        self.count += 1
        if not text:
            # whisper 对静音会返回空（`no_speech` 门槛拦住了），这是**正确结果**，
            # 不是错误：说「没听清，再说一遍？」就行。不写进 last_error。
            return "", "识别结果为空（它没听到话；静音或噪声）"
        return text, f"{self.last_ms} ms"


def _tidy(text: str, language: str) -> str:
    """去掉中文字符之间被 whisper 插进来的空格。

    只在**两侧都是中日韩字符**时去掉 —— 不能全局 `replace(' ', '')`，那样
    "把空调调到 24 度"里的英文和数字会被粘成一坨。
    """
    if not text or not language.startswith("zh"):
        return text
    CJK = "一-鿿㐀-䶿　-〿＀-￯"
    import re
    return re.sub(rf"(?<=[{CJK}])\s+(?=[{CJK}])", "", text)


# -------------------------------------------------------------------- 自测
def _bench(rounds: int = 3) -> int:
    """打**这台机器上的真实秒数**，不靠文档里的形容词。

    和 `ui/tts.py --voices` / `ui/deepseek.py --models` 一个惯例：配置里该填什么，
    照着这里打出来的挑。
    """
    a = LocalAsr({"preload": False})
    print("状态      :", a.engine())
    print("模型文件  :", a.model_file(), "存在" if a.model_local() else "**不存在**")
    if not a.model_local() or a._whisper is None:
        print("              先跑 `python ui\\install_asr.bat` 装好再来测。")
        return 1
    t0 = time.time()
    a._load()
    print(f"加载模型  : {a.load_s:.2f} s" if a.load_s else f"加载失败  : {a.error}")
    if a.model is None:
        return 1

    # 5 秒的调幅噪声当输入：不为"识别得准"（那是真人对着麦克风说才算数的事），
    # 只为量**耗时**和**采样率对不对**这两件能自动量的事。
    n = int(4.0 * SR)
    t = np.arange(n) / SR
    x = (0.25 * np.sin(2 * np.pi * 220 * t)
         * (0.5 + 0.5 * np.sin(2 * np.pi * 3.0 * t))).astype(np.float32)
    blob = _sine_wav(x)
    for i in range(rounds):
        t0 = time.time()
        text, why = a.transcribe(blob)
        print(f"第 {i + 1} 轮   : {(time.time() - t0) * 1000:6.0f} ms  "
              f"文本={text!r} 说明={why}")
    print("注意      : 上面这几轮的文本**没有意义**（输入是合成噪声，不是人说话）。")
    print("            它量的是速度。准不准只有真人对着麦克风说才算数。")
    return 0


def _sine_wav(x: np.ndarray) -> bytes:
    """float32 → 16 bit WAV 字节。自测/检查脚本要用，所以放在这里共用。"""
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes((np.clip(x, -1.0, 1.0) * 32767.0).astype("<i2").tobytes())
    return b.getvalue()


def _fetch(model_name: str = DEFAULT_MODEL, mirror: str = "") -> int:
    """把模型权重下到 `models/whisper/`。**只由 `install_asr.bat` 调** —— 服务端自己
    永远不下载（见文件头那条：tqdm 进度条打在启动服务的黑框里，现场最难看的失败）。

    ⚠️ **走 whisper 自己的 `_download`，不自己写 urllib**。理由不是图省事：
    whisper 的官方地址形状是

        https://openaipublic.azureedge.net/main/whisper/models/<sha256>/<名>.pt

    **sha256 就写在 URL 的倒数第二段**，`_download` 拿它校验下载完的文件。自己写一遍
    下载就等于把"校验"这件事抄一遍 —— 而抄出来的校验要么漏（下坏文件不报错），
    要么自己填一个猜的哈希（那比不校验更糟：它是**错的**还看起来像真的）。

    代价是换镜像时**必须保留那个 `<sha256>` 段**：镜像 URL 只允许替换域名和前面的
    路径，`<sha256>/<名>.pt` 这两段得原样保留，否则校验必然失败、然后报一句
    "checksum does not match"，看起来像文件坏了，其实是 URL 少了东西。

    ⚠️ **退出码要分清楚**，`install_asr.bat` 按它给不同的出路：下载失败和
    "whisper 都没装"是两件事，出路也完全是两件事（一个换网络，一个先装包）。
    给同一个码，bat 就只能说一句"模型没下来"，然后猜一个原因 —— 而猜错的那一半
    情况里，人被支去改网络，其实该做的是先装包。
      · 0 = 模型已就位（或本来就在）
      · 1 = 下载失败（网络/镜像）
      · 2 = whisper 包还没装（`import whisper` 就挂了）
      · 3 = 模型名不认识（配置里写错了）
    """
    try:
        import whisper
    except Exception as e:
        print(f"还装不了：{type(e).__name__}: {e}")
        print("先跑 `ui\\install_asr.bat` 装 openai-whisper，再跑 `--fetch`。")
        return 2

    target = MODEL_DIR / f"{model_name}.pt"
    if target.is_file():
        print(f"已经在了  : {target}  （{target.stat().st_size / 1024 / 1024:.1f} MB）")
        print("           不用重下。想重下就先把它删掉。")
        return 0

    models = getattr(whisper, "_MODELS", {}) or {}
    url = models.get(model_name)
    if not url:
        print(f"whisper 不认识这个模型名：{model_name!r}")
        print(f"它认这些  : {', '.join(sorted(models)) or '（读不到，whisper 版本不对？）'}")
        print("改的地方  : ui\\config.json 的 asr.model")
        return 3
    if mirror:
        url = mirror.rstrip("/") + "/" + "/".join(url.split("/")[-2:])
    print(f"模型      : {model_name}")
    print(f"地址      : {url}")
    print(f"落到      : {target}")
    print("", flush=True)

    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    try:
        # `in_memory=False` = 落盘并返回路径。进度条打在这一层，是**该有的** ——
        # 这是个安装脚本，142 MB 没有进度条才是坏的。
        p = whisper._download(url, str(MODEL_DIR), in_memory=False)
    except Exception as e:
        print(f"\n下载失败  : {type(e).__name__}: {e}")
        print("出路      : 这个域名国内可能极慢或不通。可以挂代理重跑，或者用"
              "`--fetch-mirror <镜像前缀>` 换一个源")
        print("            ⚠️ 镜像 URL 必须保留 <sha256>/<名>.pt 这两段，见本函数注释。")
        return 1

    got = Path(p)
    print(f"\n下好了    : {got}  （{got.stat().st_size / 1024 / 1024:.1f} MB）")
    if got != target:
        print(f"⚠️ 落在 {got}，和预期的 {target} 不一样 —— whisper 换了路径拼法，")
        print("   去 ui/asr.py 的 model_local() 把它对齐，否则界面会说'本地没有模型'")
        return 1
    print("校验      : 由 whisper._download 按 URL 里的 sha256 做的，通过了才会走到这里")
    print("下一步    : 跑 `python ui\\asr.py --bench` 看这台机器上的真实秒数")
    return 0


def _main(argv: list[str]) -> int:
    if "--bench" in argv:
        return _bench()
    if "--fetch" in argv:
        name = DEFAULT_MODEL
        if "--model" in argv:
            i = argv.index("--model")
            if i + 1 < len(argv):
                name = argv[i + 1]
        mirror = ""
        if "--fetch-mirror" in argv:
            i = argv.index("--fetch-mirror")
            if i + 1 < len(argv):
                mirror = argv[i + 1]
        return _fetch(name, mirror)
    a = LocalAsr({"preload": False})
    st = a.status()
    print(f"开关      : {'开' if st['enabled'] else '关'}")
    print(f"引擎      : {st['engine']}")
    print(f"模型文件  : {st['model_path']}  ({'在' if st['model_local'] else '不在'})")
    print(f"能干活的  : {'是' if st['ok'] else '否'}")
    print(f"出路      : {st['install_hint'] or '（能干活，不用装）'}")
    print(f"偏好      : prefer={st['prefer']}（browser = 先问浏览器，它不行才轮到本地）")

    # 不装也必须是**好的**状态：不能崩、不能报一堆栈，而且说清楚"没装"。
    # 这一条就是"不装也不能把界面弄坏"那条承诺的自动执行者。
    assert isinstance(st["ok"], bool), "ok 必须是布尔，前端拿它决定说什么"
    assert st["install_hint"] or st["ok"], "干不了活却没给出路，用户只能干瞪眼"
    for k in ("enabled", "ok", "model", "model_local", "model_path", "engine",
              "prefer", "language", "min_s", "max_s", "first_ms", "loading",
              "load_s", "busy", "count", "last_ms", "last_text", "error",
              "install_hint"):
        assert k in st, f"hello.asr 少了键：{k}"
    # WAV 转换是纯函数，不依赖模型，随时可验 —— 三个陷阱里有两个在这一行上。
    zero = _sine_wav(np.zeros(SR, dtype=np.float32))
    y = wav_bytes_to_float32(zero)
    assert y.dtype == np.float32 and y.ndim == 1, "必须是 1 维 float32"
    assert abs(np.abs(y).max()) <= 1.0, "幅值超过 1.0 = 忘了除 32768"
    assert quiet(y), "全零音频必须被判成没声音"
    loud = _sine_wav(np.full(SR, 0.5, dtype=np.float32))
    assert not quiet(wav_bytes_to_float32(loud)), "满幅音频被判成没声音了"

    # 掐头去尾（见 trim_silence）。它是纯函数、不依赖模型，所以在这儿自测。
    # ★ 守的是**真实发生过的坏法**：判据建在"整段平均"上时，同一句话说出去，
    #   尾巴拖 1 s 能听见、拖 10 s 就变成"基本没听到声音"（话越短越听不见）。
    #   `_scratch/_check_voice_loop.py` 的 B/D/G 三段一起红才逼出这个函数。
    voiced = (np.sin(2 * np.pi * 220 * np.arange(int(1.0 * SR)) / SR)
              .astype(np.float32) * 0.5)
    lens = []
    for tail in (1.0, 10.0, 30.0):
        seg = np.concatenate([np.zeros(int(1.0 * SR), np.float32), voiced,
                              np.zeros(int(tail * SR), np.float32)])
        lens.append(len(trim_silence(seg)) / SR)
    assert max(lens) - min(lens) < 0.3, f"掐完的长度居然跟静音尾巴有关：{lens}"
    assert 0.9 < lens[0] < 1.4, f"掐完该回到 1 s 上下，实际 {lens[0]:.2f}s"
    assert quiet(trim_silence(np.zeros(int(12 * SR), np.float32))), \
        "一整段静音掐完还得是'没声音'"
    # 句子**中间**的停顿一个字都不许动（掐头尾 ≠ 把一句话切断）
    mid = np.concatenate([voiced, np.zeros(int(0.4 * SR), np.float32), voiced,
                          np.zeros(int(5 * SR), np.float32)])
    assert len(trim_silence(mid)) / SR > 2.2, \
        f"中间的停顿被掐掉了（那是话的一部分）：只剩 {len(trim_silence(mid)) / SR:.2f}s"
    print("自测通过  : 没装也是干净的'没装'，而且没说谎")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(_main(sys.argv[1:]))
