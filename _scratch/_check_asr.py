"""语音输入 · 服务端验收（**不需要麦克风，也不需要浏览器**）。

    python _scratch/_check_asr.py            # 全跑
    python _scratch/_check_asr.py -v         # 顺带打印每条的实测值

这条脚本最要紧的一件事：**证明"绕开 ffmpeg"是真的**。`ui/asr.py` 的文件头写了
一串推理（`whisper.transcribe(ndarray)` 不会进 `load_audio`），但推理不是证据 ——
这里既正面验（同一段 WAV 喂 `transcribe` 不抛），也**反向对照**
（`whisper.audio.load_audio` 对同一个文件**必须抛**）。没有反向对照那一半，
"我们绕开了 ffmpeg"和"这台机器本来就不需要绕"分不开。

**没装 whisper 时会发生什么**：不会红。脚本会把"要真引擎才跑得动"的那几条
**记成跳过**，并在结尾把跳过数打出来，退出码 **2**（不是 0）。这是故意的 ——
这个项目里"没跑过"和"通过"必须长得不一样，否则一份有一半没跑的绿色报告
比红的还危险。装完 `ui\\install_asr.bat` 再跑一遍，退出码才应该是 0。

**有一条判据从一开始就不指望真引擎**：`min_s` / `quiet()` / 异常兜底这三条守卫
是 **`ui/asr.py` 自己的代码**，不是 whisper 的。用真 whisper 去测它们等于让被测
对象兼任测量仪器；更糟的是"全零音频 → 返回空串"这种断言在真 whisper 上会
**假过** —— `quiet()` 拦在进引擎之前，所以哪怕 whisper 根本没装、`transcribe`
在第一行就返回空串，这条也照样绿。所以这几条走的是脚本里那个**假引擎**（`_Stub`），
并且配上"3 秒正常音频必须真的到达引擎"作为对照，证明前面的空串不是"永远返回空"。

**只能靠人验的**（自动化到不了的地方，别以为跑绿了就万事大吉）：
  · 识别得准不准。脚本里的音频是**合成正弦/噪声**，`base` 模型对它只会输出空串或
    一句不存在的话 —— 中文短句的实际准确率**只有真人对着麦克风说才算数**。
  · `cam` 模式下（推理已经把 CPU 占满）识别还能不能按时出结果。答辩现场大概率
    就是 cam 模式，而这里测的全是 demo 模式下的空转。
  · 静音检测会不会把人说话中间的**停顿**当成"说完了"。
  · 权限弹窗在 kiosk 全屏下长什么样（浏览器那条路的第一屏就是它）。
"""

from __future__ import annotations

import asyncio
import io
import json
import shutil
import struct
import subprocess
import sys
import time
import wave
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "ui"))

import aiohttp                                                          # noqa: E402
import asr as A                                                         # noqa: E402
import server as S                                                      # noqa: E402

VERBOSE = "-v" in sys.argv
PORT = 8791
WAV = None          # 后面填：一段 2 秒、够响、能过 quiet() 的 16k 单声道 WAV

PASS: list[str] = []
FAIL: list[str] = []
SKIP: list[str] = []


def ck(name: str, ok: bool, note: str = "") -> None:
    (PASS if ok else FAIL).append(name)
    print(f"  {'✅' if ok else '❌'} {name}" + (f"   {note}" if note else ""))


def skip(name: str, why: str) -> None:
    SKIP.append(name)
    print(f"  ⏭️  {name}   （跳过：{why}）")


def sec(t: str) -> None:
    print(f"\n=== {t} ===")


# ------------------------------------------------------------------ 造音频
def _wav(x: np.ndarray, sr: int = 16000, ch: int = 1, width: int = 2) -> bytes:
    """任意采样率/声道/位深的 WAV 字节。`ui/asr.py` 里那个 `_sine_wav` 只出
    16k 单声道 16bit，而这里的重点恰好是**别的**几种。"""
    if ch > 1:
        x = np.repeat(x, ch)
    if width == 1:
        raw = (np.clip(x, -1, 1) * 127 + 128).astype(np.uint8).tobytes()
    else:
        raw = (np.clip(x, -1, 1) * 32767).astype("<i2").tobytes()
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(ch)
        w.setsampwidth(width)
        w.setframerate(sr)
        w.writeframes(raw)
    return b.getvalue()


