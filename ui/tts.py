"""服务端备路 —— 浏览器念不出来的时候，由这一侧顶上。

主路是**浏览器**的 `speechSynthesis`（见 `ui/web/live.js` 的 `XQ.speak`）：
Edge 白送晓晓/云希那一批中文神经音色，音质好得多，零安装零 key。这一侧只在
浏览器那条路走不通时登场（页面会发一条 `{"type": "tts", ...}` 过来）——
判据是"探测到它 1.6 s 都没开口"，不是"600 ms 内没发声"：在线音色第一句要先
联网合成，起声慢的时候能到 1 秒上下，探早了就会两边一起念。

音色只能是 Windows SAPI 装了的那些 —— 本机实测**只有 `Microsoft Huihui Desktop`
一个中文音色**（2010 年代机器人味）。神经音色走的是 Edge 自己的合成服务，
SAPI 这个口子够不着，所以这一路天生比主路难听。但它是保底的：**断网也能出声**，
而对一个会报疲劳预警的东西来说，"难听"远好过"没声"。

⚠️ 为什么照抄 `src/live.py:206-248` 的 `TTSWorker` 而不 import 它：
那个文件是带裸 `main()` 的脚本，import 会去开摄像头。这里是同一套做法的新实现，
不是复用 —— 改其中一个不用管另一个。

⚠️ 三处**故意和 `TTSWorker` 不一样**，都是踩过的坑：
  1. 它用 `subprocess.run` + `capture_output`，**杀不掉**。server 退出走的是
     `os._exit(0)`（躲 mediapipe 那 84 秒析构），`on_cleanup` 根本轮不上跑 ——
     念到一半的 powershell.exe 会变成孤儿，在你下一次启动时继续说话。这里改成
     `Popen` + `kill()`。
  2. 它的 `try { SelectVoice } catch {}` **把失败吞了**：机器上没装你要的音色时
     表现是"静默不出声、last_error 也是空的"。这里让 PowerShell 把结果写回来，
     失败变成一句看得见的话。标记分三个（下面 `_ps` 里有详细说明）：
     `XQOK` 念成了 / `XQWARN` 念了但音色不是你要的 / `XQERR` 根本没出声。
  3. 它每次念一句都要弹一个黑框控制台。这个界面是双击启动的，演示时每念一句
     闪一次黑框不能接受，所以加 `CREATE_NO_WINDOW`。

⚠️ 为什么队列只有 2 格而且满了就丢：它是"保底"，不是"主力"。宁可少念一句，
也不能让念稿把状态推送拖住（这条理由和 TTSWorker 一样）。
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import queue
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 合成的 mp3 落在这儿。**必须是 D: 相对路径**（C: 盘满，见项目笔记）；
# server 的 cwd 就是项目根，所以 runs/ 一定在。
TMP_DIR = ROOT / "runs"

DEFAULT_VOICE = "Microsoft Huihui Desktop"
DEFAULT_RATE = 2                      # SAPI 的 -10..10，2 约等于常速偏快
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# ---------------------------------------------------------------- 在线音色（edge-tts）
# ★ 2026-09-25 新增。用户报「声音不像小精灵」—— 这句抱怨指向的正是**这一路**。
#
# 为什么要给**服务端**加一个在线引擎（主路本来就是浏览器的在线神经音色）：
#   浏览器那条路的判据是"1.6 秒没开口就算它不行"，而在线音色第一句要先联网合成，
#   起声慢的时候正好卡在这个窗口上 —— 于是一句本来该用晓晓念的话，被这一侧用
#   **Windows 自带的 Huihui** 抢在中间念了出来。Huihui 是 2010 年代的拼接音，
#   又高又飘，就是用户说的那个"小精灵"。也就是说：**用户听到的很可能是这一路**，
#   而不是浏览器那一路。
#
# ⚠️ 所以修法是"把这一路也换成在线神经音色"，不是"去调浏览器的音色关键词"——
#   只改浏览器那边的话，探测窗口一超时，小精灵照样出来。
#
# `edge-tts` 用的是 Edge 浏览器"朗读"那个公开接口，**免费、不要 key、不要装 Edge**。
# 代价是**要联网**。所以它失败时**自动退回 SAPI**，这一路永远保得住"一定出声"——
# 见 `_run()` 里那段。中文音色全表见 `python ui/tts.py --edge-voices`。
#
# ⚠️ 音色名是 **edge-tts 的短名**（`zh-CN-XiaoxiaoNeural`），和 SAPI 的全名
#   （`Microsoft Huihui Desktop`）**不是一套命名**，所以配置里是两个字段，
#   由 `engine` 决定用哪个。别把短名填进 `voice`。
#
# ⚠️ 钉的是**晓晓**（XiaoxiaoNeural，成年女声），不是列表里那几个"年轻/卡通"
#   音色（晓伊 XiaoyiNeural、云夏 YunxiaNeural 是明写的 child/cartoon）。
#   用户抱怨的就是"小精灵"——**挑音色时避开年轻的那些**才是对的方向，
#   这一条比"好听不好听"重要。要换就打开 web/voice.html 挨个听，别照名字猜。
DEFAULT_EDGE_VOICE = "zh-CN-XiaoxiaoNeural"

# 情感 → 语速/音高修正。**存的是整数**（百分点 / Hz），拼字符串只发生在
# `_edge_mp3()` 那一处。
# ⚠️ 一开始这里存的是 `"-4%"` 这种字符串，然后在配置的基础值后面**拼**上去 ——
#   两个都带符号，拼出来是 `+0%+0%`，edge-tts 直接抛
#   `ValueError: Invalid rate '+0%+0%'`。自测逮到的（`--say` 那一路会把它写进
#   edge_error，然后自动退回 SAPI 接着念，所以"听得出不对、但看不出为什么"，
#   只有读了 edge_error 才知道）。整数相加就没有这个问题。
# 方向和浏览器那条路一致：**越严重越慢越低**，不是又高又急。
EDGE_RATE_ADJ = {"normal": 0, "concerned": -4, "serious": -6, "alert": -8}
EDGE_PITCH_ADJ = {"normal": 0, "concerned": -2, "serious": -3, "alert": -4}


def _pct(s, default: int = 0) -> int:
    """把 `"+0%"` / `"-5%"` / `-5` 都读成一个整数百分点。读不出来就用默认值。

    ⚠️ **不抛异常**：配置写错一个格式不该让整条语音通道起不来 —— 那和这一路
    "保底一定出声"的定位相反。读不出来时按 0 走，并在 status 里看得见
    （`edge_rate` 存的是原字符串，界面上照原样显示，不会被这里的兜底掩盖）。
    """
    try:
        return int(str(s).strip().rstrip("%").replace("Hz", ""))
    except (TypeError, ValueError):
        return default

# 情感 → 语速微调（SAPI 没有独立音高，只能用语速表达语气）。
# ⚠️ 越严重**越慢**，不是越快 —— 哪怕在最严重那档，语气也该是沉住气的，
# 而不是又高又急的警报音（亮灯和喇叭是另一条通道的事）。
# 浏览器的 emotion_prosody 用的是同一个方向（音高也压下来，而且分得比这里细）。
# ★ 2026-09-24：表情从 3 态扩成 4 态（中度 = serious）→ 这张表**必须同时加键**。
#   `_.get(emotion, 0)` 的兜底是 0（常速），漏一个键不会报错，只是那一档的
#   语气**悄悄退回正常语速** —— 听不出错、也查不到，所以宁可显式写一行。
#   ⚠️ concerned 和 serious 都是 -1：SAPI 的 Rate 是整数（-10..10），四档压不进
#   三格。这一档的区分由浏览器那条路承担（0.95 / 0.93），服务端备路本来就只在
#   浏览器念不出来时才走。
RATE_ADJ = {"normal": 0, "concerned": -1, "serious": -1, "alert": -2}


class ServerVoice:
    """后台线程念稿。**绝不阻塞事件循环**（server 那边是 asyncio）。"""

    def __init__(self, cfg: dict | None = None):
        # `cfg` 传的是 config.json 里整个 `tts` 段 —— 不是 `tts.server`。
        # ⚠️ 音色必须从**嵌着的 `server` 子字典**里读，不能从顶层 `voice` 读：
        # 顶层那个 `voice` 是给浏览器用的**关键词**（默认值就是字符串"自动"），
        # 拿它去 SelectVoice 必然失败。这两个同名字段分属两层，是这份配置里
        # 最容易读错的地方。
        cfg = cfg or {}
        srv = cfg.get("server") or {}
        if not isinstance(srv, dict):        # 有人把它写成字符串了，兜住
            srv = {}
        # 只有"总开关开着"且"服务端兜底开着"才起线程。都不开就彻底不占资源。
        self.enabled = bool(cfg.get("enabled", True)) and bool(cfg.get("server_fallback", True))
        self.voice = str(srv.get("voice") or DEFAULT_VOICE)
        # ★ 在线引擎。`engine` 决定"用哪个音色字段"，两个字段不是一套命名。
        _e = str(srv.get("engine") or "edge").strip().lower()
        self.engine = _e if _e in ("edge", "sapi") else "edge"
        self.edge_voice = str(srv.get("edge_voice") or DEFAULT_EDGE_VOICE)
        # 基础语速/音高（配置里写 `"+0%"` / `"-5%"`）。**解析成整数存**，
        # 理由见 EDGE_RATE_ADJ 上面那段（拼字符串踩过）。
        self.edge_rate = str(srv.get("edge_rate") or "+0%")
        self.edge_pitch = str(srv.get("edge_pitch") or "+0Hz")
        self._rate_base = _pct(self.edge_rate)
        self._pitch_base = _pct(self.edge_pitch)
        # 在线那一路自己失败的原因（和 last_error 分开：退回 SAPI 时 last_error
        # 会被 SAPI 那一段重写，只留一个字段的话"为什么退回"就查不出来了）。
        self.edge_error: str | None = None
        try:
            self.rate = int(srv.get("rate", DEFAULT_RATE))
        except (TypeError, ValueError):
            self.rate = DEFAULT_RATE
        try:
            self.timeout_s = float(srv.get("timeout_s", 30))
        except (TypeError, ValueError):
            self.timeout_s = 30.0
        try:
            self.max_chars = int(srv.get("max_chars", 120))
        except (TypeError, ValueError):
            self.max_chars = 120
        try:
            self.q: queue.Queue = queue.Queue(maxsize=int(srv.get("queue", 2)))
        except (TypeError, ValueError):
            self.q = queue.Queue(maxsize=2)

        self.spoken = 0
        self.dropped = 0
        self.last_error: str | None = None
        self.last_detail = ""        # PowerShell 的原话，给人排查用；界面只用得上 last_error
        self.last_text = ""
        self._proc = None
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None
        if self.enabled:
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    # ---------------------------------------------------------------- 外部
    def say(self, text: str, emotion: str = "normal") -> bool:
        """非阻塞、有损。返回"排上队没有"，**不是**"念完没有"。

        只会做 `put_nowait` —— 这个方法是从 asyncio 事件循环里直接调的，
        所以这里绝不能出现任何会等的东西。
        """
        if not self.enabled or not text:
            return False
        try:
            self.q.put_nowait((str(text), emotion))
            return True
        except queue.Full:
            self.dropped += 1
            return False

    def set_voice(self, name: str) -> bool:
        """★ 2026-09-25：运行期换音色（web/voice.html 那个试音台点一下就调它）。

        **只改内存，不回写 config.json。** 理由有两条，都是硬的：
         1. 回写要 json.dump 整个 config —— 里面躺着 `agent.deepseek.api_key`，
            为一个音色去重写那个文件，风险远大于收益（格式会变、写坏了 key 也一起坏）。
         2. 试音台的意义是"挨个听"，听一个就落一次盘，config.json 会变成一行听音记录。
        所以界面上给的是"把这行粘进 config.json"的代码片段，落盘由人来做。

        换的是**下一个**音色，已经在念的那一句不受影响（powershell/mp3 都各自独立）。
        返回"这个名字归我管吗" —— sapi 引擎下改 edge_voice 是没意义的，如实返回 False。
        """
        name = str(name or "").strip()
        if not name:
            return False
        if self.engine != "edge":
            return False
        self.edge_voice = name
        self.edge_error = None          # 换了音色，上一次的失败原因就不算数了
        return True

    def stop(self) -> None:
        """尽力而为：置停止位，并杀掉正在念的那句。

        `os._exit(0)` 之前会调它。daemon 线程本来就随进程消失，要紧的是**子进程**
        别留下 —— 一个还在说话的 powershell.exe 会在下一次启动时突然出声。
        """
        self._stop.set()
        with self._lock:
            p = self._proc
        if p is not None and p.poll() is None:
            try:
                p.kill()
            except Exception:
                pass

    def status(self) -> dict:
        return {"enabled": self.enabled, "voice": self.voice, "rate": self.rate,
                # ★ 2026-09-25：在线引擎那三个字段。`engine` 决定 `voice` 和
                # `edge_voice` 谁在说话 —— 界面上要显示的是**在说话的那个**，
                # 所以两个都给出来，让前端按 engine 挑（别在这儿合成一个
                # "effective_voice"，那样界面上就看不到"配错了哪个"）。
                "engine": self.engine, "edge_voice": self.edge_voice,
                "edge_error": self.edge_error or "",
                "spoken": self.spoken, "dropped": self.dropped,
                "error": self.last_error or "", "detail": self.last_detail,
                "last_text": self.last_text}

    # ---------------------------------------------------------------- 后台
    @staticmethod
    def _clean(text: str, max_chars: int) -> str:
        """单引号翻倍转义（PowerShell 的规矩），换行折成空格，超长截断。

        念的稿子大多是固定常量，但里头会掺模型生成的话，所以这步不能省。
        """
        t = " ".join(str(text).split())
        if len(t) > max_chars:
            t = t[:max_chars]
        return t.replace("'", "''")

    def _ps(self, text: str, emotion: str) -> str:
        safe = self._clean(text, self.max_chars)
        # 音色名同样来自配置，同样要转义 —— 漏了的话一个单引号就能把命令拼歪。
        vname = self.voice.replace("'", "''")
        rate = self.rate + RATE_ADJ.get(emotion, 0)
        rate = max(-10, min(10, rate))
        # 用字符串拼接而不是 f-string：这里面全是 powershell 的 {} 块，
        # f-string 下每个花括号都要翻倍，太难读也容易改错。
        #
        # ⚠️ 三个标记的语义，别搞混（这是自测抓出来的一个真 bug）：
        #   XQOK    —— 用你要的音色念出来了
        #   XQWARN  —— **念出来了，但用的不是你要的音色**（SelectVoice 失败）
        #   XQERR   —— **没念出来**（Speak 自己失败了）
        # 早先这里是两个标记，把"音色没装"和"根本没出声"混成一个 XQERR，
        # 结果是：配错音色时系统其实用默认音色正常念了，却报成失败、spoke 不加。
        # 现在 SelectVoice 失败写 XQWARN 而不是 XQERR，而后面 Speak 真失败时
        # 会把 $e 覆盖成 XQERR —— 先后顺序天然给出了优先级，不用额外判断。
        return (
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
            "Add-Type -AssemblyName System.Speech; $e='XQOK'; "
            "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "try { $s.SelectVoice('" + vname + "') } "
            "catch { $e='XQWARN voice: ' + $_.Exception.Message }; "
            "$s.Rate = " + str(rate) + "; "
            "try { $s.Speak('" + safe + "') } "
            "catch { $e='XQERR speak: ' + $_.Exception.Message }; "
            "Write-Output $e"
        )

    # ------------------------------------------------------------ 在线那一路
    def _edge_mp3(self, text: str, emotion: str) -> bytes:
        """同步取回一段 mp3。**只许在后台线程里调** —— 里面自己开一个事件循环。

        每句一个 `asyncio.run`：这是最省事的写法，而且和这一路的定位相符 ——
        它是"备路"，不是每秒都在跑的东西。真要做成常驻循环，代价是要在后台
        线程里维护一个长期活着的事件循环，收益只有几毫秒。
        """
        import asyncio
        import edge_tts
        # ⚠️ `:+d` 那个加号是**必须的**：edge-tts 只认带符号的写法，
        # `0%` 会被它拒掉（`+0%` 才收）。下面这对格式串是唯一的拼装点。
        rate = "%+d%%" % (self._rate_base + EDGE_RATE_ADJ.get(emotion, 0))
        pitch = "%+dHz" % (self._pitch_base + EDGE_PITCH_ADJ.get(emotion, 0))

        async def go() -> bytes:
            c = edge_tts.Communicate(text, self.edge_voice, rate=rate, pitch=pitch)
            buf = bytearray()
            async for ch in c.stream():
                if ch.get("type") == "audio":
                    buf += ch["data"]
            return bytes(buf)

        return asyncio.run(go())

    def _play_mp3(self, path: str) -> tuple[bool, str]:
        """用 PowerShell 的 WPF `MediaPlayer` 把 mp3 放完再返回。

        ⚠️ 为什么不是 `System.Media.SoundPlayer`：那个**只认 WAV**，而 edge-tts
        吐的是 mp3。转格式要 ffmpeg，这份仓库里 `shutil.which("ffmpeg")` 是 None
        （`ui/asr.py` 的注释里记着这条），所以不能走那条路。
        ⚠️ `MediaPlayer` 是**异步**的：`Play()` 立刻返回、声音还在放。所以要轮询
        `Position` 直到追上 `NaturalDuration`，否则这个方法会立刻返回、下一句
        直接把这一句掐掉。`NaturalDuration.HasTimeSpan` 在打开完成前是 False，
        所以那一项必须一起判。
        ⚠️ 路径直接拼进单引号字符串里：这里**不做转义**，因为路径是我们自己
        拼的（`TMP_DIR` + pid），不含单引号。谁要是把它改成用户可控的路径，
        这里就是一个注入口子。
        """
        ps = (
            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; "
            "Add-Type -AssemblyName PresentationCore; $e='XQOK'; "
            "$p = New-Object System.Windows.Media.MediaPlayer; "
            "try { $p.Open([Uri]'" + path + "'); $p.Play() } "
            "catch { $e='XQERR open: ' + $_.Exception.Message }; "
            "$t0=Get-Date; "
            "while (((Get-Date)-$t0).TotalSeconds -lt " + str(self.timeout_s) + ") { "
            "if ($e -ne 'XQOK') { break }; "
            "Start-Sleep -Milliseconds 100; $p.Play(); "
            "if ($p.NaturalDuration.HasTimeSpan -and "
            "$p.Position -ge $p.NaturalDuration.TimeSpan) { break } "
            "}; "
            "try { $p.Stop(); $p.Close() } catch {}; "
            "Write-Output $e"
        )
        try:
            p = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW)
        except Exception as e:
            return False, f"{type(e).__name__}: {e}"
        with self._lock:
            self._proc = p
        try:
            out, _ = p.communicate(timeout=self.timeout_s + 5)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                out, _ = p.communicate(timeout=5)
            except Exception:
                out = ""
            return False, f"播放超时（>{self.timeout_s:.0f}s），已打断"
        finally:
            with self._lock:
                self._proc = None
        out = (out or "").strip()
        self.last_detail = out
        if "XQERR" in out:
            return False, out
        if "XQOK" not in out:
            return False, f"PowerShell 没有回话（退出码 {p.returncode}）"
        return True, ""

    def _speak_edge(self, text: str, emotion: str) -> tuple[bool, str]:
        """在线合成 + 播放。返回 (成没成, 没成的原因)。**不抛异常。**"""
        try:
            blob = self._edge_mp3(text, emotion)
        except ImportError:
            return False, "没装 edge-tts（双击 ui\\install_tts.bat，或 pip install edge-tts）"
        except Exception as e:
            # 断网、DNS、证书、服务端限流……全归到这儿。**必须带类型名**：
            # 只写 e 的话断网和音色名写错会长得一模一样。
            return False, f"{type(e).__name__}: {e}"
        if not blob:
            return False, "在线合成返回了空音频"
        tmp = TMP_DIR / f"_tts_{os.getpid()}.mp3"
        try:
            TMP_DIR.mkdir(parents=True, exist_ok=True)
            tmp.write_bytes(blob)
        except Exception as e:
            return False, f"写临时文件失败：{type(e).__name__}: {e}"
        try:
            return self._play_mp3(str(tmp))
        finally:
            # 放完就删。留着的下场是 runs/ 里攒一地 mp3，删晚了文件还被
            # MediaPlayer 占着（Windows 上删正在播的文件会失败）—— 所以是
            # "播完再删"，删不掉也不当失败（那是清理，不是交付）。
            try:
                tmp.unlink()
            except Exception:
                pass

    # ------------------------------------------------------------ 主循环
    def _sapi_once(self, text: str, emotion: str) -> None:
        """SAPI 念一句（在线那一路的翻版，也是它的兜底）。"""
        ps = self._ps(text, emotion)
        try:
            p = subprocess.Popen(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                # 上面把 Console::OutputEncoding 设成了 UTF-8，这里必须跟着，
                # 否则默认按 GBK 解，错误信息里的中文全成乱码。
                text=True, encoding="utf-8", errors="replace",
                creationflags=CREATE_NO_WINDOW)
        except Exception as e:                 # 连 powershell 都起不来
            self.last_error = f"{type(e).__name__}: {e}"
            return
        with self._lock:
            self._proc = p
        try:
            out, _ = p.communicate(timeout=self.timeout_s)
        except subprocess.TimeoutExpired:
            p.kill()
            try:
                out, _ = p.communicate(timeout=5)
            except Exception:
                out = ""
            self.last_error = f"念稿超时（>{self.timeout_s:.0f}s），已打断"
            return
        finally:
            with self._lock:
                self._proc = None

            out = (out or "").strip()
            self.last_detail = out
            if "XQERR" in out:
                # **真的没出声**（Speak 自己抛了）。这句不算念过。
                self.last_error = "服务端念不出来，详情见 last_detail"
            elif "XQWARN" in out:
                # **出声了，但不是你要的音色** —— 算念过，但把原因留下来，
                # 否则界面上只会看到"声音怎么换了个人"，却查不出为什么。
                self.spoken += 1
                self.last_text = text
                self.last_error = f"音色回退：{self.voice} 没装上，用的系统默认音色"
            elif "XQOK" in out:
                self.spoken += 1
                self.last_text = text
                self.last_error = None
            else:
                self.last_error = f"PowerShell 没有回话（退出码 {p.returncode}）"

    def _run(self) -> None:
        while not self._stop.is_set():
            text, emotion = self.q.get()
            if self._stop.is_set():
                break
            if self.engine != "edge":
                self._sapi_once(text, emotion)
                continue
            # ---- 在线音色 ----
            ok, why = self._speak_edge(text, emotion)
            if ok:
                self.edge_error = None
                self.spoken += 1
                self.last_text = text
                self.last_error = None
                continue
            # ⚠️ 在线那一路没成 —— **这一句仍然要念出来**，退回 SAPI。
            # 这一支存在的全部意义就是"断网也一定出声"（模块头第一条）。
            self.edge_error = why
            self._sapi_once(text, emotion)
            # SAPI 顺利念了的话 last_error 是 None，会盖掉"为什么退回"这件事，
            # 所以补一句 —— 两个字段各管一半：edge_error 说原因，last_error
            # 说这一句最后是怎么念的。
            if self.last_error is None:
                self.last_error = f"在线音色没接上，这一句用的 Windows 音色（{why}）"

    # 不做更多清理：server 退出走 `os._exit(0)`，线程是 daemon，
    # 本来就不会被 orderly shutdown 照顾到。要管的只有子进程，见 stop()。


# -------------------------------------------------------------------- 自测
def list_edge_voices() -> tuple[list[dict], str]:
    """中文在线音色清单 → (名单, 没拿到时的原因)。**不抛异常。**

    给两个地方用：`--edge-voices` 那个自测，和 `ui/server.py`（试音台点开时
    问一次）。两边共用这一份，是为了保证"命令行列出来的"和"界面上列出来的"
    永远是同一份名单 —— 分开写必然会漂。

    ⚠️ 要联网。拿不到就**如实返回空 + 原因**，退回一份写死的名单是不行的：
    音色表在微软那边，写死的常量会随着时间变成假话。
    """
    try:
        import edge_tts
    except ImportError:
        return [], "没装 edge-tts（双击 ui\\install_tts.bat，或 pip install edge-tts）"
    import asyncio
    try:
        vs = asyncio.run(edge_tts.list_voices())
    except Exception as e:
        return [], f"列不出来（要联网）：{type(e).__name__}: {e}"
    out = [{"short": str(v.get("ShortName") or ""),
            "locale": str(v.get("Locale") or ""),
            "gender": str(v.get("Gender") or "")}
           for v in vs if str(v.get("Locale", "")).lower().startswith("zh")]
    out.sort(key=lambda x: (x["locale"], x["short"]))
    return out, ""


def _list_voices() -> int:
    """列这台机器上 SAPI 实际装了什么 —— 配置里的音色名该照着这里写。"""
    ps = ("Add-Type -AssemblyName System.Speech; "
          "(New-Object System.Speech.Synthesis.SpeechSynthesizer).GetInstalledVoices() "
          "| ForEach-Object { $i = $_.VoiceInfo; "
          "Write-Output ($i.Name + ' | ' + $i.Culture + ' | ' + $i.Gender) }")
    r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                       capture_output=True, text=True, encoding="utf-8",
                       errors="replace", creationflags=CREATE_NO_WINDOW)
    print(r.stdout.strip() or r.stderr.strip())
    return 0


def _list_edge_voices() -> int:
    """列 edge-tts 能用的中文音色 —— `server.edge_voice` 该照着这里写。"""
    zh, why = list_edge_voices()
    if why:
        print(why)
        return 1
    print(f"中文音色 {len(zh)} 个：")
    for v in zh:
        print("  %-32s %-16s %s" % (v["short"], v["locale"], v["gender"]))
    print("\n当前默认:", DEFAULT_EDGE_VOICE)
    return 0


def _wait(v: "ServerVoice", want, timeout: float = 30.0,
          step: float = 0.25) -> dict:
    """等到 status 满足 `want` 为止，返回最后那次 status。**超时就返回现状。**

    ⚠️ 自测里原本到处是 `time.sleep(7)` 这种定值等待，那是**不可靠**的：
    每一条都要起一个 powershell 进程、`Add-Type System.Speech` 是秒级的，
    机器忙的时候这条链能到 8 秒 —— 于是"睡 6 秒然后断言"会**偶发**地红，
    而红的原因和被测的东西毫无关系（实测抓到的：bad 那一段 6 秒不够，
    单独复跑同一个用例 4 秒时还没声、8 秒才出声）。
    改成轮询之后，快的时候立刻过，慢的时候真的等得够。
    """
    import time
    t0 = time.time()
    st = v.status()
    while time.time() - t0 < timeout:
        st = v.status()
        if want(st):
            return st
        time.sleep(step)
    return st


def _main(argv: list[str]) -> int:
    import time
    if "--voices" in argv:
        return _list_voices()
    if "--edge-voices" in argv:
        return _list_edge_voices()
    cfg = {"server_fallback": True}
    if "--sapi" in argv:
        cfg["server"] = {"engine": "sapi"}
    if "--say" in argv:
        v = ServerVoice(cfg)
        print("引擎:", v.engine, "| 音色:", v.edge_voice if v.engine == "edge"
              else v.voice, "| 启用:", v.enabled,
              "| 线程活着:", bool(v.thread and v.thread.is_alive()))
        text = argv[argv.index("--say") + 1]
        v.say(text)
        # 等到"出了声或者留了话"为止，不再拿一个定值 sleep 去赌。
        st = _wait(v, lambda s: s["spoken"] >= 1 or bool(s["edge_error"]), 30)
        print("status:", st)
        v.stop()
        return 1 if v.last_error else 0

    # ① 先自检**在线那一路**（默认引擎）。它不成也要如实报，但不中断 ——
    #    下面还有 SAPI 那一段要跑，而那一段不依赖网络。
    ev = ServerVoice(cfg)
    print("引擎:", ev.engine, "| 音色:", ev.edge_voice)
    ev.say("小瑞语音自检，在线音色这一路。")
    est = _wait(ev, lambda s: s["spoken"] >= 1 or bool(s["edge_error"]), 30)
    print("在线那一路:", est)
    edge_ok = est["spoken"] >= 1 and not est["edge_error"]
    print("  在线音色可用:", edge_ok, "" if edge_ok else f"（{est['edge_error']}）")
    ev.stop()

    # ② SAPI 那一路的老自检：念一句、塞爆队列看丢没丢、把音色名写错看留不留痕。
    #    ⚠️ **必须显式 engine=sapi**：默认引擎已经是在线那一路了，不写死的话
    #    下面这几条断言量到的是另一条路，全都对不上。
    v = ServerVoice({"server_fallback": True, "server": {"engine": "sapi"}})
    print("音色:", v.voice, "| rate:", v.rate, "| 启用:", v.enabled,
          "| 线程活着:", bool(v.thread and v.thread.is_alive()))
    v.say("小瑞语音自检，第一条。")
    # ⚠️ 这个 0.3 s 是**必须**的、不能改成轮询：它要的就是"第一条还在念、
    #    队列还空着"那一瞬间，晚了后面四条就塞不进队列、dropped 恒为 0。
    time.sleep(0.3)
    for i in (2, 3, 4, 5):
        v.say(f"第{i}条，队列只有两格，这条应该被丢掉。")
    st1 = _wait(v, lambda s: s["spoken"] >= 1, 30)
    print("塞爆队列后:", st1)
    assert st1["spoken"] >= 1, "一句都没念成"
    assert v.dropped >= 1, "队列没满过？两格塞四条应该丢"

    bad = ServerVoice({"server": {"engine": "sapi", "voice": "根本不存在的音色"}})
    print("配错音色时 status:", bad.status())
    bad.say("音色配错了，这句应该仍然念得出来。")
    st = _wait(bad, lambda s: s["spoken"] >= 1 or bool(s["error"]), 30)
    print("配错音色后:", st)
    # 这两条断言是配套的：音色配错**不是**"没声"，是"声不对"。
    # 只断 spoken>=1 会漏掉"报成失败但其实念了"那种错（第一版就是这么错的），
    # 所以要连 last_error 一起断 —— 它必须留下话，不能是空。
    assert st["spoken"] >= 1, "SelectVoice 失败后应该仍用默认音色念出来"
    assert st["error"], "音色回退了却什么都没记，界面上就查不出为什么换了个人声"
    assert "回退" in st["error"], f"这条应该是回退警告而不是硬失败：{st['error']}"

    v.stop()
    bad.stop()
    print("自测通过")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.exit(_main(sys.argv[1:]))
