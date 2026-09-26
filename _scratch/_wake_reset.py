# -*- coding: utf-8 -*-
"""唤醒词诊断 3：命中一次之后，检测器还活着吗。

    python _scratch/_wake_reset.py

前面两个脚本的结论都是错的，因为我把"喂的顺序"当成了无关变量。回头看所有跑过的
输出，形状一模一样：

    第一个喂进去的样本命中，之后**整场再没有任何一次命中** ——
    不管换声调拼法（24 种）、补静音（前补/后补/前后补）、还是换样本。

一个"补了静音就把原本能叫醒的样本弄哑"的结果，声学上不可能。它只可能是
**喂的顺序**在起作用，也就是我自己那层封装有问题：命中之后的那次 `reset()`
没把状态真正清干净。这个脚本把两件事分开量：

    A 同一个实例：样本1 → reset → 样本1（命中还能再来吗）
    B 每个样本都用**全新实例**喂（各自的第一口），看是不是都命中
    C 命中后不用 reset_stream，改用 create_stream() 重开一条流
    D 一条流上连喂三遍样本1，看第几遍开始哑

判据是"每次喂的命中与否"，不是"整体跑通了"。
"""
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "ui"))
sys.path.insert(0, str(ROOT / "ui" / "voice"))

import asr                                    # noqa: E402
from kws import WakeWord, SR                  # noqa: E402

CHUNK = 1600
SDIR = ROOT / "runs" / "wake_samples"


def pcm(stem: str):
    return asr.wav_bytes_to_float32((SDIR / (stem + ".wav")).read_bytes(), want_sr=SR)


def feed(w: WakeWord, x):
    hits = []
    for i in range(0, len(x), CHUNK):
        for d in w.feed(x[i:i + CHUNK]):
            hits.append((d, (i + CHUNK) / SR * 1000.0))
    return hits


def main() -> int:
    S1 = "pos_hello_xiaorui"
    S2 = "pos_hello_xiaorui2"
    S3 = "pos_hello_xiaorui_slow"
    x1, x2, x3 = pcm(S1), pcm(S2), pcm(S3)

    print("=" * 78)
    print("B 每个样本喂给**全新实例**（都是各自的第一口）—— 这一组最要紧")
    print("=" * 78)
    for stem, x in ((S1, x1), (S2, x2), (S3, x3)):
        w = WakeWord()
        h = feed(w, x)
        print("  %-26s %s" % (stem, ("✅ 命中 %s @%.0fms" % (h[0][0], h[0][1]))
                              if h else "❌ 第一口就没命中"))

    print("\n" + "=" * 78)
    print("A 同一个实例，同一段音频连喂两遍（中间走 reset）")
    print("=" * 78)
    w = WakeWord()
    for k in (1, 2, 3):
        h = feed(w, x1)
        print("  第 %d 遍：%s" % (k, ("命中 @%.0fms" % h[0][1]) if h else "没有"))

    print("\n" + "=" * 78)
    print("C 命中后**不用 reset_stream**，直接 create_stream() 重开一条流")
    print("=" * 78)
    w = WakeWord()
    h = feed(w, x1)
    print("  第 1 遍（reset_stream）：%s" % (("命中 @%.0fms" % h[0][1]) if h else "没有"))
    for k in (2, 3):
        w._stream = w._kws.create_stream()        # 硬换一条流
        h = feed(w, x1)
        print("  第 %d 遍（新 stream）：%s" % (k, ("命中 @%.0fms" % h[0][1]) if h else "没有"))

    print("\n" + "=" * 78)
    print("D 一条流连喂三遍，但**把命中后的 reset 关掉**（只看流自己的行为）")
    print("=" * 78)
    w = WakeWord({"debounce_s": 0.0})
    saved = w.reset
    w.reset = lambda: None                        # 故意不 reset
    for k in (1, 2, 3):
        h = feed(w, x1)
        print("  第 %d 遍：%s" % (k, "、".join("%s@%.0fms" % t for t in h) or "没有"))
    w.reset = saved

    print("\n" + "=" * 78)
    print("结论怎么用")
    print("=" * 78)
    print("  · B 组三行全命中 → 模型没问题，是**命中之后没有真正复位**。")
    print("    改 kws.py 的 reset()：命中后一律 create_stream() 换新流，别信 reset_stream。")
    print("  · B 组只有第一行命中 → 是真·漏唤醒，回到音频/模型层面查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