def _tone(sec: float, sr: int = 16000, amp: float = 0.25) -> np.ndarray:
    t = np.arange(int(sec * sr)) / sr
    return (amp * np.sin(2 * np.pi * 220 * t)).astype(np.float32)


def _with_extra_chunk(b: bytes) -> bytes:
    """在 fmt 和 data 之间插一个 LIST 块，并修好 RIFF 长度。

    这就是"不能 `blob[44:]` 硬切"那条注释的可执行版本：canonical 头是 44 字节，
    这里插进去 12 字节之后 data 从 48 开始，硬切会把块头的 8 个字节当成样本读。
    """
    extra = b"LIST" + struct.pack("<I", 4) + b"INFO"
    out = bytearray(b)
    out[4:8] = struct.pack("<I", struct.unpack("<I", bytes(out[4:8]))[0] + len(extra))
    out[36:36] = extra
    return bytes(out)


# ------------------------------------------------------------------ 假引擎
class _StubEngine:
    """`LocalAsr.transcribe` 唯一调到的那个对象。见文件头「有一条判据从一开始
    就不指望真引擎」那一段。"""

    def __init__(self, text: str = "我有点困", boom: Exception | None = None):
        self.text = text
        self.boom = boom
        self.calls = 0
        self.kw: dict = {}

    def transcribe(self, x, **kw):
        self.calls += 1
        self.kw = kw
        if self.boom:
            raise self.boom
        return {"text": self.text}


class _Stub(A.LocalAsr):
    def __init__(self, text: str = "我有点困", boom: Exception | None = None):
        super().__init__({"preload": False})
        self.eng = _StubEngine(text, boom)
        self._whisper = self.eng
        self.model = object()

    def model_local(self) -> bool:
        return True

    def ok(self) -> bool:
        return True


# ------------------------------------------------------------------ A 纯函数
def section_a() -> None:
    sec("A. 绕开 ffmpeg 的前提，和三个『不报错』的陷阱")

    ff = shutil.which("ffmpeg")
    ck("前提：本机没有 ffmpeg", ff is None,
       "" if ff is None else f"但是找到了 {ff} —— 反向对照那一条就证明不了什么了")

    # A1 44.1k 当成 16k 是"不报错"陷阱之一：whisper 既不重采样也不检查采样率。
    y = A.wav_bytes_to_float32(_wav(_tone(4.0, 44100), 44100))
    ck("44.1k 重采样到 16k，长度对得上", abs(len(y) - 4.0 * 16000) <= 4,
       f"{len(y)} 个样本（应为 {int(4.0 * 16000)}）")

    # A2 双声道要塌成 1 维，否则 whisper 会把两个声道当两倍时长。
    y = A.wav_bytes_to_float32(_wav(_tone(2.0), 16000, ch=2))
    ck("双声道塌成 1 维", y.ndim == 1, f"ndim={y.ndim} len={len(y)}")

    # A3 ★ 忘了除 32768 是"不报错"陷阱里最阴的一个：波形整体放大三万倍，
    # 削顶成方波，whisper 照样跑完，只是输出胡话。
    y = A.wav_bytes_to_float32(_wav(np.full(16000, 1.0, dtype=np.float32)))
    ck("满幅 ±32767 → 幅值落在 ±1 内", np.abs(y).max() <= 1.0,
       f"max={np.abs(y).max():.4f}")
    ck("满幅输入确实接近满幅（不是整段被压小）", np.abs(y).max() > 0.99,
       f"max={np.abs(y).max():.4f}")

    # A4 8 bit WAV 是无符号的，中点 128。当成有符号读会把波形整个翻个面 —— 也不报错。
    hi = A.wav_bytes_to_float32(_wav(np.full(8000, 1.0, dtype=np.float32), width=1))
    lo = A.wav_bytes_to_float32(_wav(np.full(8000, -1.0, dtype=np.float32), width=1))
    ck("8 bit 的符号没读反", hi.max() > 0.9 and lo.min() < -0.9,
       f"正max={hi.max():.3f} 负min={lo.min():.3f}")

    # A5 用 wave 模块解析而不是硬切 44 字节（插了个 LIST 块）。
    plain = _wav(_tone(2.0))
    a = A.wav_bytes_to_float32(plain)
    b = A.wav_bytes_to_float32(_with_extra_chunk(plain))
    ck("头部多一个块也不会错位（没硬切 44 字节）",
       len(a) == len(b) and np.allclose(a, b, atol=1e-6),
       f"canonical={len(a)} 带LIST={len(b)}")

    # A6 静音守卫的判据必须是"相对本段峰值的比例"，不是绝对阈值。
    ck("全零被判成没声音", A.quiet(np.zeros(16000, dtype=np.float32)))
    ck("满幅不被判成没声音", not A.quiet(np.full(16000, 0.5, dtype=np.float32)))
    # 底噪 + 末尾一声响：峰值不低（过得了 min_s），但 RMS 相对峰值极小。
    # ⚠️ 那声"响"必须**极短**（这里 10 个样本 ≈ 0.6 ms，像一声鼠标点击）。
    # 写长一点（比如 1000 个样本 = 62 ms）RMS 就上去了，这条**反而会失败** ——
    # 而那不是判据错了：60 毫秒的响声本来就该被当成有声音。
    x = np.concatenate([np.full(15990, 0.002, dtype=np.float32),
                        np.full(10, 0.5, dtype=np.float32)])
    ck("底噪里的一声鼠标响也判成没声音", A.quiet(x),
       f"peak={A.level(x)[0]:.3f} rms={A.level(x)[1]:.4f}")


