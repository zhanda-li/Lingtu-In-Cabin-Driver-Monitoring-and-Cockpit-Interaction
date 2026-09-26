"""合成座舱多媒体那三首曲子 -> ui/web/assets/*.wav

    python ui/make_audio.py            # 生成（已存在就覆盖）
    python ui/make_audio.py --check    # 只报现有文件的状态，不写盘

**为什么要合成本地音频，而不是放三首真歌**：这是要**提交进仓库**的东西，
真歌一放上去就是版权问题，而这个仓库是公开的作品集。用 numpy 算三个波形出来，
来源上没有任何问题，而且下面页脚那句"音频是本机合成的，不是曲库"是真话。

风格是照着用途挑的（和座舱里那三档状态对得上）：
  calm   舒缓 —— 慢速和弦垫，用来配「轻度疲劳，放段音乐吧」
  alert  提神 —— 五声音阶的拨弦，节奏清楚、不吵
  noise  白噪音 —— 低频噪声，助眠/遮蔽用

⚠️ 采样率写死 16000 Hz、单声道、16 bit。**别改成 44100/立体声**：
文件会大三倍，而这三段全是低频内容，16 kHz 的奈奎斯特是 8 kHz，
够用；答辩现场要拷来拷去，2 MB 和 6 MB 是两回事。
（16 kHz 也是 `ui/asr.py` 那边用的采样率，将来若要拿它当语音自检的输入，
不用再重采样 —— 虽然目前没有这个用法。）

⚠️ 三段都做了 0.3 秒淡入淡出。**别去掉**：波形在文件头尾被硬切断会"啪"一声，
在座舱那种安静环境里比音乐本身还显眼。
"""

from __future__ import annotations

import sys
import wave
from pathlib import Path

import numpy as np

SR = 16000
OUT = Path(__file__).resolve().parent / "web" / "assets"

# 结尾的淡出、开头的淡入（秒）。见文件头那条注释。
FADE = 0.3