# ------------------------------------------------------------------ B 守卫
def section_b() -> None:
    sec("B. 我们自己的守卫（用假引擎，和 whisper 隔开测）")

    KEYS = ("enabled", "ok", "model", "model_local", "model_path", "engine",
            "prefer", "language", "min_s", "max_s", "first_ms", "loading",
            "load_s", "busy", "count", "last_ms", "last_text", "error",
            "install_hint")
    st = A.LocalAsr({"preload": False}).status()
    missing = [k for k in KEYS if k not in st]
    ck("hello.asr 的键一个不缺", not missing, f"缺：{missing}" if missing else f"{len(KEYS)} 个键")

    # 键名这份清单是**抄**的，不是从 ui/asr.py import 的 —— 测试如果从被测对象
    # 那里取清单，就永远测不出"少了一个键"。
    s = _Stub()
    ck("ok() 返回的是布尔，不是真值", isinstance(s.status()["ok"], bool))
    ck("干不了活时必须给一条出路",
       bool(A.LocalAsr({"enabled": False}).status()["install_hint"]))

    # 配置注入坏状态（照 ui/tts.py:271 那个写法）：关掉 / 模型名写错，
    # 都不能崩，而且要如实说。
    off = A.LocalAsr({"enabled": False})
    ck("配置里关掉 → ok=False 且说得出为什么",
       off.ok() is False and "关" in off.engine(), off.engine())
    bad = A.LocalAsr({"model": "并不存在的模型名"})
    ck("模型名写错不崩、如实报",
       isinstance(bad.status(), dict) and bad.ok() in (True, False), bad.engine())

    # ★ 守卫四条。前两条是"空串"，所以必须有第三条（正常音频真的到引擎）当对照，
    # 否则"总是返回空串"也能全绿。
    e = _Stub()
    t, why = e.transcribe(_wav(_tone(3.0)))
    ck("3 秒正常音频 → 真的到达引擎并带回文本",
       t == "我有点困" and e.eng.calls == 1, f"text={t!r} calls={e.eng.calls}")
    kw = e.eng.kw
    ck("language/fp16/verbose/condition_on_previous_text 都传对了",
       kw.get("language") == "zh" and kw.get("fp16") is False
       and kw.get("verbose") is None and kw.get("condition_on_previous_text") is False,
       f"{ {k: kw.get(k) for k in ('language', 'fp16', 'verbose', 'condition_on_previous_text')} }")

    e = _Stub()
    t, why = e.transcribe(_wav(_tone(0.1)))
    ck("太短的音频根本不进引擎", t == "" and e.eng.calls == 0 and "太短" in why, why)

    e = _Stub()
    t, why = e.transcribe(_wav(np.zeros(3 * 16000, dtype=np.float32)))
    ck("★ 静音根本不进引擎（幻视的第一道闸）",
       t == "" and e.eng.calls == 0, f"calls={e.eng.calls} why={why}")

    e = _Stub(boom=RuntimeError("假装引擎炸了"))
    try:
        t, why = e.transcribe(_wav(_tone(3.0)))
        ck("引擎抛异常时不往外抛，返回空串", t == "" and "识别出错" in why, why)
    except Exception as exc:
        ck("引擎抛异常时不往外抛，返回空串", False, f"它抛出来了：{type(exc).__name__}: {exc}")

    # whisper 对静音/噪声返回空文本是**正确结果**，不是错误。
    e = _Stub(text="")
    t, why = e.transcribe(_wav(_tone(3.0)))
    ck("引擎返回空文本 → 空串 + 说明，且不计入 last_error",
       t == "" and "空" in why and not e.error, f"why={why} error={e.error!r}")

    # 中文之间去空格；**数字和英文两边的空格必须留着**。
    # ⚠️ 这一条判据我第一版写反了（写成"24"两边也会被粘起来）：`_tidy` 的字符类
    # 是中/日/韩，数字 U+0032 不在里面，所以 "调到 24 度" 原样不动 —— 这正是
    # 注释里说的"不能全局 replace(' ', '')"。写错的那版会红，红得对：它说明我以为
    # 代码做了件它没做的事，而不是代码坏了。
    ck("中文之间去空格，数字英文两边的留着",
       A._tidy("我 有点 困", "zh") == "我有点困"
       and A._tidy("把空调调到 24 度", "zh") == "把空调调到 24 度"
       and A._tidy("OK Google", "zh") == "OK Google",
       repr(A._tidy("把空调调到 24 度", "zh")))


# ------------------------------------------------------------------ C 装没装
def section_c() -> None:
    sec("C. 文案里的路径必须真的存在（现场最尴尬的失败）")

    hint = A.INSTALL_HINT
    ck("install_hint 里指的是 ui\\install_asr.bat，这个文件真的在",
       (ROOT / "ui" / "install_asr.bat").is_file(), hint)
    ck("requirements-asr.txt 在", (ROOT / "ui" / "requirements-asr.txt").is_file())
    ck("install_asr.bat 是纯 ASCII（cmd 用 GBK 解析 .bat）",
       all(c < 128 for c in (ROOT / "ui" / "install_asr.bat").read_bytes()))

    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    ck(".gitignore 挡了模型权重", "models/whisper/*.pt" in gi)

    # 配置模板里提到的命令要真的存在（`python ui/asr.py --bench`）。
    ex = (ROOT / "ui" / "config.example.json").read_text(encoding="utf-8")
    ck("config.example.json 有 asr 段", '"asr"' in ex)
    ck("配置里那句 --bench 是真命令", "--bench" in ex and hasattr(A, "_bench"))


# ------------------------------------------------------------------ D 413
def section_d() -> None:
    sec("D. POST /asr 的护栏（直接调处理函数，不经网线）")

    class _Req:
        # 只有超限那一支会被走到，而那一支**根本不碰 hub** —— 所以给个空对象就够，
        # 不用为了测这一条去把整个 Hub 建起来（那会把 Agent / ServerVoice / 数据源
        # 全拉起来，测一条纯计算反而变慢变脆）。
        app = {"hub": None}
        content_length = 5 * 1024 * 1024

        async def read(self):
            raise AssertionError("超限的请求不该走到 read() —— 读了就白读 5 MB")

    resp = asyncio.run(S.asr_post(_Req()))
    body = json.loads(resp.body.decode("utf-8"))
    ck("超过 2 MB 直接 413，而且给的是人话",
       resp.status == 413 and "MB" in body.get("why", ""), f"{resp.status} {body}")


# ------------------------------------------------------------------ E 并发
def _read_port_ready(port: int, secs: float = 25.0) -> bool:
    import socket
    t0 = time.time()
    while time.time() - t0 < secs:
        with socket.socket() as s:
            s.settimeout(0.4)
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return True
        time.sleep(0.25)
    return False