def _fade(x: np.ndarray) -> np.ndarray:
    n = int(FADE * SR)
    if n * 2 >= len(x):
        n = max(1, len(x) // 4)
    ramp = np.linspace(0.0, 1.0, n)
    x = x.copy()
    x[:n] *= ramp
    x[-n:] *= ramp[::-1]
    return x


def _norm(x: np.ndarray, peak: float = 0.62) -> np.ndarray:
    """归一化到固定峰值。**不给每段单独定音量** —— 三段音量不一致的话，
    切歌时会被当成"这一段坏了"。0.62 留出余量，避免 float32→int16 时削顶。"""
    m = float(np.max(np.abs(x))) or 1.0
    return x / m * peak


def calm(sec: float = 20.0) -> np.ndarray:
    """舒缓：一个 A 大三和弦的垫音，两个缓慢起伏的层叠在一起。"""
    n = int(sec * SR)
    t = np.arange(n) / SR
    # A2 E3 A3 C#4 E4 —— 只用低次谐波，听感就是"闷"的，正是想要的
    freqs = [110.00, 164.81, 220.00, 277.18, 329.63]
    weights = [1.00, 0.72, 0.60, 0.34, 0.26]
    sig = np.zeros(n)
    for i, (f, w) in enumerate(zip(freqs, weights)):
        # 每个音都加一个 -6 音的失谐副音，两路拍频出缓慢的 chorus
        slow = 0.55 + 0.45 * np.sin(2 * np.pi * (0.07 + 0.013 * i) * t + i)
        sig += w * slow * np.sin(2 * np.pi * f * t)
        sig += 0.28 * w * np.sin(2 * np.pi * (f * 1.0035) * t + 1.1)
        sig += 0.16 * w * np.sin(2 * np.pi * (2 * f) * t + 0.4)
    # 极慢的整体呼吸，2.5 分钟一次 —— 20 秒里只露出很小一段，够用
    sig *= 0.82 + 0.18 * np.sin(2 * np.pi * 0.0067 * t)
    return _fade(_norm(sig))


def alert(sec: float = 16.0) -> np.ndarray:
    """提神：A 小调五声音阶的拨弦，每拍一个音，四拍一记低频。"""
    n = int(sec * SR)
    bpm, beats_per_note = 132.0, 0.5
    step = 60.0 / bpm * beats_per_note
    scale = [440.00, 523.25, 587.33, 659.25, 783.99, 659.25, 587.33, 523.25]
    # 写死一个音序，不用随机 —— 随机会出现"某个音听着别扭"，而这是要反复听的
    order = [0, 2, 4, 3, 5, 4, 2, 1, 0, 2, 4, 6, 5, 3, 1, 2]
    sig = np.zeros(n)
    k = 0
    pos = 0.0
    while pos < sec:
        f = scale[order[k % len(order)]]
        i0 = int(pos * SR)
        ln = min(int(0.9 * SR), n - i0)
        if ln <= 0:
            break
        tt = np.arange(ln) / SR
        # 拨弦：指数衰减 + 一个二次谐波，衰减比基音快（真实弦就这样）
        tone = np.exp(-6.5 * tt) * np.sin(2 * np.pi * f * tt)
        tone += 0.30 * np.exp(-11.0 * tt) * np.sin(2 * np.pi * 2 * f * tt)
        sig[i0:i0 + ln] += 0.42 * tone
        if k % 4 == 0:                      # 四拍一记低频，给个落点
            ln2 = min(int(0.34 * SR), n - i0)
            t2 = np.arange(ln2) / SR
            sweep = 92.0 * np.exp(-9.0 * t2) + 44.0
            sig[i0:i0 + ln2] += 0.34 * np.exp(-8.0 * t2) * np.sin(2 * np.pi * sweep * t2)
        pos += step
        k += 1
    return _fade(_norm(sig))


def noise(sec: float = 14.0) -> np.ndarray:
    """白噪音：其实做得偏"棕噪"（低频更重），纯白噪听久了刺耳。
    做法是白噪做一次累积和 —— 累积和就是一阶积分，频谱按 1/f² 掉。"""
    n = int(sec * SR)
    rng = np.random.default_rng(20260923)     # 固定种子：重跑同一个文件，
    w = rng.standard_normal(n)                # 免得每次生成的噪声不一样
    b = np.cumsum(w)
    b -= np.linspace(b[0], b[-1], n)          # 去掉积分带来的直流斜坡，否则是一段下滑
    b -= b.mean()
    # 再拿一个很轻的一阶低通把最高频磨掉，听感更"雨声"而不是"嘶声"
    a = 0.86
    out = np.empty(n)
    acc = 0.0
    for i in range(n):
        acc = a * acc + (1 - a) * b[i]
        out[i] = acc
    out *= 0.9 + 0.1 * np.sin(2 * np.pi * 0.05 * np.arange(n) / SR)
    return _fade(_norm(out))


TRACKS = [
    ("calm.wav", "舒缓 · 低频和弦垫", calm),
    ("alert.wav", "提神 · 五声音阶拨弦", alert),
    ("noise.wav", "白噪音 · 雨声", noise),
]


def wav_bytes(x: np.ndarray) -> bytes:
    """float32(-1~1) -> 16 bit 小端 PCM。
    ⚠️ `clip` 不能省：上面虽然归一化过了，但相加之后个别采样仍可能略微出界，
    出界在 int16 里是**回绕**（0.7 变成 -0.99），听感是"啪"的一声爆音。"""
    i16 = np.clip(x, -1.0, 1.0)
    return (i16 * 32767.0).astype("<i2").tobytes()


def main() -> int:
    check = "--check" in sys.argv
    OUT.mkdir(parents=True, exist_ok=True)
    if not check:
        print(f"输出目录 : {OUT}")
    for name, desc, fn in TRACKS:
        fp = OUT / name
        if check:
            if fp.exists():
                print(f"OK   {name:10s} {fp.stat().st_size / 1024:7.1f} KB  {desc}")
            else:
                print(f"!!   {name:10s} 不存在 —— 跑 `python ui/make_audio.py` 生成")
            continue
        x = fn()
        with wave.open(str(fp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(wav_bytes(x))
        print(f"生成 {name:10s} {len(x) / SR:5.1f} s  "
              f"{fp.stat().st_size / 1024:7.1f} KB  {desc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