async def section_e() -> None:
    sec("E. 慢转写不许把服务卡住（假引擎 + 真 HTTP/WS）")

    env = dict(__import__("os").environ)
    env["PYTHONIOENCODING"] = "utf-8"
    # 日志落文件而不是丢 DEVNULL：这个子进程起不来的时候（端口占用、import 炸、
    # 配置读不到），DEVNULL 会让失败现场只剩一句"25 秒内没监听上端口"，
    # 而真正的原因在它自己的 traceback 里。
    logp = Path(__file__).parent / "_asr_srv.log"
    log = open(logp, "wb")
    proc = subprocess.Popen(
        [sys.executable, "-u", str(Path(__file__).parent / "_asr_srv.py"),
         "--port", str(PORT), "--slow", "1.5"],
        cwd=str(ROOT), env=env, stdout=log, stderr=subprocess.STDOUT)
    try:
        if not _read_port_ready(PORT):
            log.flush()
            tail = logp.read_text(encoding="utf-8", errors="replace")[-1200:]
            ck("慢引擎服务起来了", False, f"25 秒内没监听上端口，它的输出：\n{tail}")
            return
        ck("慢引擎服务起来了", True, f"127.0.0.1:{PORT}")

        url = f"http://127.0.0.1:{PORT}"
        async with aiohttp.ClientSession() as sess:
            async with sess.ws_connect(f"{url}/ws") as ws:
                hello = json.loads((await ws.receive()).data)
                ck("WS hello 里带 asr 段", "asr" in hello.get("data", {}))
                ck("hello.asr 说这是假引擎（测试替身别混进结论）",
                   "假" in hello["data"]["asr"]["engine"], hello["data"]["asr"]["engine"])

                async def post(blob: bytes) -> dict:
                    async with sess.post(f"{url}/asr", data=blob) as r:
                        return json.loads(await r.text())

                # E1 正常一路
                r = await post(WAV)
                ck("POST /asr 正常返回文本", r.get("text") == "我有点困", str(r))

                # E2 坏字节不能是 500，得是一句人话。
                # （`b"中文"` 是语法错误 —— 字节字面量只能放 ASCII，所以 .encode。）
                r = await post("这不是一个 WAV 文件".encode("utf-8"))
                ck("坏字节 → 空串 + 人话（不是 500）",
                   r.get("text") == "" and "读不了" in r.get("why", ""), str(r))

                # ★ E3 第一条还在跑时，第二条必须**立刻**被顶回来（拒绝，不排队）。
                # 排队的话表现是"点第二下像卡住"，而界面上的 busy 只管得住自己那一页。
                t1 = asyncio.create_task(post(WAV))
                await asyncio.sleep(0.35)          # 让第一条真的进到引擎里
                t0 = time.time()
                r2 = await post(WAV)
                dt = time.time() - t0
                ck("★ 第二条立刻拿到『正在识别』（< 300 ms）",
                   dt < 0.30 and "正在识别" in r2.get("why", ""),
                   f"{dt * 1000:.0f} ms  why={r2.get('why')!r}")
                r1 = await t1
                ck("第一条没被第二条挤掉", r1.get("text") == "我有点困", str(r1))

                # ★ E4 慢转写期间 state 推送必须照常流。
                # 忘了 `to_thread` 的坏法在别的测试里完全看不出来：状态最后还是会到，
                # 只是那 1.5 秒里全部停住 —— 现场看起来就是"点了一下，整块屏卡住"。
                #
                # ⚠️ **量之前必须先把积压读空。** E3 那一段我们从没读过 WS，缓冲区里
                # 躺着两秒多的 state（demo 源 8 Hz）。不排空的话，下面这 1 秒里读到的
                # 几乎全是**积压**：就算事件循环真的被 transcribe 堵死、这一秒一条新的
                # 都没产生，那些积压也足够把计数喂到 4 以上 —— 一条永远绿的断言。
                # 第一版就是这么写的，读出了 37 条（8 Hz 的源在 1 秒里不可能产生 37 条），
                # 那个数字本身就是"量错了"的证据。
                while True:
                    try:
                        await asyncio.wait_for(ws.receive(), timeout=0.25)
                    except asyncio.TimeoutError:
                        break                      # 静了 0.25 s = 队列空了

                t = asyncio.create_task(post(WAV))
                await asyncio.sleep(0.35)          # 让转写真的进到引擎里
                # 下面这 1 秒整段都落在那 1.5 秒的转写里 —— 所以窗口里每一条 state
                # 都只能来自"事件循环在转写期间还活着"。
                n, t0 = 0, time.time()
                while time.time() - t0 < 1.0:
                    try:
                        m = await asyncio.wait_for(ws.receive(), timeout=1.0)
                    except asyncio.TimeoutError:
                        break
                    try:
                        if json.loads(m.data).get("type") == "state":
                            n += 1
                    except Exception:
                        pass
                await t
                ck("★ 转写进行中 state 照常推（1 秒 ≥ 4 条）", n >= 4,
                   f"收到 {n} 条（源是 8 Hz，排空积压后这里约 8 条才算对）")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=8)
        except subprocess.TimeoutExpired:
            proc.kill()
        log.close()


# ------------------------------------------------------------------ F 真引擎
def section_f() -> None:
    sec("F. 真的 whisper（没装就整段跳过，不算通过）")

    a = A.LocalAsr({"preload": False})
    if a._whisper is None:
        skip("真引擎那一组（6 条）", "没装 openai-whisper：双击 ui\\install_asr.bat")
        return
    if not a.model_local():
        skip("真引擎那一组（6 条）", f"本地没有 {a.model_file().name}：install_asr.bat --fetch-model")
        return

    a._load()
    ck("模型加载起来了", a.model is not None, a.error or f"{a.load_s:.2f} s")

    p = ROOT / "_scratch" / "_asr_probe.wav"
    p.write_bytes(WAV)

    # ★★ 反向对照：同一段 WAV 交给 whisper 自己的 load_audio **必须抛**。
    # 没有这一半，"我们绕开了 ffmpeg"和"这台机器本来不需要绕"是分不开的。
    import whisper
    try:
        whisper.audio.load_audio(str(p))
        ck("★ 反向对照：whisper.load_audio 对同一段音频会抛（证明绕开它有意义）",
           False, "它居然成功了 —— 说明这台机器上有 ffmpeg，前提不成立")
    except Exception as e:
        ck("★ 反向对照：whisper.load_audio 对同一段音频会抛（证明绕开它有意义）",
           True, f"{type(e).__name__}")

    try:
        t, why = a.transcribe(WAV)
        ck("★ 数组直喂 transcribe 不抛异常（这就是绕开的正面证据）",
           "读不了" not in why and "出错" not in why, f"why={why} text={t!r}")
    except Exception as e:
        ck("★ 数组直喂 transcribe 不抛异常（这就是绕开的正面证据）",
           False, f"{type(e).__name__}: {e}")

    t, why = a.transcribe(_wav(np.zeros(3 * 16000, dtype=np.float32)))
    ck("真引擎 + 静音 → 空串（不是幻视出来的话）",
       t == "" and "没听" in why, f"why={why}")

    t, why = a.transcribe(_wav(_tone(0.2)))
    ck("真引擎 + 太短 → 空串", t == "" and "太短" in why, why)

    ck("ok() 为真（模型在本地且加载好了）", a.ok() is True)
    ck("status().install_hint 能干活时是空的", a.status()["install_hint"] == "")
    if VERBOSE:
        print(f"      （合成的 3 秒正弦识别成 {t!r} —— 这个文本没有意义，"
              f"合成音不是人话，别拿它判断准不准）")


# ------------------------------------------------------------------ main
def main() -> int:
    global WAV
    WAV = _wav(_tone(2.0))
    print("语音输入 · 服务端验收")
    print(f"解释器   : {sys.executable}")
    print(f"ffmpeg   : {shutil.which('ffmpeg') or '（没有）'}")

    section_a()
    section_b()
    section_c()
    section_d()
    asyncio.run(section_e())
    section_f()

    print()
    print(f"通过 {len(PASS)} · 失败 {len(FAIL)} · 跳过 {len(SKIP)}")
    if FAIL:
        print("\n失败：")
        for n in FAIL:
            print(f"  · {n}")
    if SKIP:
        print("\n跳过（**不算通过**）：")
        for n in SKIP:
            print(f"  · {n}")
        print("\n装完 ui\\install_asr.bat 再跑一遍，退出码才该是 0。"
              "现在这个 2 的意思是『有一半没跑过』，不是『跑过了都好』。")
        return 2
    if FAIL:
        return 1
    print("全绿。")
    return 0


if __name__ == "__main__":
    # ⚠️ 必须重设 stdout 编码：stdout 被**重定向到文件**时 python 会用 GBK 编码，
    # 而上面每个 ✅ 都是非 GBK 字符，第一个就 UnicodeEncodeError 把脚本炸在开头。
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(main())
